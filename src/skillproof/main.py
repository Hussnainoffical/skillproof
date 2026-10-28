"""SkillProof HTTP API and local-first single-user application."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import MAX_CASE_STORAGE_BYTES, MAX_CONCURRENT_UPLOAD_REQUESTS, MAX_DISCREPANCY_SCAN_PAGES, MAX_DOCUMENTS_PER_CASE, MAX_EVIDENCE_PER_CASE, MAX_REQUIREMENTS_PER_CASE, MAX_TOTAL_STORAGE_BYTES, MAX_UPLOAD_BYTES, UPLOAD_DIR, WORKERS, ensure_data_dirs
from .db import connection, initialize, row_dict
from . import ai
from .processing import now_iso, page_suggestions, process_document


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    occupation: str = Field(default="", max_length=160)
    jurisdiction: str = Field(default="Germany", max_length=120)
    source_country: str = Field(default="", max_length=120)
    route: str = Field(default="", max_length=200)


class RequirementCreate(BaseModel):
    code: str = Field(default="", max_length=60)
    title: str = Field(min_length=1, max_length=240)
    guidance: str = Field(default="", max_length=2000)
    source_name: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=1000)
    source_checked_at: str = Field(default="", max_length=80)
    required: bool = True


class EvidenceCreate(BaseModel):
    requirement_id: str | None = None
    document_id: str
    page_number: int = Field(ge=1)
    region_id: str = Field(default="", max_length=100)
    claim_type: str = Field(default="supporting_evidence", max_length=80)
    claim_text: str = Field(min_length=1, max_length=4000)
    provenance: Literal["human_observed"] = "human_observed"


class EvidenceReview(BaseModel):
    disposition: Literal["unreviewed", "supports", "conflicts", "needs_expert", "not_relevant"]
    reviewer_note: str | None = Field(default=None, max_length=2000)


class CaseUpdate(BaseModel):
    status: Literal["open", "review", "ready", "archived"]


class AIAnalysisRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    requirement_id: str | None = None


def _require_case(case_id: str) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Case not found")
    return dict(row)


def _audit(conn: sqlite3.Connection, case_id: str, action: str, object_type: str, object_id: str, details: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_events(id,case_id,action,object_type,object_id,details_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), case_id, action, object_type, object_id, json.dumps(details or {}, ensure_ascii=False), now_iso()),
    )


def _validate_source_url(source_url: str) -> None:
    if not source_url:
        return
    if any(ord(char) < 0x21 or char == "\\" for char in source_url):
        raise HTTPException(422, "Source URL must not contain spaces, control characters, or backslashes")
    try:
        parts = urlsplit(source_url)
        port = parts.port
    except ValueError as exc:
        raise HTTPException(422, "Source URL is malformed") from exc
    if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username or parts.password or (port is not None and not 1 <= port <= 65535):
        raise HTTPException(422, "Source URL must be a valid HTTP(S) URL without embedded credentials")


def _safe_name(name: str) -> str:
    base = PureWindowsPath(name.replace("/", "\\")).name
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", base).strip(" .")[:140]
    return base or "uploaded-document"


def _detect_type(prefix: bytes, name: str) -> tuple[str, str] | None:
    ext = Path(name).suffix.lower()
    if prefix.startswith(b"%PDF-") and ext == ".pdf":
        return "application/pdf", ".pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n") and ext == ".png":
        return "image/png", ".png"
    if prefix.startswith(b"\xff\xd8\xff") and ext in {".jpg", ".jpeg"}:
        return "image/jpeg", ".jpg"
    if prefix.startswith((b"II*\x00", b"MM\x00*")) and ext in {".tif", ".tiff"}:
        return "image/tiff", ".tiff"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP" and ext == ".webp":
        return "image/webp", ".webp"
    return None


async def _store_upload(upload: UploadFile, document_id: str) -> tuple[str, str, int, str]:
    source_name = _safe_name(upload.filename or "uploaded-document")
    prefix = await upload.read(32)
    if not prefix:
        raise HTTPException(400, "The uploaded file is empty")
    detected = _detect_type(prefix, source_name)
    if detected is None:
        raise HTTPException(415, "Use a valid PDF or PNG/JPEG/TIFF/WebP image with its matching file extension")
    media_type, suffix = detected
    storage_name = f"{document_id}{suffix}"
    if len(prefix) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
    target = UPLOAD_DIR / storage_name
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("xb") as output:
            output.write(prefix)
            digest.update(prefix)
            size += len(prefix)
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
                digest.update(chunk)
                output.write(chunk)
        return storage_name, media_type, size, digest.hexdigest()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _case_detail(case_id: str, evidence_limit: int | None = 50) -> dict:
    _require_case(case_id)
    with connection() as conn:
        case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
        requirements = [dict(row) for row in conn.execute("""SELECT r.*,
            count(e.id) AS evidence_count,
            sum(CASE WHEN e.disposition='supports' THEN 1 ELSE 0 END) AS supported_count,
            sum(CASE WHEN e.disposition='unreviewed' THEN 1 ELSE 0 END) AS unreviewed_count
            FROM requirements r LEFT JOIN evidence e ON e.requirement_id=r.id
            WHERE r.case_id=? AND r.is_current=1 GROUP BY r.id ORDER BY r.created_at,r.id""", (case_id,))]
        documents = [dict(row) for row in conn.execute("SELECT id,case_id,original_name,media_type,size_bytes,sha256,status,error_code,error_message,page_count,extracted_chars,uploaded_at FROM documents WHERE case_id=? ORDER BY uploaded_at DESC", (case_id,))]
        evidence_total = conn.execute("SELECT count(*) FROM evidence WHERE case_id=?", (case_id,)).fetchone()[0]
        evidence_pending = conn.execute("SELECT count(*) FROM evidence WHERE case_id=? AND disposition='unreviewed'", (case_id,)).fetchone()[0]
        evidence_sql = """SELECT e.*, d.original_name, r.title AS requirement_title, r.version AS requirement_version
            FROM evidence e JOIN documents d ON d.id=e.document_id
            LEFT JOIN requirements r ON r.id=e.requirement_id
            WHERE e.case_id=? ORDER BY e.created_at DESC,e.id DESC"""
        if evidence_limit is None:
            evidence = [dict(row) for row in conn.execute(evidence_sql, (case_id,))]
        else:
            evidence = [dict(row) for row in conn.execute(evidence_sql + " LIMIT ?", (case_id, evidence_limit))]
        jobs = [dict(row) for row in conn.execute("SELECT j.* FROM jobs j JOIN documents d ON d.id=j.document_id WHERE d.case_id=? ORDER BY j.created_at DESC LIMIT 30", (case_id,))]
        events = [dict(row) for row in conn.execute("SELECT action,object_type,object_id,details_json,created_at FROM audit_events WHERE case_id=? ORDER BY created_at DESC LIMIT 30", (case_id,))]
    for event in events:
        try:
            event["details"] = json.loads(event.pop("details_json"))
        except json.JSONDecodeError:
            event["details"] = {}
    cursor = {"created_at": evidence[-1]["created_at"], "id": evidence[-1]["id"]} if evidence_limit is not None and evidence_total > len(evidence) and evidence else None
    return {"case": case, "requirements": requirements, "documents": documents, "evidence": evidence, "evidence_total": evidence_total, "evidence_pending": evidence_pending, "evidence_cursor": cursor, "jobs": jobs, "events": events}


def _potential_discrepancies(case_id: str) -> tuple[list[dict], int, bool]:
    """Find only label-keyed, cross-file text differences for a person to inspect."""
    aliases = {
        "name": "name", "full name": "name", "candidate name": "name", "student name": "name",
        "programme": "qualification", "program": "qualification", "qualification": "qualification", "award": "qualification", "degree": "qualification",
        "institution": "institution", "awarding institution": "institution", "awarding body": "institution", "university": "institution",
        "date of birth": "date_of_birth", "birth date": "date_of_birth",
        "training period": "training_period", "study period": "training_period", "period of study": "training_period",
    }
    pattern = re.compile(r"^\s*([A-Za-z][A-Za-z /-]{1,45})\s*[:–—-]\s*(.{2,180})\s*$")
    fields: dict[str, dict[str, dict]] = {}
    pages_scanned = 0
    truncated = False
    with connection() as conn:
        rows = conn.execute("SELECT d.id AS document_id,d.original_name,p.page_number,p.text FROM pages p JOIN documents d ON d.id=p.document_id WHERE d.case_id=? AND d.status IN ('ready','partial','needs_ocr') ORDER BY d.uploaded_at,d.id,p.page_number LIMIT ?", (case_id, MAX_DISCREPANCY_SCAN_PAGES + 1))
        for row in rows:
            if pages_scanned >= MAX_DISCREPANCY_SCAN_PAGES:
                truncated = True
                break
            pages_scanned += 1
            for line in row["text"].splitlines():
                match = pattern.match(line.strip())
                if not match:
                    continue
                key = aliases.get(match.group(1).strip().lower())
                value = " ".join(match.group(2).split())[:180]
                if key and value:
                    fields.setdefault(key, {}).setdefault(row["document_id"], {"document_id": row["document_id"], "document_name": row["original_name"], "page_number": row["page_number"], "value": value})
    result = []
    for field, by_document in fields.items():
        if len(by_document) < 2:
            continue
        values = []
        values.extend(by_document.values())
        normalized = {re.sub(r"[^\w]", "", item["value"]).casefold() for item in values}
        if len(normalized) > 1:
            result.append({"field": field.replace("_", " "), "values": values, "status": "review_required"})
    return result, pages_scanned, truncated


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_dirs()
    initialize()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="skillproof")
    app.state.pool = pool
    # Resume queued work after a clean application restart.
    with connection() as conn:
        stale = conn.execute("SELECT id,document_id FROM jobs WHERE state IN ('queued','running') ORDER BY created_at").fetchall()
        for job in stale:
            conn.execute("UPDATE jobs SET state='queued',updated_at=? WHERE id=?", (now_iso(), job["id"]))
            pool.submit(process_document, job["document_id"], job["id"])
    yield
    pool.shutdown(wait=False, cancel_futures=False)


app = FastAPI(
    title="SkillProof",
    description="Local-first, page-linked qualification document preparation for human review. Not an eligibility or equivalence decision system.",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class UploadBodyLimitMiddleware:
    """Reject oversized multipart bodies before Starlette spools uploads to disk."""

    # Multipart boundaries, headers, and the single file field need bounded room
    # beyond the configured file cap. This also limits unexpected extra form fields.
    multipart_overhead_bytes = 128 * 1024

    def __init__(self, app, max_file_bytes: int = MAX_UPLOAD_BYTES, max_concurrent_uploads: int = MAX_CONCURRENT_UPLOAD_REQUESTS):
        self.app = app
        self.max_body_bytes = max_file_bytes + self.multipart_overhead_bytes
        self.upload_slots = threading.BoundedSemaphore(max_concurrent_uploads)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or scope.get("method") != "POST" or not re.fullmatch(r"/api/cases/[^/]+/documents", path):
            await self.app(scope, receive, send)
            return

        if not self.upload_slots.acquire(blocking=False):
            await self._reject(send, 429)
            return
        try:
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            raw_length = headers.get(b"content-length", b"")
            if raw_length.isdigit() and int(raw_length) > self.max_body_bytes:
                await self._reject(send, 413)
                return

            received = 0

            class OversizedBody(Exception):
                pass

            async def bounded_receive():
                nonlocal received
                message = await receive()
                if message.get("type") == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body_bytes:
                        raise OversizedBody
                return message

            try:
                await self.app(scope, bounded_receive, send)
            except OversizedBody:
                await self._reject(send, 413)
        finally:
            self.upload_slots.release()

    @staticmethod
    async def _reject(send, status_code: int):
        message = "Upload request exceeds the configured size limit" if status_code == 413 else "Too many concurrent upload requests; retry shortly"
        body = json.dumps({"detail": message}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status_code == 429:
            headers.append((b"retry-after", b"10"))
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(UploadBodyLimitMiddleware)


@app.middleware("http")
async def local_security_headers(request: Request, call_next):
    hostname = (request.url.hostname or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"detail": "SkillProof is restricted to loopback hosts in this build"}, status_code=400)
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        origin_parts = urlsplit(origin)
        host = request.headers.get("host", "").lower()
        if origin_parts.scheme not in {"http", "https"} or origin_parts.netloc.lower() != host:
            return JSONResponse({"detail": "Cross-origin state changes are blocked in local mode"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-src 'self'; object-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/ai/status", tags=["ai"])
def ai_status() -> dict:
    return ai.status()


@app.post("/api/cases/{case_id}/ai/analyze", tags=["ai"])
def analyze_case(case_id: str, payload: AIAnalysisRequest) -> dict:
    _require_case(case_id)
    return ai.analyze(case_id, payload.question.strip(), payload.requirement_id)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    with connection() as conn:
        queued = conn.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    return {"status": "ok", "product": "skillproof", "stage": "local-review-mvp", "queued_jobs": queued, "storage": "local"}


@app.get("/api/cases", tags=["cases"])
def list_cases() -> list[dict]:
    with connection() as conn:
        rows = conn.execute("""SELECT c.*,
            (SELECT count(*) FROM documents d WHERE d.case_id=c.id) AS document_count,
            (SELECT count(*) FROM requirements r WHERE r.case_id=c.id AND r.is_current=1) AS requirement_count,
            (SELECT count(*) FROM evidence e WHERE e.case_id=c.id AND e.disposition='unreviewed') AS pending_review_count
            FROM cases c ORDER BY updated_at DESC""").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/cases", status_code=201, tags=["cases"])
def create_case(payload: CaseCreate) -> dict:
    case_id, now = str(uuid.uuid4()), now_iso()
    with connection() as conn:
        conn.execute("INSERT INTO cases(id,title,occupation,jurisdiction,source_country,route,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (case_id, payload.title.strip(), payload.occupation.strip(), payload.jurisdiction.strip(), payload.source_country.strip(), payload.route.strip(), now, now))
        _audit(conn, case_id, "case.created", "case", case_id)
    return _case_detail(case_id)


@app.post("/api/demo", status_code=201, tags=["cases"])
def create_demo() -> dict:
    """Create a clearly synthetic fixture for trying the evidence-review workflow."""
    case_id, now = str(uuid.uuid4()), now_iso()
    reqs = [
        ("DOC-CERT", "Award certificate", "Synthetic demonstration checklist item; replace with the applicable official source.", "Synthetic demo", "", ""),
        ("DOC-TRANSCRIPT", "Transcript or training record", "Synthetic demonstration checklist item; replace with the applicable official source.", "Synthetic demo", "", ""),
        ("DOC-TRANSLATION", "Translation evidence when needed", "Confirm what the responsible authority requires for this case.", "Synthetic demo", "", ""),
    ]
    pages = [
        (str(uuid.uuid4()), "synthetic-award-letter.txt", "Synthetic demo record — not a real credential or person.\nName: Amina Example\nAward: Diploma in Sustainable Energy Systems\nAwarding institution: Alpine Technical Institute\nAward date: 12 June 2019\nThis fictional sample exists only to show page-linked review."),
        (str(uuid.uuid4()), "synthetic-training-record.txt", "Synthetic demo record — not a real credential or person.\nName: Amina Example\nProgramme: Diploma in Sustainable Energy Systems\nInstitution: Alpine Technical Institute West\nTraining period: 2017–2020\nTranslation status: no translator statement present in this fictional file."),
    ]
    with connection() as conn:
        conn.execute("INSERT INTO cases(id,title,occupation,jurisdiction,source_country,route,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (case_id, "Synthetic qualification review", "Renewable energy technician (fictional)", "Germany — demo only", "Exampleland (fictional)", "No official route selected", now, now))
        req_ids = []
        for code, title, guidance, source_name, source_url, checked in reqs:
            rid = str(uuid.uuid4())
            req_ids.append(rid)
            conn.execute("INSERT INTO requirements(id,case_id,code,title,guidance,source_name,source_url,source_checked_at,required,version,chain_id,supersedes_id,is_current,created_at) VALUES(?,?,?,?,?,?,?,?,1,1,?,'',1,?)", (rid, case_id, code, title, guidance, source_name, source_url, checked, rid, now))
        doc_ids = []
        for doc_id, filename, text in pages:
            doc_ids.append(doc_id)
            conn.execute("INSERT INTO documents(id,case_id,original_name,media_type,status,page_count,extracted_chars,uploaded_at) VALUES(?,?,?,?,?,?,?,?)", (doc_id, case_id, filename, "text/plain", "ready", 1, len(text), now))
            conn.execute("INSERT INTO pages(id,document_id,page_number,text,regions_json,tables_json,ocr_used) VALUES(?,?,?,?,?,?,0)", (str(uuid.uuid4()), doc_id, 1, text, "[]", "[]"))
        claims = [
            (req_ids[0], doc_ids[0], "Award: Diploma in Sustainable Energy Systems"),
            (req_ids[1], doc_ids[1], "Training period: 2017–2020"),
            (req_ids[1], doc_ids[0], "Award date: 12 June 2019"),
        ]
        for requirement_id, document_id, claim in claims:
            conn.execute("INSERT INTO evidence(id,case_id,requirement_id,document_id,page_number,claim_type,claim_text,provenance,disposition,created_at,updated_at) VALUES(?,?,?,?,1,'supporting_evidence',?,'human_observed','unreviewed',?,?)", (str(uuid.uuid4()), case_id, requirement_id, document_id, claim, now, now))
        _audit(conn, case_id, "demo.created", "case", case_id, {"synthetic_only": True})
    return _case_detail(case_id)


@app.get("/api/cases/{case_id}", tags=["cases"])
def get_case(case_id: str) -> dict:
    return _case_detail(case_id)


@app.get("/api/cases/{case_id}/evidence", tags=["evidence"])
def list_case_evidence(case_id: str, offset: int = Query(default=0, ge=0, le=100_000), limit: int = Query(default=50, ge=1, le=100), before_created_at: str | None = Query(default=None, max_length=64), before_id: str | None = Query(default=None, max_length=64)) -> dict:
    if bool(before_created_at) != bool(before_id):
        raise HTTPException(422, "Both evidence cursor fields are required")
    _require_case(case_id)
    with connection() as conn:
        total = conn.execute("SELECT count(*) FROM evidence WHERE case_id=?", (case_id,)).fetchone()[0]
        evidence_sql = """SELECT e.*, d.original_name, r.title AS requirement_title, r.version AS requirement_version
            FROM evidence e JOIN documents d ON d.id=e.document_id
            LEFT JOIN requirements r ON r.id=e.requirement_id
            WHERE e.case_id=?"""
        params: tuple = (case_id,)
        if before_created_at is not None:
            evidence_sql += " AND (e.created_at < ? OR (e.created_at=? AND e.id < ?))"
            params = (case_id, before_created_at, before_created_at, before_id)
            rows = conn.execute(evidence_sql + " ORDER BY e.created_at DESC,e.id DESC LIMIT ?", (*params, limit + 1)).fetchall()
        else:
            rows = conn.execute(evidence_sql + " ORDER BY e.created_at DESC,e.id DESC LIMIT ? OFFSET ?", (*params, limit + 1, offset)).fetchall()
    has_more = len(rows) > limit
    items = [dict(row) for row in rows[:limit]]
    cursor = {"created_at": items[-1]["created_at"], "id": items[-1]["id"]} if has_more and items else None
    return {"items": items, "offset": offset, "limit": limit, "total": total, "has_more": has_more, "next_cursor": cursor}


@app.get("/api/cases/{case_id}/checks", tags=["review"])
def get_case_checks(case_id: str) -> dict:
    _require_case(case_id)
    differences, pages_scanned, truncated = _potential_discrepancies(case_id)
    notice = "Text-pattern differences are review prompts only. They do not establish an error, identity mismatch, fraud, or qualification outcome."
    if truncated:
        notice += f" This scan inspected the first {MAX_DISCREPANCY_SCAN_PAGES:,} pages only; later pages were not checked."
    return {"potential_discrepancies": differences, "pages_scanned": pages_scanned, "partial_scan": truncated, "notice": notice}


@app.patch("/api/cases/{case_id}", tags=["cases"])
def update_case(case_id: str, payload: CaseUpdate) -> dict:
    _require_case(case_id)
    with connection() as conn:
        conn.execute("UPDATE cases SET status=?,updated_at=? WHERE id=?", (payload.status, now_iso(), case_id))
        _audit(conn, case_id, "case.status_changed", "case", case_id, {"status": payload.status})
    return _case_detail(case_id)


@app.delete("/api/cases/{case_id}", status_code=204, tags=["cases"])
def delete_case(case_id: str) -> Response:
    _require_case(case_id)
    with connection() as conn:
        names = [row[0] for row in conn.execute("SELECT storage_name FROM documents WHERE case_id=? AND storage_name!=''", (case_id,))]
        conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
    for name in names:
        candidate = (UPLOAD_DIR / name).resolve()
        if candidate.parent == UPLOAD_DIR.resolve():
            candidate.unlink(missing_ok=True)
    return Response(status_code=204)


@app.post("/api/cases/{case_id}/requirements", status_code=201, tags=["requirements"])
def add_requirement(case_id: str, payload: RequirementCreate) -> dict:
    _require_case(case_id)
    _validate_source_url(payload.source_url.strip())
    requirement_id, now = str(uuid.uuid4()), now_iso()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current_count = conn.execute("SELECT count(*) FROM requirements WHERE case_id=? AND is_current=1", (case_id,)).fetchone()[0]
        if current_count >= MAX_REQUIREMENTS_PER_CASE:
            raise HTTPException(409, f"This case has reached the {MAX_REQUIREMENTS_PER_CASE}-requirement limit")
        conn.execute("INSERT INTO requirements(id,case_id,code,title,guidance,source_name,source_url,source_checked_at,required,version,chain_id,supersedes_id,is_current,created_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,'',1,?)", (requirement_id, case_id, payload.code.strip(), payload.title.strip(), payload.guidance.strip(), payload.source_name.strip(), payload.source_url.strip(), payload.source_checked_at.strip(), int(payload.required), requirement_id, now))
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (now, case_id))
        _audit(conn, case_id, "requirement.added", "requirement", requirement_id, {"title": payload.title})
        row = conn.execute("SELECT * FROM requirements WHERE id=?", (requirement_id,)).fetchone()
    return dict(row)


@app.put("/api/requirements/{requirement_id}", status_code=201, tags=["requirements"])
def revise_requirement(requirement_id: str, payload: RequirementCreate) -> dict:
    """Create an immutable checklist revision; linked evidence keeps the prior requirement ID."""
    _validate_source_url(payload.source_url.strip())
    new_id, now = str(uuid.uuid4()), now_iso()
    with connection() as conn:
        # Serialize concurrent edits and let the second reviewer see the
        # first committed revision before deciding whether it is still current.
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT * FROM requirements WHERE id=? AND is_current=1", (requirement_id,)).fetchone()
        if old is None:
            raise HTTPException(409, "This requirement has already been revised or removed; refresh its history")
        version = old["version"] + 1
        conn.execute("UPDATE requirements SET is_current=0 WHERE id=?", (requirement_id,))
        conn.execute("INSERT INTO requirements(id,case_id,code,title,guidance,source_name,source_url,source_checked_at,required,version,chain_id,supersedes_id,is_current,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (new_id, old["case_id"], payload.code.strip(), payload.title.strip(), payload.guidance.strip(), payload.source_name.strip(), payload.source_url.strip(), payload.source_checked_at.strip(), int(payload.required), version, old["chain_id"] or old["id"], requirement_id, 1, now))
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (now, old["case_id"]))
        _audit(conn, old["case_id"], "requirement.revised", "requirement", new_id, {"supersedes_id": requirement_id, "version": version})
        row = conn.execute("SELECT * FROM requirements WHERE id=?", (new_id,)).fetchone()
    return dict(row)


@app.get("/api/requirements/{requirement_id}/history", tags=["requirements"])
def requirement_history(requirement_id: str) -> list[dict]:
    with connection() as conn:
        exists = conn.execute("SELECT chain_id FROM requirements WHERE id=?", (requirement_id,)).fetchone()
        if exists is None:
            raise HTTPException(404, "Requirement not found")
        rows = conn.execute("SELECT * FROM requirements WHERE chain_id=? ORDER BY version", (exists["chain_id"],)).fetchall()
    return [dict(row) for row in rows]


@app.delete("/api/requirements/{requirement_id}", status_code=204, tags=["requirements"])
def delete_requirement(requirement_id: str) -> Response:
    with connection() as conn:
        row = conn.execute("SELECT * FROM requirements WHERE id=? AND is_current=1", (requirement_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Requirement not found")
        _audit(conn, row["case_id"], "requirement.removed", "requirement", requirement_id, {"title": row["title"]})
        conn.execute("UPDATE requirements SET is_current=0 WHERE id=?", (requirement_id,))
    return Response(status_code=204)


@app.post("/api/cases/{case_id}/documents", status_code=202, tags=["documents"])
async def upload_document(case_id: str, request: Request, file: UploadFile = File(...)) -> dict:
    _require_case(case_id)
    with connection() as conn:
        active = conn.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    if active >= max(8, WORKERS * 4):
        raise HTTPException(429, "The local processing queue is full. Wait for current files to finish, then retry.", headers={"Retry-After": "15"})
    document_id, job_id, now = str(uuid.uuid4()), str(uuid.uuid4()), now_iso()
    storage_name, media_type, size, digest = await _store_upload(file, document_id)
    display_name = _safe_name(file.filename or "uploaded-document")
    try:
        with connection() as conn:
            # The count and insertion share a write lock. Without this, two
            # simultaneous uploads could both pass a stale capacity check.
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if active >= max(8, WORKERS * 4):
                raise HTTPException(429, "The local processing queue is full. Wait for current files to finish, then retry.", headers={"Retry-After": "15"})
            case_storage = conn.execute("SELECT count(*),coalesce(sum(size_bytes),0) FROM documents WHERE case_id=?", (case_id,)).fetchone()
            if case_storage[0] >= MAX_DOCUMENTS_PER_CASE:
                raise HTTPException(409, f"This case has reached the {MAX_DOCUMENTS_PER_CASE}-document limit")
            if case_storage[1] + size > MAX_CASE_STORAGE_BYTES:
                raise HTTPException(413, "This upload exceeds the per-case storage budget")
            total_storage = conn.execute("SELECT coalesce(sum(size_bytes),0) FROM documents").fetchone()[0]
            if total_storage + size > MAX_TOTAL_STORAGE_BYTES:
                raise HTTPException(413, "This upload exceeds the local workspace storage budget")
            duplicate = conn.execute("SELECT id,original_name FROM documents WHERE case_id=? AND sha256=? AND sha256!=''", (case_id, digest)).fetchone()
            if duplicate:
                (UPLOAD_DIR / storage_name).unlink(missing_ok=True)
                raise HTTPException(409, f"This file is already in the case as {duplicate['original_name']}", headers={"X-Duplicate-Document": duplicate["id"]})
            conn.execute("INSERT INTO documents(id,case_id,original_name,storage_name,media_type,size_bytes,sha256,status,uploaded_at) VALUES(?,?,?,?,?,?,?,'queued',?)", (document_id, case_id, display_name, storage_name, media_type, size, digest, now))
            conn.execute("INSERT INTO jobs(id,document_id,state,created_at,updated_at) VALUES(?,?,'queued',?,?)", (job_id, document_id, now, now))
            _audit(conn, case_id, "document.uploaded", "document", document_id, {"bytes": size, "media_type": media_type, "sha256": digest})
        try:
            request.app.state.pool.submit(process_document, document_id, job_id)
        except RuntimeError:
            with connection() as conn:
                conn.execute("UPDATE documents SET status='failed',error_code='PROCESSING_QUEUE_UNAVAILABLE',error_message='The local worker pool stopped before this file could be queued.' WHERE id=?", (document_id,))
                conn.execute("UPDATE jobs SET state='failed',error_code='PROCESSING_QUEUE_UNAVAILABLE',updated_at=? WHERE id=?", (now_iso(), job_id))
                _audit(conn, case_id, "document.queue_failed", "document", document_id, {"code": "PROCESSING_QUEUE_UNAVAILABLE"})
            return {"document_id": document_id, "job_id": job_id, "state": "failed", "error_code": "PROCESSING_QUEUE_UNAVAILABLE", "max_upload_bytes": MAX_UPLOAD_BYTES}
    except Exception:
        (UPLOAD_DIR / storage_name).unlink(missing_ok=True)
        raise
    return {"document_id": document_id, "job_id": job_id, "state": "queued", "sha256": digest, "max_upload_bytes": MAX_UPLOAD_BYTES}


@app.delete("/api/documents/{document_id}", status_code=204, tags=["documents"])
def delete_document(document_id: str) -> Response:
    with connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        _audit(conn, row["case_id"], "document.deleted", "document", document_id, {"filename": row["original_name"]})
        name = row["storage_name"]
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
    if name:
        candidate = (UPLOAD_DIR / name).resolve()
        if candidate.parent == UPLOAD_DIR.resolve():
            candidate.unlink(missing_ok=True)
    return Response(status_code=204)


@app.get("/api/jobs/{job_id}", tags=["documents"])
def get_job(job_id: str) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Processing job not found")
    return dict(row)


@app.get("/api/documents/{document_id}/pages/{page_number}", tags=["documents"])
def get_page(document_id: str, page_number: int) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT p.*,d.original_name,d.case_id FROM pages p JOIN documents d ON d.id=p.document_id WHERE p.document_id=? AND p.page_number=?", (document_id, page_number)).fetchone()
    if row is None:
        raise HTTPException(404, "Page not found. The document may still be processing.")
    item = dict(row)
    item["regions"] = json.loads(item.pop("regions_json"))
    item["tables"] = json.loads(item.pop("tables_json"))
    item["text_truncated_for_display"] = len(item["text"]) > 40_000
    item["text"] = item["text"][:40_000]
    item["suggestions"] = []
    for kind, quote in page_suggestions(item["text"]):
        quote_key = " ".join(quote.split()).casefold()
        region = next((r["id"] for r in item["regions"] if quote_key and quote_key in " ".join(r["text"].split()).casefold()), "")
        item["suggestions"].append({"claim_type": kind, "claim_text": quote, "region_id": region})
    return item


@app.get("/api/documents/{document_id}/source", tags=["documents"])
def document_source(document_id: str, page: int = 1) -> FileResponse:
    with connection() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if doc is None:
        raise HTTPException(404, "Document not found")
    if not doc["storage_name"]:
        raise HTTPException(404, "Synthetic demo pages do not have an uploaded source file")
    path = (UPLOAD_DIR / doc["storage_name"]).resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "Source file is unavailable")
    return FileResponse(path, media_type=doc["media_type"], filename=doc["original_name"], content_disposition_type="inline")


@app.post("/api/cases/{case_id}/evidence", status_code=201, tags=["evidence"])
def add_evidence(case_id: str, payload: EvidenceCreate) -> dict:
    _require_case(case_id)
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = conn.execute("SELECT case_id FROM documents WHERE id=?", (payload.document_id,)).fetchone()
        if doc is None or doc["case_id"] != case_id:
            raise HTTPException(404, "Document not found in this case")
        page = conn.execute("SELECT text FROM pages WHERE document_id=? AND page_number=?", (payload.document_id, payload.page_number)).fetchone()
        if page is None:
            raise HTTPException(404, "Source page is not available")
        if payload.requirement_id:
            req = conn.execute("SELECT case_id FROM requirements WHERE id=?", (payload.requirement_id,)).fetchone()
            if req is None or req["case_id"] != case_id:
                raise HTTPException(422, "Requirement must belong to this case")
        if payload.region_id:
            region_row = conn.execute("SELECT regions_json FROM pages WHERE document_id=? AND page_number=?", (payload.document_id, payload.page_number)).fetchone()
            try:
                region_ids = {region["id"] for region in json.loads(region_row["regions_json"])}
            except (TypeError, json.JSONDecodeError):
                region_ids = set()
            if payload.region_id not in region_ids:
                raise HTTPException(422, "Region must belong to the selected source page")
        quote = " ".join(payload.claim_text.split())
        if quote not in " ".join(page["text"].split()):
            raise HTTPException(422, "Evidence text must be an exact excerpt from the selected source page")
        duplicate = conn.execute("SELECT id FROM evidence WHERE case_id=? AND document_id=? AND page_number=? AND requirement_id IS ? AND region_id=? AND claim_text=? LIMIT 1", (case_id, payload.document_id, payload.page_number, payload.requirement_id, payload.region_id, quote)).fetchone()
        if duplicate:
            raise HTTPException(409, "This exact excerpt is already linked to this requirement and source region")
        evidence_count = conn.execute("SELECT count(*) FROM evidence WHERE case_id=?", (case_id,)).fetchone()[0]
        if evidence_count >= MAX_EVIDENCE_PER_CASE:
            raise HTTPException(409, f"This case has reached the {MAX_EVIDENCE_PER_CASE:,}-evidence-item limit")
        evidence_id, now = str(uuid.uuid4()), now_iso()
        conn.execute("INSERT INTO evidence(id,case_id,requirement_id,document_id,page_number,region_id,claim_type,claim_text,provenance,disposition,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'unreviewed',?,?)", (evidence_id, case_id, payload.requirement_id, payload.document_id, payload.page_number, payload.region_id, payload.claim_type, quote, payload.provenance, now, now))
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (now, case_id))
        _audit(conn, case_id, "evidence.captured", "evidence", evidence_id, {"page_number": payload.page_number, "provenance": payload.provenance})
        row = conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
    return dict(row)


@app.patch("/api/evidence/{evidence_id}", tags=["evidence"])
def review_evidence(evidence_id: str, payload: EvidenceReview) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Evidence item not found")
        now = now_iso()
        provenance = "human_verified" if payload.disposition in {"supports", "conflicts", "needs_expert", "not_relevant"} else ("human_observed" if row["provenance"] == "human_verified" else row["provenance"])
        note = row["reviewer_note"] if payload.reviewer_note is None else payload.reviewer_note.strip()
        conn.execute("UPDATE evidence SET disposition=?,reviewer_note=?,provenance=?,updated_at=? WHERE id=?", (payload.disposition, note, provenance, now, evidence_id))
        _audit(conn, row["case_id"], "evidence.reviewed", "evidence", evidence_id, {"disposition": payload.disposition})
        result = conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
    return dict(result)


def _md(value: str) -> str:
    normalized = " ".join(str(value or "").split())
    return re.sub(r"([\\`*_{}\[\]()#+.!>|])", r"\\\1", normalized)


@app.get("/api/cases/{case_id}/packet.md", tags=["export"])
def export_packet(case_id: str) -> Response:
    detail = _case_detail(case_id, evidence_limit=None)
    case = detail["case"]
    lines = [
        f"# Human-reviewed qualification evidence packet: {_md(case['title'])}",
        "",
        f"**Status:** {_md(case['status'])} · **Occupation:** {_md(case['occupation'])} · **Jurisdiction:** {_md(case['jurisdiction'])}",
        f"**Source country:** {_md(case['source_country']) or 'Not recorded'} · **Route:** {_md(case['route']) or 'Not recorded'}",
        "",
        "> This packet organizes evidence for human review. It does not verify authenticity, decide qualification equivalence, establish legal eligibility, rank a person, or replace the competent authority.",
        "",
        "## Requirements and source versions",
        "",
        "| Requirement | Required | Guidance | Source | Last checked | Review state |",
        "|---|---:|---|---|---|---|",
    ]
    for req in detail["requirements"]:
        evidence = [e for e in detail["evidence"] if e["requirement_id"] == req["id"]]
        states = sorted({e["disposition"] for e in evidence}) or ["no evidence linked"]
        source = _md(req["source_name"])
        if req["source_url"]:
            source = f"[{source or 'source'}]({_md(req['source_url'])})"
        lines.append(f"| v{req['version']} · {_md(req['title'])} | {'Yes' if req['required'] else 'No'} | {_md(req['guidance'])} | {source or 'Not recorded'} | {_md(req['source_checked_at']) or 'Not recorded'} | {', '.join(states)} |")
    lines += ["", "## Evidence and reviewer dispositions", "", "| Claim excerpt | Requirement version | Source file | Page | Provenance | Disposition | Reviewer note |", "|---|---|---|---:|---|---|---|"]
    for item in detail["evidence"]:
        requirement_label = f"v{item['requirement_version']} · {_md(item['requirement_title'])}" if item["requirement_title"] else "Unassigned"
        lines.append(f"| {_md(item['claim_text'])} | {requirement_label} | {_md(item['original_name'])} | {item['page_number']} | {_md(item['provenance'])} | {_md(item['disposition'])} | {_md(item['reviewer_note'])} |")
    lines += ["", "## Files", ""]
    for doc in detail["documents"]:
        lines.append(f"- {_md(doc['original_name'])}: {_md(doc['status'])}, {doc['page_count']} pages, {doc['extracted_chars']} extracted characters, SHA-256 `{doc['sha256'] or 'synthetic demo'}`")
        if doc["error_message"]:
            lines.append(f"  - Processing note: {_md(doc['error_message'])}")
    lines += ["", "## Limitations", "", "Text extraction, OCR suggestions, and reviewer notes can be wrong or incomplete. Inspect each cited original page. A missing excerpt is not evidence of fraud or non-qualification. Requirements need an authoritative source and current review date.", ""]
    content = "\n".join(lines)
    return Response(content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=skillproof-{case_id[:8]}-packet.md"})
