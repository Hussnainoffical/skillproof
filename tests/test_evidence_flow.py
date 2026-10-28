from __future__ import annotations

import io
import sqlite3
import time
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from skillproof import config, db, main, processing


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "runtime"
    uploads = data / "uploads"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(config, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(db, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(processing, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    with TestClient(main.app) as test_client:
        yield test_client


def pdf_bytes(text: str, page_count: int = 1) -> bytes:
    writer = PdfWriter()
    pages = [writer.add_blank_page(width=612, height=792) for _ in range(page_count)]
    page = pages[0]
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
    page[NameObject("/MediaBox")] = page.mediabox
    lines = text.splitlines() or [text]
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({safe}) Tj")
        if index < len(lines) - 1:
            commands.append("0 -16 Td")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def wait_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        result = client.get(f"/api/jobs/{job_id}").json()
        if result["state"] in {"complete", "failed"}:
            return result
        time.sleep(0.025)
    raise AssertionError("Document processing did not finish within the test deadline")


def test_local_pdf_to_human_review_and_export(client):
    case = client.post("/api/cases", json={"title": "Synthetic test case", "occupation": "Technician"})
    assert case.status_code == 201
    case_id = case.json()["case"]["id"]
    requirement = client.post(f"/api/cases/{case_id}/requirements", json={
        "title": "Certificate and award date", "source_name": "Synthetic checklist", "source_checked_at": "2026-10-28", "guidance": "Synthetic-only test requirement."
    })
    assert requirement.status_code == 201
    requirement_id = requirement.json()["id"]

    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("certificate.pdf", pdf_bytes("Award: Diploma in Energy Systems\nInstitution: Example Institute\nAward date: 2019"), "application/pdf")})
    assert upload.status_code == 202
    result = wait_job(client, upload.json()["job_id"])
    assert result["state"] == "complete"

    document_id = upload.json()["document_id"]
    detail = client.get(f"/api/documents/{document_id}/pages/1")
    assert detail.status_code == 200
    page = detail.json()
    assert "Award: Diploma in Energy Systems" in page["text"]
    assert page["regions"]
    suggestion = next(item for item in page["suggestions"] if item["claim_text"] == "Award: Diploma in Energy Systems")
    assert suggestion["region_id"]

    invalid_region = client.post(f"/api/cases/{case_id}/evidence", json={
        "requirement_id": requirement_id, "document_id": document_id, "page_number": 1,
        "claim_text": "Award: Diploma in Energy Systems", "region_id": "not-on-this-page", "provenance": "human_observed"
    })
    assert invalid_region.status_code == 422

    evidence = client.post(f"/api/cases/{case_id}/evidence", json={
        "requirement_id": requirement_id,
        "document_id": document_id,
        "page_number": 1,
        "claim_type": "qualification",
        "claim_text": "Award: Diploma in Energy Systems",
        "region_id": suggestion["region_id"],
        "provenance": "human_observed",
    })
    assert evidence.status_code == 201
    assert evidence.json()["provenance"] == "human_observed"
    duplicate_evidence = client.post(f"/api/cases/{case_id}/evidence", json={
        "requirement_id": requirement_id, "document_id": document_id, "page_number": 1,
        "claim_type": "qualification", "claim_text": "Award: Diploma in Energy Systems", "region_id": suggestion["region_id"], "provenance": "human_observed"
    })
    assert duplicate_evidence.status_code == 409
    reviewed = client.patch(f"/api/evidence/{evidence.json()['id']}", json={"disposition": "supports", "reviewer_note": "Checked against synthetic source page."})
    assert reviewed.status_code == 200
    assert reviewed.json()["provenance"] == "human_verified"
    reopened = client.patch(f"/api/evidence/{evidence.json()['id']}", json={"disposition": "unreviewed"})
    assert reopened.json()["provenance"] == "human_observed"
    assert reopened.json()["reviewer_note"] == "Checked against synthetic source page."
    reviewed = client.patch(f"/api/evidence/{evidence.json()['id']}", json={"disposition": "supports"})
    assert reviewed.json()["reviewer_note"] == "Checked against synthetic source page."

    revised = client.put(f"/api/requirements/{requirement_id}", json={
        "title": "Certificate and award date", "source_name": "Updated synthetic checklist", "source_checked_at": "2026-10-29", "guidance": "Rechecked in the synthetic test."
    })
    assert revised.status_code == 201
    assert revised.json()["version"] == 2
    revised_again = client.put(f"/api/requirements/{revised.json()['id']}", json={
        "title": "Certificate and award date", "source_name": "Third synthetic checklist", "source_checked_at": "2026-10-30", "guidance": "Rechecked for chain test."
    })
    assert revised_again.status_code == 201
    assert revised_again.json()["version"] == 3
    history = client.get(f"/api/requirements/{revised.json()['id']}/history")
    assert history.status_code == 200
    assert [version["version"] for version in history.json()] == [1, 2, 3]
    current = client.get(f"/api/cases/{case_id}").json()
    assert current["requirements"][0]["version"] == 3
    assert current["evidence"][0]["requirement_version"] == 1
    assert next(item for item in client.get("/api/cases").json() if item["id"] == case_id)["requirement_count"] == 1

    packet = client.get(f"/api/cases/{case_id}/packet.md")
    assert packet.status_code == 200
    assert "Award: Diploma in Energy Systems" in packet.text
    assert "Page | Provenance" in packet.text
    assert "v1 · Certificate and award date" in packet.text
    assert "does not verify authenticity" in packet.text


def test_duplicate_upload_is_rejected_and_case_delete_removes_file(client, tmp_path):
    case_id = client.post("/api/cases", json={"title": "Deletion test"}).json()["case"]["id"]
    pdf = pdf_bytes("Synthetic record\nAward: Example certificate")
    first = client.post(f"/api/cases/{case_id}/documents", files={"file": ("one.pdf", pdf, "application/pdf")})
    assert first.status_code == 202
    wait_job(client, first.json()["job_id"])
    duplicate = client.post(f"/api/cases/{case_id}/documents", files={"file": ("copy.pdf", pdf, "application/pdf")})
    assert duplicate.status_code == 409
    detail = client.get(f"/api/cases/{case_id}").json()
    assert len(detail["documents"]) == 1
    stored = list((tmp_path / "runtime" / "uploads").iterdir())
    assert len(stored) == 1
    deleted = client.delete(f"/api/cases/{case_id}")
    assert deleted.status_code == 204
    assert not list((tmp_path / "runtime" / "uploads").iterdir())


def test_evidence_quote_must_be_on_selected_page(client):
    case_id = client.post("/api/cases", json={"title": "Citation test"}).json()["case"]["id"]
    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("record.pdf", pdf_bytes("Name: Fictional Person"), "application/pdf")})
    wait_job(client, upload.json()["job_id"])
    response = client.post(f"/api/cases/{case_id}/evidence", json={
        "document_id": upload.json()["document_id"], "page_number": 1, "claim_text": "A qualification was recognized", "provenance": "human_observed"
    })
    assert response.status_code == 422


