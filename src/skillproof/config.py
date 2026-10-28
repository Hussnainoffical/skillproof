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
OCR_ENABLED = os.environ.get("SKILLPROOF_OCR", "0").lower() in {"1", "true", "yes"}
OCR_LANGUAGES = os.environ.get("SKILLPROOF_OCR_LANGS", "eng")
RETENTION_DAYS = int(os.environ.get("SKILLPROOF_RETENTION_DAYS", 30))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
