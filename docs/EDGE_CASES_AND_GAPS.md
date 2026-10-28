# Edge cases, current behavior, and production gaps

This is a risk-based checklist for the SkillProof local prototype. It records tested behavior separately from protections that still need implementation. Passing synthetic tests does not establish security against hostile files, extraction accuracy, legal compliance, or production capacity.

## Covered by code and tests

| Failure or edge case | Current behavior | Evidence |
|---|---|---|
| Empty, mismatched, or unsupported upload signature | Reject before storing the file | Synthetic API test |
| Upload exceeds byte cap, including chunked body without `Content-Length` | Reject at the ASGI boundary before multipart spooling; chunk streaming enforces the same cap | Synthetic middleware test |
| Too many simultaneous upload request bodies | Reject excess request bodies with 429 and `Retry-After` before parsing/spooling | Parallel ASGI middleware test |
| Too many active parsing jobs or concurrent admissions | Serialize capacity check and insert under a SQLite write lock; return 429 and `Retry-After` | Saturated queue test |
| Case or workspace reaches its configured storage quota | Reject upload and remove the uncommitted stored file | Per-case quota test; workspace quota path not yet directly tested |
| Same file uploaded twice in one case | Compare SHA-256 and reject the duplicate | Duplicate upload test |
| Storage write or database insert raises during upload | Remove the partial/orphan file before propagating the error | Upload cleanup path; needs disk-failure integration test |
| Worker pool is shutting down at submit time | Preserve the uploaded file and mark its document/job failed for visible recovery | Explicit queue failure branch; not yet forced in a test |
| App restarts while a job is queued/running | Requeue unfinished database jobs during startup | Startup recovery path; crash/restart integration test remains open |
| Parser stops on the per-file text budget before a 50-page batch | Flush saved pages and report actual completed page count versus total source pages | Partial extraction regression test |
| PDF has too many pages, no text, or password protection | Bound pages; expose needs-OCR or a public parse error without treating absence as fraud | PDF flow tests; malformed/encrypted fixture coverage incomplete |
| PDF has extremely many text fragments on one page | Cap stored layout hints to 200 regions and 20,000 characters per page | Region-bound test |
| Requirement is edited from two simultaneous reviewers | Immediate transaction serializes revisions; chain index permits one current revision; stale edit gets conflict response | Multi-version and migration tests; live concurrent stress test remains open |
| Evidence points to another case, page, or region | Reject cross-case references, unavailable pages, invalid regions, and text not present on the selected page | Evidence API tests |
| Same evidence excerpt is captured repeatedly | Reject exact duplicates for the same case, source page, requirement, and region; retain distinct regions or requirement revisions separately | Duplicate excerpt assertion |
| Reviewer reopens a previously reviewed item | Return current provenance to `human_observed`, preserve the prior note unless edited, and retain prior review actions in audit history | Review-reopen regression assertions |
| Requirement source changes after evidence was captured | Keep evidence tied to the historical requirement revision; show version history | Revision/export regression test |
| Source URL is malformed, missing a host, or contains embedded credentials | Reject it before it is saved or emitted as a clickable link | URL validation test |
| Cross-document fields differ | Show only a source-linked review prompt; never classify it as fraud, identity mismatch, or an eligibility result | Synthetic demo test |
| Case contains a large evidence history or new evidence arrives while paging | Return bounded pages, aggregate requirement/review counts, and use stable keyset cursors so inserts do not shift later pages | Evidence cursor pagination assertions |
| Cross-document scan would traverse too many pages | Stream rows and cap at the configured page budget; explicitly label incomplete results | Partial-scan disclosure test |
| User deletes a case or document | Delete associated database rows and local file; separately copied backups remain outside app control | Deletion test and operations note |

## Known gaps before any real-data pilot

| Risk | Why it matters | Required next work |
|---|---|---|
| Untrusted PDF parser runs in a worker thread in the app process | A crafted file could consume CPU/memory or exploit parser code; a thread timeout cannot safely terminate it | Move parsing into a restricted process/container with no network, OS CPU/memory/file limits, hard wall-clock timeout, and kill/retry tests |
| No authentication, multi-user identity, or tenant isolation | Loopback binding limits network exposure but does not protect data from another local account, browser extension, or compromised workstation | Define trust model; add authentication, authorization, tenant scoping, CSRF defense, and isolation tests before network deployment |
| Files and SQLite database are not encrypted by the application | Device compromise or copied backups can expose personal documents | Set encryption-at-rest and key management requirements; test encrypted backups and restore procedures |
| No automatic retention/deletion policy | Documents can remain indefinitely unless a reviewer deletes them | Agree a lawful retention schedule per pilot; implement verified purge and backup expiry only after policy approval |
| TIFF and other image support is not comprehensively validated | Some browsers do not render TIFF; multi-frame TIFF may be shown or indexed incompletely | Validate image decoding, frame counts, decompression-bomb behavior, orientation, color profiles, and page-by-page source display |
| OCR has no quality guarantee | Language, scan quality, rotation, handwriting, stamps, tables, and mixed scripts can produce omissions or substitutions | Build a consented, diverse, labeled evaluation corpus; measure per-field recall/precision and quote fidelity by language and scan condition |
| Table extraction is only whitespace heuristics for digital text | Merged cells, multi-column pages, scans, and visually aligned tables can be misread | Add layout-aware evaluation and a source-linked human correction workflow; keep uncertainty visible |
| Job recovery has no lease/heartbeat/watchdog | A live process can leave a hung job in `running` until restart; multiple app processes are unsupported | Add leases, heartbeat, retry counts, dead-letter state, cancellation, and recovery tests before multi-process use |
| SQLite, local disk, and one worker pool are single-node | No demonstrated million-user capacity, cross-host fairness, high availability, or safe horizontal scaling | Define workload/SLOs, then load test a production-like queue, database, object storage, and worker topology; measure p50/p95/p99 and recovery |
| No malware scanning, document authenticity verification, or authority integration | A supported file can still be malicious, altered, or unrelated to the case | Sandbox and scan files; preserve a human verification process and never infer authenticity from extraction |
| Storage quotas track database file sizes, not actual filesystem use | SQLite/WAL, temporary multipart spooling, backups, and other files consume additional disk | Add filesystem reserve checks and operational low-disk alerting before real-data use |
| Source checklist freshness is manual | Official requirements change and differ by route and region | Pilot one named route with a qualified adviser; define source ownership, review cadence, and stale-source alerts |
| Packet output has no signing or tamper-evident seal | A Markdown export can be modified after export | If downstream reliance requires it, define signed export, digest, key rotation, and verification before building it |
| No adversarial test corpus or external penetration test | Unit tests cover known paths but not the full attack surface | Add fuzz/property tests, dependency scanning, parser corpus, abuse tests, backup/restore, and independent security review |

## Exit gates

Do not use real applicant data or advertise production readiness until the project has: (1) a reviewed privacy/legal basis and retention policy, (2) an isolated parser with enforceable resource/time limits, (3) authentication and access controls appropriate to the deployment, (4) an evaluated multilingual corpus with documented error rates, (5) a tested backup/deletion path, (6) a representative load and recovery report, and (7) a qualified human owner for every case decision. The current prototype does not pass these gates.