def test_requirement_source_url_rejects_invalid_hosts_credentials_and_malformed_ipv6(client):
    case_id = client.post("/api/cases", json={"title": "Source URL validation"}).json()["case"]["id"]
    for source_url in ("https:///missing-host", "https://reviewer:secret@example.org/checklist", "http://[::1", "https://example.org:99999", "https://example.org\\path"):
        response = client.post(f"/api/cases/{case_id}/requirements", json={"title": "Synthetic requirement", "source_url": source_url})
        assert response.status_code == 422


def test_synthetic_demo_is_marked_and_discrepancy_is_only_a_prompt(client):
    response = client.post("/api/demo")
    assert response.status_code == 201
    case_id = response.json()["case"]["id"]
    details = client.get(f"/api/cases/{case_id}").json()
    assert all("Synthetic" in d["original_name"] or d["original_name"].startswith("synthetic-") for d in details["documents"])
    checks = client.get(f"/api/cases/{case_id}/checks").json()
    assert "not establish" in checks["notice"]
    assert any(item["field"] == "institution" for item in checks["potential_discrepancies"])
    first_page = client.get(f"/api/cases/{case_id}/evidence?offset=0&limit=2").json()
    cursor = first_page["next_cursor"]
    next_page = client.get(f"/api/cases/{case_id}/evidence", params={"limit": 2, "before_created_at": cursor["created_at"], "before_id": cursor["id"]}).json()
    assert first_page["total"] == 3 and len(first_page["items"]) == 2
    assert next_page["total"] == 3 and len(next_page["items"]) == 1
    assert client.get(f"/api/cases/{case_id}/evidence?before_id=only-one-half").status_code == 422


