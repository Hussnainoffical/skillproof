"""Incremental PDF/image parsing with exact page and approximate region provenance."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from .config import MAX_EXTRACTED_CHARS, MAX_IMAGE_PIXELS, MAX_PAGE_CHARS, MAX_PAGES, OCR_ENABLED, OCR_LANGUAGES, OCR_TIMEOUT_SECONDS, UPLOAD_DIR
from .db import connection


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snippets(text: str) -> list[tuple[str, str]]:
    """Return keyword-triggered review prompts, not inferred facts."""
    patterns = {
        "qualification": re.compile(r"\b(degree|diploma|certificate|qualification|award|credential|abschluss|zeugnis|qualifikation)\b", re.I),
        "institution": re.compile(r"\b(university|college|institute|school|institution|universität|hochschule|institut)\b", re.I),
        "date": re.compile(r"\b(19|20)\d{2}\b"),
        "identity_or_name": re.compile(r"\b(name|surname|given name|date of birth|full name|vorname|nachname|geburtsdatum)\b", re.I),
        "translation": re.compile(r"\b(translation|translated|translator|übersetzung|übersetzer)\b", re.I),
    }
    output: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if len(line) < 8:
            continue
        for label, pattern in patterns.items():
            if pattern.search(line):
                item = (label, line[:600])
                if item not in seen:
                    seen.add(item)
                    output.append(item)
                break
    return output[:100]


def _optional_ocr(path: Path, page_index: int | None, media_type: str, existing: str) -> tuple[str, bool]:
    if not OCR_ENABLED or len(existing.strip()) >= 30:
        return existing, False
    try:
        import io
        import pytesseract
        from PIL import Image

        if media_type == "application/pdf" and page_index is not None:
            import fitz  # optional local renderer, installed with the [ocr] extra
            with fitz.open(path) as source:
                page = source.load_page(page_index)
                scale = 1.5
                if math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale) > MAX_IMAGE_PIXELS:
                    return existing, False
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
        else:
            image = Image.open(path)
            if image.width * image.height > MAX_IMAGE_PIXELS:
                return existing, False
        return pytesseract.image_to_string(image, lang=OCR_LANGUAGES, timeout=OCR_TIMEOUT_SECONDS), True
    except Exception:
        return existing, False


def _layout_tables(text: str, page_number: int) -> list[dict]:
    """Detect row-shaped whitespace in digital PDF text; this is only a locator heuristic."""
    rows: list[list[str]] = []
    run: list[list[str]] = []
    tables: list[dict] = []
    for line in text.splitlines() + [""]:
        cells = [part.strip() for part in re.split(r"\t+|\s{2,}", line.strip()) if part.strip()]
        if len(cells) >= 2:
            run.append(cells[:40])
        else:
            if len(run) >= 2:
                rows.append([])
                tables.append({"id": f"p{page_number}-layout-t{len(tables)+1}", "method": "whitespace-layout heuristic", "review_required": True, "rows": run[:200]})
            run = []
    return tables[:50]


def _region_visitor(regions: list[dict], page_number: int):
    retained_chars = 0

    def visit(text, cm, tm, font_dict, font_size):
        nonlocal retained_chars
        if len(regions) >= 200 or retained_chars >= 20_000:
            return
        clean = " ".join(str(text).split())
        if not clean:
            return
        try:
            x, y = float(tm[4]), float(tm[5])
            size = float(font_size or 10)
            # pypdf's text matrix coordinates are a locator approximation in PDF user space,
            # not pixel-exact bounding boxes. The original viewer remains authoritative.
            width = max(size, min(len(clean) * size * 0.5, 2000))
            clean = clean[: min(1000, 20_000 - retained_chars)]
            regions.append({"id": f"p{page_number}-r{len(regions)+1}", "bbox": [round(x, 2), round(y-size, 2), round(x+width, 2), round(y+size*0.2, 2)], "coordinate_space": "pdf_user_space_approximate", "text": clean})
            retained_chars += len(clean)
        except Exception:
            return
    return visit


def _page_record(document_id: str, number: int, text: str, regions: list, tables: list, ocr_used: bool) -> dict:
    return {"id": str(uuid.uuid4()), "document_id": document_id, "page_number": number, "text": text, "regions_json": json.dumps(regions, ensure_ascii=False), "tables_json": json.dumps(tables, ensure_ascii=False), "ocr_used": int(ocr_used)}


def _insert_pages(conn: sqlite3.Connection, batch: list[dict]) -> None:
    conn.executemany("INSERT OR REPLACE INTO pages(id,document_id,page_number,text,regions_json,tables_json,ocr_used) VALUES(:id,:document_id,:page_number,:text,:regions_json,:tables_json,:ocr_used)", batch)


def process_document(document_id: str, job_id: str) -> None:
    """Parse one document incrementally, persisting bounded page batches and job progress."""
    with connection() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not doc:
            return
        path = UPLOAD_DIR / doc["storage_name"]
        conn.execute("UPDATE documents SET status='processing',error_code='',error_message='' WHERE id=?", (document_id,))
        conn.execute("UPDATE jobs SET state='running',updated_at=? WHERE id=?", (now_iso(), job_id))
        conn.execute("DELETE FROM pages WHERE document_id=?", (document_id,))

    batch: list[dict] = []
    page_count = 0
    processed_pages = 0
    extracted_chars = 0
    ocr_count = 0
    partial = False
    try:
        media_type = doc["media_type"]
        if media_type == "application/pdf":
            with path.open("rb") as source:
                reader = PdfReader(source, strict=False)
                if reader.is_encrypted:
                    try:
                        if reader.decrypt("") == 0:
                            raise ValueError("PDF_PASSWORD_PROTECTED")
                    except Exception as exc:
                        if isinstance(exc, ValueError):
                            raise
                        raise ValueError("PDF_PASSWORD_PROTECTED") from exc
                page_count = len(reader.pages)
                if page_count == 0 or page_count > MAX_PAGES:
                    raise ValueError("PDF_PAGE_LIMIT")
                with connection() as conn:
                    conn.execute("UPDATE jobs SET progress_total=?,updated_at=? WHERE id=?", (page_count, now_iso(), job_id))
                for index, page in enumerate(reader.pages, start=1):
                    processed_pages = index
                    regions: list[dict] = []
                    text = page.extract_text(visitor_text=_region_visitor(regions, index)) or ""
                    text, used_ocr = _optional_ocr(path, index - 1, media_type, text)
                    ocr_count += int(used_ocr)
                    if len(text) > MAX_PAGE_CHARS:
                        text = text[:MAX_PAGE_CHARS]
                        partial = True
                    remaining = MAX_EXTRACTED_CHARS - extracted_chars
                    if len(text) > remaining:
                        text = text[:max(remaining, 0)]
                        partial = True
                    extracted_chars += len(text)
                    rows = _layout_tables(text, index)
                    batch.append(_page_record(document_id, index, text, regions[:500], rows, used_ocr))
                    if len(batch) >= 50 or index == page_count:
                        with connection() as conn:
                            _insert_pages(conn, batch)
                            conn.execute("UPDATE jobs SET progress_current=?,updated_at=? WHERE id=?", (index, now_iso(), job_id))
                        batch.clear()
                    if extracted_chars >= MAX_EXTRACTED_CHARS:
                        partial = index < page_count or partial
                        break
                if batch:
                    with connection() as conn:
                        _insert_pages(conn, batch)
                        conn.execute("UPDATE jobs SET progress_current=?,updated_at=? WHERE id=?", (processed_pages, now_iso(), job_id))
                    batch.clear()
        else:
            text, used_ocr = _optional_ocr(path, None, media_type, "")
            page_count, processed_pages, ocr_count = 1, 1, int(used_ocr)
            text_limit = min(MAX_PAGE_CHARS, MAX_EXTRACTED_CHARS)
            extracted_chars = min(len(text), text_limit)
            if len(text) > text_limit:
                text, partial = text[:text_limit], True
            batch.append(_page_record(document_id, 1, text, [], [], used_ocr))
            with connection() as conn:
                _insert_pages(conn, batch)
                conn.execute("UPDATE jobs SET progress_current=1,progress_total=1,updated_at=? WHERE id=?", (now_iso(), job_id))

        state = "partial" if partial else ("needs_ocr" if extracted_chars == 0 else "ready")
        with connection() as conn:
            conn.execute("UPDATE documents SET status=?,page_count=?,extracted_chars=? WHERE id=?", (state, page_count, extracted_chars, document_id))
            conn.execute("UPDATE jobs SET state='complete',progress_current=?,progress_total=?,updated_at=? WHERE id=?", (processed_pages, page_count, now_iso(), job_id))
            conn.execute("INSERT INTO audit_events(id,case_id,action,object_type,object_id,details_json,created_at) SELECT ?,case_id,'document.processed','document',?,json_object('status',?,'page_count',?,'ocr_pages',?),? FROM documents WHERE id=?", (str(uuid.uuid4()), document_id, state, page_count, ocr_count, now_iso(), document_id))
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "DOCUMENT_PARSE_FAILED"
        public = {
            "PDF_PASSWORD_PROTECTED": "This PDF is password protected. Export an unlocked copy if you are authorized to do so.",
            "PDF_PAGE_LIMIT": f"The file is empty or exceeds the configured limit of {MAX_PAGES:,} pages.",
            "OCR_UNAVAILABLE_OR_EMPTY": "No readable text was found. Enable optional OCR or provide a text-based PDF.",
        }.get(code, "The file could not be parsed safely. Try a clean export or a supported image/PDF.")
        with connection() as conn:
            conn.execute("UPDATE documents SET status='failed',error_code=?,error_message=? WHERE id=?", (code, public, document_id))
            conn.execute("UPDATE jobs SET state='failed',error_code=?,updated_at=? WHERE id=?", (code, now_iso(), job_id))


def page_suggestions(text: str) -> list[tuple[str, str]]:
    return _snippets(text)
