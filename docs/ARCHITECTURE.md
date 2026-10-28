# SkillProof architecture

## Current vertical slice

```text
Browser (same-origin, loopback)
  ├─ Case/checklist/review UI ── FastAPI JSON API
  ├─ Source PDF/image viewer ─── local upload endpoint
  └─ Markdown packet export ─── deterministic renderer
                                  │
                          SQLite (WAL, foreign keys)
                     cases / requirements / documents
                     page text / regions / tables / evidence
                     jobs / audit events
                                  │
                     bounded local worker pool
                     pypdf extraction + optional local OCR
```

The application writes only under its configured project-local data directory. Documents use UUID storage names and retain a sanitized display filename. Uploads are type/signature checked, size limited, hashed, and duplicate checked within the case. An ASGI request-body guard rejects oversized multipart bodies before framework disk spooling; the endpoint then streams the file in bounded chunks. Queue admission is serialized with a SQLite write lock so concurrent uploads cannot all pass the same stale queue check. PDF pages are parsed incrementally and committed in batches. Per-page layout hints have explicit count and text limits. The original remains the primary evidence; extracted text does not replace it.

## Evidence graph and provenance

SQLite foreign keys connect a case to versioned requirement records, documents, source pages/layout regions, human-created evidence excerpts, reviewer dispositions, jobs, and audit events. A stable chain key and partial unique index prevent two current revisions from existing in the same checklist lineage; revision writes use an immediate transaction to serialize concurrent edits. Evidence excerpts must match the selected extracted page text. Provenance differentiates system keyword suggestions from human-observed and human-reviewed items. A reviewer disposition does not mean a competent authority has recognized a qualification.

The local deterministic discrepancy check only compares exact, label-keyed fields (for example, `Institution:`) across files. It returns source-linked prompts. It does not infer identity, truth, authenticity, fraud, or equivalence. Unstructured disagreements and unlabeled data can be missed.

## Large-file behavior

The local worker pool bounds concurrent parser jobs. Limits apply to upload bytes, page count, total extracted characters, and page text. Results are persisted incrementally; a worker restart requeues queued/running jobs. This prototype has no distributed queue, per-tenant quota, multi-process job lease, cloud object store, or backpressure across hosts. SQLite is a single-node database and not suitable as the write backend for a very large collaborative deployment.

## Production scale path (not implemented or benchmarked)

Supporting 1,000,000 simultaneous users would require a different deployment and an explicit workload model; it cannot be inferred from this MVP. Before any scale claim:

1. Define active vs registered users, upload rate, pages/file, storage retention, query mix, regions, latency SLO, availability, and abuse limits.
2. Put a zero-trust authenticated API gateway in front of tenant-scoped services; require SSO/OIDC, role/access checks, consent tracking, audit access, and per-tenant quotas.
3. Move originals to encrypted object storage using short-lived signed access, malware scanning, retention lifecycle rules, and tenant-specific key strategy.
4. Use an idempotent durable queue (e.g. Kafka/SQS-class service) and isolated parser workers with CPU, memory, page-time, file, and OCR budgets. Keep parsing in a sandbox without network access.
5. Use PostgreSQL for transactional case/evidence data, partitioned/replicated only after measurements. Add a search index only if retrieval latency or corpus size requires it; preserve canonical evidence IDs and source-page links.
6. Separate extraction, review API, packet generation, and notification capacity. Apply load shedding, retry/backoff, dead-letter handling, per-tenant fairness, and job cancellation.
7. Benchmark a representative multilingual, scanned, table-heavy corpus; inject worker crashes, duplicate uploads, queue floods, storage failures, and tenant isolation checks. Report p50/p95/p99, queue delay, extraction cost, failures, and recovery time.

Those components are a scale design direction, not a claim that one million users are currently supported. A measured capacity number requires production-like load tests and infrastructure.

## Key trade-offs

- Local storage avoids sending personal documents to model APIs but does not encrypt SQLite or protect a compromised workstation.
- `pypdf` extracts digital PDF text and visitor fragments; the stored region geometry is an approximate locator, not a pixel-accurate box. Whitespace-based digital table candidates are heuristic. Scanned tables need visual/manual review.
- OCR is opt-in and requires a local Tesseract binary plus optional Python dependencies; OCR of scanned PDF pages also uses optional PyMuPDF for rendering. OCR quality depends on language packs and scan quality.
- No LLM is required for this MVP. That reduces unsupported generation risk; richer extraction should be introduced only behind provenance, evaluation, and human correction.
