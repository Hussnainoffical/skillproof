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
| `SKILLPROOF_OCR` | `0` | Enable local OCR when set to `1` |
| `SKILLPROOF_OCR_LANGS` | `eng` | Installed Tesseract language codes, e.g. `deu+eng` |

Keep the app bound to `127.0.0.1`. Do not use `--host 0.0.0.0` for real case data.

## Backup and deletion

Stop the app before copying `data/runtime/` so the SQLite database and WAL state stay consistent. Protect backups with the same access controls as originals. Deleting a case or document in the UI removes local files and related database records. Verify backup retention separately; application deletion cannot erase copies you made elsewhere.

## Job states

`queued → running → complete` or `failed`. A parsed PDF may be marked `partial` if limits or table parsing prevent complete extraction. The UI exposes page count and processing errors. Restarting the app requeues unfinished jobs. Failed files remain until a reviewer deletes or replaces them.

## Troubleshooting

- **Image has no text:** install Tesseract and `pip install -e ".[ocr]"`, set `SKILLPROOF_OCR=1`, then restart.
- **Password-protected PDF:** export an unlocked version only if authorized.
- **Partial extraction:** inspect the original page; check page/text limits and parser notices.
- **Source viewer blank:** use the page text as a locator and open/download the original in a PDF viewer. The source file remains available via the local API.
- **Queue full:** wait for current jobs to complete or reduce file size; the local API rejects excess work rather than accepting an unbounded queue.

Never copy raw applicant documents into logs, screenshots, issue trackers, or public repositories.
