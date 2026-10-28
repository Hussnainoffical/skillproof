"""SQLite persistence. Local prototype only; production topology is documented separately."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import DB_PATH, ensure_data_dirs


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    occupation TEXT NOT NULL DEFAULT '',
    jurisdiction TEXT NOT NULL DEFAULT 'Germany',
    source_country TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','review','ready','archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    code TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    guidance TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_checked_at TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    supersedes_id TEXT NOT NULL DEFAULT '',
    is_current INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    storage_name TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','ready','partial','needs_ocr','failed')),
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0,
    extracted_chars INTEGER NOT NULL DEFAULT 0,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    regions_json TEXT NOT NULL DEFAULT '[]',
    tables_json TEXT NOT NULL DEFAULT '[]',
    ocr_used INTEGER NOT NULL DEFAULT 0,
    UNIQUE(document_id, page_number)
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    requirement_id TEXT REFERENCES requirements(id) ON DELETE SET NULL,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    region_id TEXT NOT NULL DEFAULT '',
    claim_type TEXT NOT NULL DEFAULT 'supporting_evidence',
    claim_text TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK(provenance IN ('model_suggestion','human_observed','human_verified')),
    confidence REAL,
    reviewer_note TEXT NOT NULL DEFAULT '',
    disposition TEXT NOT NULL DEFAULT 'unreviewed' CHECK(disposition IN ('unreviewed','supports','conflicts','needs_expert','not_relevant')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK(state IN ('queued','running','complete','failed')),
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    actor TEXT NOT NULL DEFAULT 'local-user',
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requirements_case ON requirements(case_id);
CREATE INDEX IF NOT EXISTS idx_documents_case ON documents(case_id);
CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id, requirement_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id, created_at);
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    ensure_data_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    ensure_data_dirs()
    with connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # Additive migration for local databases created by the first prototype build.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(requirements)")}
        for name, definition in (
            ("version", "INTEGER NOT NULL DEFAULT 1"),
            ("supersedes_id", "TEXT NOT NULL DEFAULT ''"),
            ("is_current", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE requirements ADD COLUMN {name} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requirements_current ON requirements(case_id,is_current)")


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
