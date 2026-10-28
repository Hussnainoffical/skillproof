# SkillProof

SkillProof is a local-first workspace for preparing international qualification documents for **human review**. It ties extracted text, tables, and reviewer excerpts back to an original file and page, records the source/version for each case requirement, and exports a review packet.

It does **not** authenticate documents, decide qualification equivalence or immigration eligibility, rank or reject people, recommend hiring decisions, or submit applications. OCR and discrepancy prompts are fallible review aids. A missing excerpt is not a fraud finding.

## Run locally

Requires Python 3.11 or newer.

```powershell
cd Project5_SkillProof
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
skillproof
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). The app binds to loopback by default. Do not expose it on a network or reverse proxy without implementing authentication, tenant isolation, encryption, and a security review.

To run without installing the console entry point:

```powershell
python -m pip install -e .
uvicorn skillproof.main:app --app-dir src --host 127.0.0.1 --port 8787
```

The API reference is at `/api/docs`. Runtime documents and the SQLite database live in `data/runtime/` by default and are git-ignored. Back up or delete that folder deliberately. The app does not upload files to a model provider or analytics service.

## First-time demo

Select **Explore with synthetic data** to create a fictional case with made-up documents and one intentionally different institution label. No real person or credential is represented. Use this to inspect page linking, human dispositions, and the packet export before uploading anything.

## Workflow

1. Create a case scoped to one occupation, route, and jurisdiction.
2. Add the requirements from the responsible authority's current information; record its URL and the date you checked it. No official checklist is bundled because requirements depend on the case and can change.
3. Upload a consented PDF or image. The local worker extracts page text, approximate layout-region locators, and heuristic digital-table candidates. Processing runs asynchronously and is bounded by configured size/page/text limits.
4. Inspect the original page. Capture an exact excerpt and attach it to a requirement. Keyword suggestions and cross-document text differences are prompts, not verdicts.
5. Record a human disposition (supports, conflicts, needs expert, not relevant) with an optional note.
6. Export a Markdown packet that preserves source links, excerpts, page numbers, and reviewer decisions.

## OCR and scanned documents

Text extraction and whitespace-based table candidates are on by default for PDFs. Image OCR is off by default. To enable OCR, install Tesseract and the needed language packs on the machine, install the optional Python package, then set `SKILLPROOF_OCR=1` before starting. Set `SKILLPROOF_OCR_LANGS` to installed codes such as `deu+eng` for German and English:

```powershell
python -m pip install -e ".[ocr]"
$env:SKILLPROOF_OCR="1"
$env:SKILLPROOF_OCR_LANGS="deu+eng"
skillproof
```

The PDF renderer uses OCR only for pages with little extractable text. Raster output is processed one page at a time and never sent to an external service. OCR language defaults depend on the local Tesseract installation. Tables on scanned pages may not retain row/column structure. Inspect the original image.

## Limits and safe defaults

- Single-user local prototype; no sign-in, team sharing, network service, or tenant boundary.
- Default maximum upload size: 200 MiB; maximum PDF length: 10,000 pages; extracted text budget: 100 million characters per file; each stored page is capped at 100,000 characters. Configure using `SKILLPROOF_MAX_UPLOAD_BYTES`, `SKILLPROOF_MAX_PAGES`, `SKILLPROOF_MAX_EXTRACTED_CHARS`, and `SKILLPROOF_MAX_PAGE_CHARS`.
- Two local processing workers by default (`SKILLPROOF_WORKERS`). These limits prevent unbounded work; they do not demonstrate capacity for 1,000,000 concurrent users.
- SQLite is not encrypted by the app. Use device encryption and access controls; do not use real applicant documents until data protection, retention, access, and legal review are complete.
- Delete a case to remove its records and uploaded files. Deleting a document removes its extracted pages and linked evidence.
- Data stays in the project-local runtime directory unless you choose another local path via `SKILLPROOF_DATA_DIR`.

## Development and verification

```powershell
python -m pip install -e ".[dev]"
pytest
```

The synthetic test suite covers case setup, PDF ingestion, page citations, evidence provenance, human dispositions, duplicate detection, export, and deletion. See [evaluation plan](docs/EVALUATION_PLAN.md) for quality measures beyond software tests.

## Project notes

- [Product brief](docs/PRODUCT_BRIEF.md)
- [Architecture and scale path](docs/ARCHITECTURE.md)
- [Privacy and threat boundaries](docs/SECURITY_PRIVACY.md)
- [Operations](docs/OPERATIONS.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Customer discovery guide](docs/CUSTOMER_DISCOVERY_GUIDE.md)
- [Build journal](docs/BUILD_JOURNAL.md)
- [Market evidence and competitor boundary](docs/MARKET_EVIDENCE.md)

## Research provenance

The product hypothesis draws on a 50-paper second arXiv cohort curated in the shared research workspace. This repository maps the relevant papers in [research-to-design traceability](docs/RESEARCH_TRACEABILITY.md); those papers are research leads, not proof of production performance, and peer-review status was not independently verified. Check venues, licenses, datasets, and reported results before reuse. [Market evidence](docs/MARKET_EVIDENCE.md) records existing official/free services and commercial competitors. SkillProof is not claimed to be first or market validated.