def test_cross_document_scan_discloses_when_page_budget_is_reached(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_DISCREPANCY_SCAN_PAGES", 1)
    case_id = client.post("/api/demo").json()["case"]["id"]
    result = client.get(f"/api/cases/{case_id}/checks").json()
    assert result["pages_scanned"] == 1
    assert result["partial_scan"] is True
    assert "later pages were not checked" in result["notice"]


def test_bad_file_signature_and_security_headers(client):
    case_id = client.post("/api/cases", json={"title": "Input test"}).json()["case"]["id"]
    response = client.post(f"/api/cases/{case_id}/documents", files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")})
    assert response.status_code == 415
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    cross_origin = client.post("/api/cases", headers={"Origin": "https://example.invalid"}, json={"title": "Must be blocked"})
    assert cross_origin.status_code == 403


def test_whitespace_table_candidates_are_marked_as_heuristic():
    from skillproof.processing import _layout_tables

    tables = _layout_tables("Year     Course             Result\n2019     Electrical safety  Pass\n2020     Energy systems     Pass", 3)
    assert len(tables) == 1
    assert tables[0]["method"] == "whitespace-layout heuristic"
    assert tables[0]["review_required"] is True


def test_pdf_layout_region_hints_have_per_page_memory_bounds():
    from skillproof.processing import _region_visitor

    regions = []
    visit = _region_visitor(regions, 1)
    for _ in range(1000):
        visit("X" * 3000, None, [0, 0, 0, 0, 1, 1], None, 10)
    assert len(regions) <= 200
    assert sum(len(region["text"]) for region in regions) <= 20_000


def test_multi_batch_pdf_processing_persists_late_pages(client):
    case_id = client.post("/api/cases", json={"title": "Multi-page synthetic case"}).json()["case"]["id"]
    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("large-synthetic.pdf", pdf_bytes("Award: Diploma in Energy Systems", page_count=63), "application/pdf")})
    assert upload.status_code == 202
    result = wait_job(client, upload.json()["job_id"])
    assert result["state"] == "complete"
    document = client.get(f"/api/cases/{case_id}").json()["documents"][0]
    assert document["page_count"] == 63
    last_page = client.get(f"/api/documents/{document['id']}/pages/63")
    assert last_page.status_code == 200
    assert last_page.json()["page_number"] == 63


def test_partial_extraction_reports_actual_page_progress(client, monkeypatch):
    monkeypatch.setattr(processing, "MAX_EXTRACTED_CHARS", 5)
    case_id = client.post("/api/cases", json={"title": "Budget boundary"}).json()["case"]["id"]
    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("budget.pdf", pdf_bytes("A long first page that exhausts the tiny budget", page_count=63), "application/pdf")})
    result = wait_job(client, upload.json()["job_id"])
    assert result["state"] == "complete"
    assert result["progress_current"] == 1
    assert result["progress_total"] == 63
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["documents"][0]["status"] == "partial"


def test_first_prototype_database_gets_requirement_history_columns(tmp_path, monkeypatch):
    data = tmp_path / "legacy-runtime"
    data.mkdir()
    database = data / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE requirements (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, guidance TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '', source_checked_at TEXT NOT NULL DEFAULT '',
            required INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", data / "uploads")
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    db.initialize()
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requirements)")}
    assert {"version", "chain_id", "supersedes_id", "is_current"}.issubset(columns)


