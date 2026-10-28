# Build journal

**Build date:** 2026-10-28 · **Project:** SkillProof local review MVP

## Phase 0 — scope and stop conditions

Started from the evidence-backed but unvalidated hypothesis and 50-paper discovery cohort in the shared `Codex/Papers` workspace. This repository includes a compact [market evidence summary](MARKET_EVIDENCE.md) and a [research-to-design traceability table](RESEARCH_TRACEABILITY.md). The existing portfolio already has a PDF evidence assistant, industrial content assurance, agent tool-effect testing, and invoice exception review. SkillProof adds a different case-level qualification evidence workflow. No evidence supports claiming that the market is empty or willingness to pay is proven.

**Boundary:** human review and preparation only. No identity authentication, equivalence/immigration decisions, candidate ranking or rejection, hiring recommendation, or application submission.

## Phase 1 — bounded architecture

Implemented a FastAPI same-origin local app; SQLite records for cases, versioned requirements, documents, page text/regions/tables, evidence provenance, processing jobs, and audit events; UUID file storage; SHA-256; file signature, upload/page/text/pixel limits; and a bounded two-worker parser pool. Runtime files are under this project directory only. The design is explicitly single-user; it does not claim million-user capacity.

## Phase 2 — end-to-end review vertical slice

Implemented case creation/status, manual official-source checklist entries, PDF/image upload, incremental page extraction, optional local OCR, approximate text-region locators, whitespace-based table candidates, page source inspection, suggested excerpt discovery, exact excerpt capture, requirement linking, human dispositions/notes, label-keyed cross-file difference prompts, Markdown packet export, synthetic demo, and deletion.

## Phase 3 — safeguards and verification

Implemented source-page quote validation, visible limitations, HTML escaping, same-origin/local binding, loopback host checks, security headers, no external model or analytics calls, synthetic-only demo data, and human-only disposition controls. The synthetic demo includes a deliberately different institution string; it exercises the cross-document prompt without presenting it as a factual error. Eight automated API tests cover the primary lifecycle, a 63-page multi-batch PDF, legacy database migration, requirement history, and unsafe input boundaries. Verification: `python -m pytest` — 8 passed; Python compile check passed; `node --check` passed; local browser dashboard, demo case, discrepancy prompt, and source-page inspector opened successfully.

## Phase 4 — next increments

Before a real-data pilot: recruit advisers, identify one occupation/state/source-country route, verify source checklists with an authority or qualified adviser, label a diverse evaluation corpus, review privacy/legal classification, add authentication and tenant isolation if collaboration is required, encrypt stored data, sandbox parsing, and benchmark representative large files. Kill or pivot if existing tools already solve the workflow or no buyer commits to a safe pilot.

## Frictions and decisions

- No official requirements are preloaded because they are route-specific and can change. The reviewer records the current source and check date.
- PDF extraction and OCR are not treated as truth; every saved evidence excerpt must match the selected source page text.
- The discrepancy baseline uses explicit labels only and is shown as a review prompt. It cannot establish fraud or identity.
- Large files are bounded, not guaranteed fast. The 10,000-page ceiling is a configurable guardrail, not a benchmark result.
- The market lead is a hypothesis; direct competition and free substitutes remain material risks.
