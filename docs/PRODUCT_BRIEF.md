# SkillProof product brief

## Problem hypothesis

Recognition advisers and international hiring teams may spend time assembling applicant-provided documents, locating evidence for each case-specific requirement, and resolving inconsistencies across documents. The pain is plausible and supported by official application volume and a small European Commission SME survey, but market demand and willingness to pay are not yet validated. Existing government portals, free counselling, country-information resources, and commercial platforms already solve adjacent tasks.

## Initial user and job

**Primary discovery user:** recognition adviser or international hiring operations specialist who prepares a case for review. The person and competent authority retain all consequential decisions.

**Job:** “Given an applicant-consented set of qualification documents and a current, case-specific official checklist, help me locate and review evidence, see unresolved differences, and prepare a source-linked packet without losing the original page context.”

## Product hypothesis

The possible wedge is a versioned, case-scoped evidence graph linking:

- requirement → authoritative source and checked date;
- evidence excerpt → file, page, and optional layout region;
- source provenance → model suggestion, human observation, or human verification;
- review disposition → supports, conflicts, needs expert, or not relevant;
- unresolved prompt → exact pages that a reviewer must inspect.

The combination is a **hypothesis**, not a novelty claim. Do not build full scale until buyers demonstrate a repeated unmet workflow.

## MVP boundary

Included: local case records, manually curated requirements and source dates, PDF/image upload, PDF text/approximate layout locators/heuristic table candidates, optional local OCR, page inspection, exact-quote evidence capture, deterministic label-keyed discrepancy prompts, human review notes, audit events, Markdown packet export, deletion, and a synthetic walkthrough.

Excluded: official credential validation, equivalence decisions, immigration advice, candidate scoring/ranking/selection, fraud labels, job recommendations, form submission, third-party LLM APIs, cloud collaboration, and automatic claims that requirements are complete.

## Success criteria for a customer pilot

Only define targets with an adviser after seeing the current process. Measure the baseline and prototype side by side. Candidate metrics: minutes per packet, required-item recall, false missing-item rate, exact source-page/region correctness, extraction field precision/recall by language and document type, table cell fidelity, OCR correction time, false discrepancy rate, reviewer override rate, and deletion success.

## Discovery gate

Interview 5–8 advisers/operations staff and 5 applicants who recently managed a recognition case. Continue beyond this prototype only if three independent organizations describe recurring manual evidence review not already solved by their current tools and at least one agrees to a permissioned/synthetic pilot with a named budget owner. Stop or pivot if existing services already meet the need, no buyer owns the problem, or reviewers need the product to make adverse decisions.
