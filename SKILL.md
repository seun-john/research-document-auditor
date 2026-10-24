---
name: research-document-auditor
description: Audit a thesis, report, dissertation, or journal manuscript for citation–bibliography mismatches, inconsistent research details, structural problems, missing disclosures, and optional live reference-verification issues. Use when a user asks to audit, preflight, quality-check, or submission-check a research document. Do not use as a substitute for peer review or to allege fabrication without external evidence.
license: MIT
---

# Research Document Auditor

Use the bundled deterministic auditor, then interpret its evidence conservatively. The original manuscript is read-only.

## Run an audit

Accept `.docx`, `.md`, or `.txt`. Choose `thesis`, `journal`, or `report` when the user identifies the document type; otherwise use `auto`.

Run from this skill directory, or replace `scripts/audit.py` with its absolute path:

```powershell
python scripts/audit.py "manuscript.docx" --profile auto --format json --output "manuscript-audit.json" --fail-on none
```

Add `--online-references` only when reference existence or citation metadata is in scope. Reuse a cache so evidence is reproducible and public services are not queried unnecessarily:

```powershell
python scripts/audit.py "manuscript.docx" --online-references --online-workers 4 --reference-cache "reference-cache.json" --format json --output "manuscript-audit.json" --fail-on none
```

Add `--email` only when the user supplied a real contact address. Add `--openalex-api-key` only when the user supplied a key; it increases the free daily budget for DOI-linked retraction checks. Never invent either value or commit a key or reference cache to the repository. Cache keys are hashed and cached metadata is reduced, but reference metadata may still be sensitive.

## Review the result

Lead with high-confidence findings that affect submission integrity. Keep heuristic candidates separate and inspect their evidence before recommending changes.

- Citation matching shows that author–year keys agree; it does not prove a reference is genuine.
- `CIT007` means a bracketed numeric style was detected and author–date matching deliberately abstained.
- `DOC001` means visible DOCX content may not have been fully extracted; treat the audit as incomplete until reviewed.
- Numeric, alignment, abbreviation, and caption-count findings are screening signals.
- A network failure or missing index record is not evidence of fabrication.
- `VERIFIED` means the open metadata passed the documented title/author/year thresholds; it does not show that the source supports a claim.
- `REAL_BUT_MIS_CITED` means a registry match was found but supplied metadata differs; review the linked record.
- `POSSIBLE_MATCH` and `UNVERIFIED` require human searching. Neither means fabricated.
- An `UNREGISTERED_DOI` is a strong warning only after both Crossref and DataCite return 404, and still requires an independent title/author search before a fabrication verdict.
- Treat retraction status as checked only when the result says `NOT_RETRACTED` or `RETRACTED`; `UNAVAILABLE` is not a clean result.
- Never say a source supports a claim unless its full text or clearly identified abstract was actually compared with that claim.
- State that claim-support checking is unavailable in the bundled v0.3 engine.
- Report evidence without speculating about the author's intent or whether AI produced the document.

For check coverage, finding-code interpretation, and known limits, read [references/audit-method.md](references/audit-method.md).
