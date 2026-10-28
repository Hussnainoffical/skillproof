"""Runtime configuration with conservative local defaults."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]
DATA_DIR = Path(os.environ.get("SKILLPROOF_DATA_DIR", PROJECT_DIR / "data" / "runtime")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "skillproof.sqlite3"
MAX_UPLOAD_BYTES = int(os.environ.get("SKILLPROOF_MAX_UPLOAD_BYTES", 200 * 1024 * 1024))
MAX_PAGES = int(os.environ.get("SKILLPROOF_MAX_PAGES", 10_000))
MAX_EXTRACTED_CHARS = int(os.environ.get("SKILLPROOF_MAX_EXTRACTED_CHARS", 100_000_000))
MAX_PAGE_CHARS = int(os.environ.get("SKILLPROOF_MAX_PAGE_CHARS", 100_000))
MAX_IMAGE_PIXELS = int(os.environ.get("SKILLPROOF_MAX_IMAGE_PIXELS", 60_000_000))
WORKERS = max(1, int(os.environ.get("SKILLPROOF_WORKERS", 2)))
MAX_CONCURRENT_UPLOAD_REQUESTS = max(1, min(16, int(os.environ.get("SKILLPROOF_MAX_CONCURRENT_UPLOAD_REQUESTS", 4))))
MAX_DOCUMENTS_PER_CASE = max(1, int(os.environ.get("SKILLPROOF_MAX_DOCUMENTS_PER_CASE", 100)))
MAX_CASE_STORAGE_BYTES = max(1, int(os.environ.get("SKILLPROOF_MAX_CASE_STORAGE_BYTES", 2 * 1024 * 1024 * 1024)))
MAX_TOTAL_STORAGE_BYTES = max(1, int(os.environ.get("SKILLPROOF_MAX_TOTAL_STORAGE_BYTES", 10 * 1024 * 1024 * 1024)))
MAX_DISCREPANCY_SCAN_PAGES = max(100, int(os.environ.get("SKILLPROOF_MAX_DISCREPANCY_SCAN_PAGES", 10_000)))
MAX_EVIDENCE_PER_CASE = max(100, int(os.environ.get("SKILLPROOF_MAX_EVIDENCE_PER_CASE", 100_000)))
MAX_REQUIREMENTS_PER_CASE = max(1, int(os.environ.get("SKILLPROOF_MAX_REQUIREMENTS_PER_CASE", 500)))
OCR_ENABLED = os.environ.get("SKILLPROOF_OCR", "0").lower() in {"1", "true", "yes"}
OCR_LANGUAGES = os.environ.get("SKILLPROOF_OCR_LANGS", "eng")
OCR_TIMEOUT_SECONDS = max(1, int(os.environ.get("SKILLPROOF_OCR_TIMEOUT_SECONDS", 60)))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
