# Security and privacy boundaries

## Current safeguards

- Binds to `127.0.0.1` by default; no network service or external model call.
- Upload file signature and extension checks; per-file byte limit; UUID-only storage path; SHA-256 integrity/deduplication; PDF page and text budgets.
- No original contents are written to application logs. Source text is rendered as escaped text in the browser. Source URLs are recorded, not fetched by the server.
- Loopback host and same-origin checks block normal cross-origin browser state-changing requests in local mode. This is not a substitute for authentication or a security review.
- Same-origin UI with restrictive security headers. Delete operations remove the selected case/document records, page text, evidence, and uploaded source files.
- Optional OCR remains local and disabled by default.

## Important gaps

- There is no authentication, authorization, tenant isolation, encryption at rest, key management, antivirus scanning, or hardened parser sandbox. Anyone who can use this local app can access the local cases.
- SQLite and uploaded files are plaintext. Rely on full-disk encryption, OS account security, and carefully controlled backups; do not treat this as GDPR-compliant deployment.
- PDF parsers process attacker-controlled files. Keep dependencies updated and use an isolated, resource-limited worker before accepting files from untrusted users.
- No automatic retention purge exists. Delete cases/documents when no longer needed and ensure copies in backups are handled separately.
- The source checklist can be stale or incorrectly entered. The app requires the reviewer to record the authority and last-checked date but cannot guarantee correctness.
- Employment-related use can trigger EU AI Act high-risk obligations depending on intended purpose. Human oversight alone does not settle classification. Obtain qualified legal and data-protection review before any employer pilot or real applicant processing.

## Data handling guidance

Use synthetic or explicitly permitted/redacted material during development. Collect only the documents needed for a named case, record the applicable lawful basis and consent/authorization outside this tool, restrict access to the workstation, define deletion dates, and never add customer documents or secrets to source control. The tool does not establish a lawful basis or provide legal advice.
