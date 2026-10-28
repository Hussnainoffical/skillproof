# Research-to-design traceability

The relevant papers are in the second research cohort under `../Papers/Library/reading_pack_round2.md`. They are arXiv records and their peer-review/venue status was not independently verified. The product implementation does not claim their results as its own.

| Research candidate | Design influence in this prototype | What it does not prove |
|---|---|---|
| [DocXEval: explainability evaluation for multimodal document understanding](https://arxiv.org/abs/2610.36929) | Keep field suggestions visibly tied to text region and page; preserve original file access; evaluate source link correctness separately. | That the prototype's approximate PDF text coordinates are faithful explanations or that the cited explanation method is best. |
| [One Fact, Many Places](https://arxiv.org/abs/2610.26401) | Permit multiple excerpts/documents to support one checklist requirement; do not force a single evidence span. | That a page-level extraction finds every valid location in a 10,000-page corpus. |
| [Identify, Locate, Link](https://arxiv.org/abs/2608.20868) | Store optional source-region identifiers alongside document/page excerpts; require a valid page excerpt before evidence is persisted. | Pixel-perfect grounding; the current pypdf region geometry is explicitly approximate PDF user space. |
| [Evaluating cloud and self-hosted OCR for Arabic, English, and French documents](https://arxiv.org/abs/2610.25235) | Keep OCR local and optional; define per-language/script and scan-quality measurements for a future evaluation. | OCR support for every script or production accuracy; no OCR model is bundled by default. |
| [Same Entity, Different Script](https://arxiv.org/abs/2610.31407) | Keep script variants as a reviewer concern; the system never converts a transliteration difference into an identity or fraud verdict. | A solved cross-script identity match. |
| [From Skill Extraction to Multistakeholder Recommendation](https://arxiv.org/abs/2607.15707) | Exclude candidate ranking and hiring recommendations; keep decisions with affected people and qualified reviewers. | That a human-in-the-loop workflow alone removes bias or regulatory duties. |
| [Enhancing Job Matching with ESCO and EQF](https://arxiv.org/abs/2512.03195), [UniSkill](https://arxiv.org/abs/2603.03134) | Defer taxonomy matching to a later opt-in feature; if added, label it as vocabulary support rather than formal equivalence. | Legal recognition or equivalence of qualifications from semantic similarity. |
| [Secure-CUA](https://arxiv.org/abs/2610.09469) and [FormBharo](https://arxiv.org/abs/2608.06027) | Keep the current scope at preparation and export; no browser agent submits authority forms. | That automatic portal interaction is safe or appropriate for this domain. |

## Claims and attribution discipline

These papers influenced design questions and evaluation requirements. The local implementation uses deterministic parsing/provenance and human review; it does not reproduce the cited papers' experimental methods or claim to invent their techniques. Any public case study must distinguish the paper's reported result from our own measured result, cite the exact version, and state the tested corpus, language, and limitations. Before reusing paper code or datasets, inspect the license and venue record.
