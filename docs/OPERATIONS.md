# Local operations

## Environment settings

| Variable | Default | Purpose |
|---|---:|---|
| `SKILLPROOF_DATA_DIR` | `data/runtime` | Database and uploaded files directory |
| `SKILLPROOF_MAX_UPLOAD_BYTES` | 209715200 | Maximum file size |
| `SKILLPROOF_MAX_PAGES` | 10000 | Maximum PDF pages |
| `SKILLPROOF_MAX_EXTRACTED_CHARS` | 100000000 | Per-file text budget |
| `SKILLPROOF_MAX_PAGE_CHARS` | 100000 | Text retained per page |
| `SKILLPROOF_MAX_IMAGE_PIXELS` | 60000000 | Image raster safety limit |
| `SKILLPROOF_WORKERS` | 2 | Concurrent local parser jobs |
| `SKILLPROOF_MAX_CONCURRENT_UPLOAD_REQUESTS` | 4 | Concurrent request bodies accepted for file upload (capped at 16) |
| `SKILLPROOF_MAX_DOCUMENTS_PER_CASE` | 100 | Maximum documents in one case |
| `SKILLPROOF_MAX_CASE_STORAGE_BYTES` | 2147483648 | Maximum uploaded file bytes in one case |
| `SKILLPROOF_MAX_TOTAL_STORAGE_BYTES` | 10737418240 | Maximum uploaded file bytes in the local workspace |
| `SKILLPROOF_MAX_DISCREPANCY_SCAN_PAGES` | 10000 | Maximum pages scanned for cross-document text prompts per case |
| `SKILLPROOF_MAX_EVIDENCE_PER_CASE` | 100000 | Maximum source-linked evidence records in one case |
| `SKILLPROOF_MAX_REQUIREMENTS_PER_CASE` | 500 | Maximum current requirement lineages in one case |
| `SKILLPROOF_OCR_TIMEOUT_SECONDS` | 60 | Maximum time for one Tesseract page call |
| `SKILLPROOF_OCR` | `0` | Enable local OCR when set to `1` |
| `SKILLPROOF_OCR_LANGS` | `eng` | Installed Tesseract language codes, e.g. `deu+eng` |
| `SKILLPROOF_OLLAMA_URL` | `http://127.0.0.1:11434` | Loopback Ollama service URL; remote endpoints are rejected |
| `SKILLPROOF_OLLAMA_MODEL` | unset | Exact local Ollama model name; unset disables AI |
| `SKILLPROOF_OLLAMA_TIMEOUT_SECONDS` | `120` | Maximum model response wait |
| `SKILLPROOF_AI_MAX_CONCURRENT_REQUESTS` | `2` | Maximum concurrent local AI analyses (capped at 4) |

To enable the optional analyst, install Ollama, pull a model that fits device resources (e.g. `ollama pull qwen3:8b`), then set `SKILLPROOF_OLLAMA_MODEL` to the installed model name and restart. `/api/ai/status` reports availability. Retrieval uses up to eight case-scoped pages (up to 6,000 characters each), while model calls run through a bounded local semaphore. Citation checks confirm the returned quote occurs on the referenced retrieved page; they do not guarantee interpretation accuracy. No cloud model or fallback is used. The CPU/GPU model's memory consumption is outside SkillProof's queue bound.

Keep the app bound to `127.0.0.1`. Do not use `--host 0.0.0.0` for real case data.

The accepted-job ceiling is `max(8, 4 × SKILLPROOF_WORKERS)` across the local SQLite database. Uploads receive HTTP 429 with `Retry-After` when that ceiling or the concurrent upload-request limit is reached. Concurrent admission checks serialize at the database. Request bodies are capped at the file-size limit plus 128 KiB for multipart framing, including clients that omit `Content-Length`. Case detail returns the newest 50 evidence items by default; fetch later items from the paginated endpoint using its stable `(created_at, id)` cursor so new evidence does not shift later pages. Duplicate source excerpts for the same requirement and region are rejected. Cross-document checks stream at most `SKILLPROOF_MAX_DISCREPANCY_SCAN_PAGES` rows and disclose when the result is partial. Storage quotas count uploaded bytes recorded in the database; monitor actual disk usage separately for SQLite indexes, WAL files, temporary multipart spooling, and backups.

## Backup and deletion

Stop the app before copying `data/runtime/` so the SQLite database and WAL state stay consistent. Protect backups with the same access controls as originals. Deleting a case or document in the UI removes local files and related database records. Verify backup retention separately; application deletion cannot erase copies you made elsewhere.

## Job states

`queued → running → complete` or `failed`. A document may be `partial` if text/page limits truncate extraction, or `needs_ocr` if the source has no extractable text. A job can complete successfully while its document needs OCR; job completion means the attempt ended, not that the extracted text is complete or accurate. The UI exposes page count and processing errors. Restarting the app requeues unfinished jobs. Failed files remain until a reviewer deletes or replaces them.

## Troubleshooting

- **Image has no text:** install Tesseract and `pip install -e ".[ocr]"`, set `SKILLPROOF_OCR=1`, then restart.
- **Password-protected PDF:** export an unlocked version only if authorized.
- **Partial extraction:** inspect the original page; check page/text limits and parser notices.
- **Source viewer blank:** use the page text as a locator and open/download the original in a PDF viewer. The source file remains available via the local API.
- **Queue full:** wait for current jobs to complete or reduce file size; the local API rejects excess work rather than accepting an unbounded queue.

Never copy raw applicant documents into logs, screenshots, issue trackers, or public repositories.
