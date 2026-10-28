# Evaluation plan

## What software checks can show

The automated tests use synthetic data to check API behavior, evidence/page references, duplicate detection, lifecycle/deletion, and packet output. Passing them does not establish OCR accuracy, requirement recall, fairness, legal compliance, customer demand, or production readiness.

## Human-labeled evaluation corpus

Before any real pilot, assemble a permissioned or synthetic corpus reviewed by a qualified adviser. Stratify by language/script, document type (certificate, transcript, translation, work record), scan quality, handwriting, layout, and table density. Keep gold labels separate from the product database and restrict access.

## Metrics

- Field extraction precision, recall, and exact-match accuracy, separately by field and language.
- Requirement-to-evidence recall and false-missing rate; include the cases where evidence is present in a table, alternate page, or translation.
- Source page and region link correctness; evidence quote exactness.
- Table row/cell fidelity and OCR character error rate, measured against human transcription.
- Potential discrepancy precision, false alert rate, and missed conflicts. The current label heuristic should be considered a baseline only.
- Human correction rate, review minutes, abstention/unknown rate, and reviewer agreement.
- Deletion verification, unauthorized access checks, audit completeness, latency and memory on the largest approved file.

## Release gates

1. No demo claims or generated packet may imply official recognition, authenticity verification, or candidate suitability.
2. Every output excerpt must resolve to its source file and page; test wrong, missing, deleted, and partial source states.
3. Calibrate any threshold on a held-out set and report slices, not one aggregate score.
4. A qualified human reviewer must confirm the checklist and all dispositions.
5. A legal/privacy review and approved lawful data workflow are mandatory before real applicant documents or employer selection workflows.
6. Establish buyer-specific time-saving and quality targets against a manual baseline before calling the product effective.

## Known untested cases

Handwriting, low-quality scans, right-to-left layouts, multilingual pages, stamps/seals, forged/altered documents, large complex tables, 10,000-page performance, worker restart at arbitrary points, concurrent multi-user access, and tenant isolation are not validated by this prototype's test suite.