def test_queue_capacity_is_checked_atomically_before_accepting_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WORKERS", 1)
    case_id = client.post("/api/cases", json={"title": "Queue boundary"}).json()["case"]["id"]
    with db.connection() as conn:
        for _ in range(8):
            document_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
            conn.execute("INSERT INTO documents(id,case_id,original_name,storage_name,media_type,size_bytes,sha256,status,uploaded_at) VALUES(?,?,?,'',?,0,'','queued',?)", (document_id, case_id, "queued synthetic.pdf", "application/pdf", processing.now_iso()))
            conn.execute("INSERT INTO jobs(id,document_id,state,created_at,updated_at) VALUES(?,?,'queued',?,?)", (job_id, document_id, processing.now_iso(), processing.now_iso()))
    response = client.post(f"/api/cases/{case_id}/documents", files={"file": ("too-late.pdf", pdf_bytes("synthetic"), "application/pdf")})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "15"
    assert not list((tmp_path / "runtime" / "uploads").iterdir())


def test_upload_stream_limit_rejects_chunked_body_before_form_spooling(monkeypatch):
    from skillproof.main import UploadBodyLimitMiddleware

    monkeypatch.setattr(UploadBodyLimitMiddleware, "multipart_overhead_bytes", 0)
    sent = []
    chunks = iter([{"type": "http.request", "body": b"1234", "more_body": True}])

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = UploadBodyLimitMiddleware(downstream, max_file_bytes=3)
    scope = {"type": "http", "method": "POST", "path": "/api/cases/case-1/documents", "headers": []}
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]["status"] == 413


def test_upload_middleware_caps_parallel_request_bodies():
    from skillproof.main import UploadBodyLimitMiddleware

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        first_messages, second_messages = [], []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def downstream(scope, receive, send):
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def send_first(message):
            first_messages.append(message)

        async def send_second(message):
            second_messages.append(message)

        middleware = UploadBodyLimitMiddleware(downstream, max_file_bytes=10, max_concurrent_uploads=1)
        scope = {"type": "http", "method": "POST", "path": "/api/cases/case-1/documents", "headers": []}
        first = asyncio.create_task(middleware(scope, receive, send_first))
        await entered.wait()
        await middleware(scope, receive, send_second)
        release.set()
        await first
        assert second_messages[0]["status"] == 429
        assert first_messages[0]["status"] == 200

    asyncio.run(scenario())


def test_per_case_document_quota_fails_cleanly(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "MAX_DOCUMENTS_PER_CASE", 1)
    case_id = client.post("/api/cases", json={"title": "Storage quota"}).json()["case"]["id"]
    first = client.post(f"/api/cases/{case_id}/documents", files={"file": ("first.pdf", pdf_bytes("First synthetic record"), "application/pdf")})
    assert first.status_code == 202
    wait_job(client, first.json()["job_id"])
    second = client.post(f"/api/cases/{case_id}/documents", files={"file": ("second.pdf", pdf_bytes("Second, different record"), "application/pdf")})
    assert second.status_code == 409
    files = list((tmp_path / "runtime" / "uploads").iterdir())
    assert len(files) == 1


def test_legacy_requirement_revisions_receive_one_current_chain(tmp_path, monkeypatch):
    data = tmp_path / "revision-runtime"
    data.mkdir()
    database = data / "revisions.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE requirements (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, title TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1, supersedes_id TEXT NOT NULL DEFAULT '',
            is_current INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
        conn.executemany("INSERT INTO requirements(id,case_id,title,version,supersedes_id,is_current,created_at) VALUES(?,?,?,?,?,?,?)", [
            ("req-v1", "case-1", "Requirement v1", 1, "", 1, "2026-01-01"),
            ("req-v2", "case-1", "Requirement v2", 2, "req-v1", 1, "2026-01-02"),
            ("req-other", "case-1", "Other requirement", 1, "", 1, "2026-01-03"),
        ])
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", data / "uploads")
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    db.initialize()
    with sqlite3.connect(database) as conn:
        current = conn.execute("SELECT chain_id,count(*),min(id) FROM requirements WHERE is_current=1 GROUP BY chain_id ORDER BY chain_id").fetchall()
    assert current == [("req-other", 1, "req-other"), ("req-v1", 1, "req-v2")]
