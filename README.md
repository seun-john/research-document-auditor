# Research Document Auditor

A privacy-first command-line auditor for theses, reports, and journal manuscripts. It turns structural, citation, consistency, and disclosure checks into evidence-backed findings that a researcher can review before submission.

This repository is the open-source engine. NovaPoint-specific templates, institutional profiles, and client rules can remain a separate private layer.

## What v0.3 checks

- author–date citations missing from the bibliography, including citations found in DOCX tables;
- bibliography entries not cited in the manuscript;
- multiple chapter-level reference sections and common headings such as `List of References`;
- duplicate or unparseable bibliography entries;
- contradictory sample-size and named-percentage candidates;
- possible objective, research-question, and findings misalignment;
- tables and figures not mentioned in the text, plus possible missing captions;
- repeated abbreviations without a detected definition;
- skipped or duplicate heading levels;
- missing ethics, limitations, and AI-use statements;
- optional live verification of DOI and non-DOI references using Crossref and DataCite;
- DOI-linked retraction checks through OpenAlex, with explicit unavailable coverage when the service budget is exhausted.
- DOCX extraction coverage, including visible content inside Word content controls.

Every heuristic finding includes a confidence level. A low-confidence screen is a prompt for human review, not a verdict.

## Install as a skill

The repository root is the skill. Clone the complete repository into a skills directory supported by Codex, Claude Code, or another compatible coding agent:

```powershell
git clone <repository-url> "$env:USERPROFILE\.codex\skills\research-document-auditor"
cd "$env:USERPROFILE\.codex\skills\research-document-auditor"
python scripts\audit.py manuscript.docx --output manuscript-audit.md --fail-on none
```

No Python package installation is required. The root `SKILL.md` tells the agent when to invoke the bundled deterministic engine and how to interpret its findings conservatively.

Example request:

> Use $research-document-auditor to audit my thesis and explain the high-confidence findings first.

## Install as a CLI

The offline checker uses only the Python standard library and requires Python 3.10 or newer.

```powershell
python -m pip install -e .
research-audit thesis.docx --output audit-report.md
```

Run the optional live reference engine and keep a reusable evidence cache:

```powershell
research-audit thesis.docx --online-references --online-workers 4 --reference-cache reference-cache.json --output audit-report.md
```

For fuller retraction coverage, create a free OpenAlex key and supply it at runtime. Do not commit the key:

```powershell
research-audit thesis.docx --online-references --openalex-api-key YOUR_KEY --reference-cache reference-cache.json --output audit-report.md
```

Produce machine-readable output for CI or a later web interface:

```powershell
research-audit manuscript.docx --format json --output audit-report.json --fail-on high
```

Supported inputs are `.docx`, `.md`, and `.txt`. The command exits `1` when it finds an issue at or above `--fail-on`, `2` for an input/runtime error, and `0` otherwise.
Use `--min-confidence high` or `medium` to stop low-confidence heuristic findings from failing CI. Online progress is written to stderr.

The optional cache stores hashed request keys, reduced public metadata fields, and expiry timestamps. It does not store manuscript text as a document, but bibliographic metadata can still be sensitive; keep cache files private and out of Git.

## Design

```text
skill request or CLI command
        │
        ▼
document (.docx/.md/.txt)
        │
        ▼
  format extractor
        │
        ▼
 normalized document model
        │
        ├── deterministic offline checks
        ├── DOI registry engine (optional/live)
        └── future full-text claim-support engine
        │
        ▼
 stable finding schema ──► Markdown / JSON / future web UI
```

The live reference checker is an engine rather than the whole product. This lets later engines add full-text claim support, similarity/plagiarism screening, journal-specific policies, and institutional rules without changing the report contract.

## Important limits

- Citation matching targets APA/Harvard-style author–date citations, with or without the comma: `(Smith, 2020)` and `(Smith 2020)` both parse. Bracketed numeric styles are detected and clearly reported as unsupported instead of producing author–date mismatch findings.
- DOCX extraction reads paragraph text, heading styles, content controls, text boxes, tables, and drawing counts. It does not yet inspect footnotes, endnotes, comments, tracked changes, or embedded citation-manager fields. A `DOC001` finding is raised when recovered text falls below 90% of the visible word tokens.
- Numeric and alignment findings are deliberately labelled as heuristic candidates.
- DOI registration proves that a DOI exists, not that a source supports a claim.
- Claim-to-source support is not automated in v0.3. Reliable checking needs the cited source’s full text or a clearly labelled abstract-only comparison.
- An OpenAlex `UNAVAILABLE` result means retraction status was not established. OpenAlex now meters anonymous access against a daily budget and can return `429` once it is spent, so confirm your own quota before treating `UNAVAILABLE` as unusual. `--openalex-api-key` is sent as the documented `api_key` query parameter and is redacted from any error text the report shows.
- A registry outage or missing index record is never treated as proof of fabrication.

## Next build slices

1. Add full-text retrieval and sentence-to-source claim support with explicit full-text/abstract coverage labels.
2. Add full numeric citation matching plus CSL JSON/BibTeX/RIS, footnotes, and citation-manager fields.
3. Add custom YAML/JSON policy profiles for universities, journals, and private NovaPoint rules.
4. Add configurable service time budgets and richer service-health summaries.
5. Create a reviewable HTML report, then wrap the same engine in a paid upload-and-audit web interface.

## Publish this repository on GitHub

The `.gitignore` excludes local audit reports, caches, virtual environments, and generated build files. Review `git status` before every public push so no manuscript-derived data is included.

Using GitHub CLI:

```powershell
git init
git add README.md SKILL.md pyproject.toml src tests references .github .gitignore
git status
git commit -m "Release Research Document Auditor v0.3.0"
gh auth login
gh repo create research-document-auditor --public --source . --remote origin --push
```

Without GitHub CLI, create an empty public repository on GitHub, then run the `git init` through `git commit` commands above followed by:

```powershell
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/research-document-auditor.git
git push -u origin main
```

Before announcing the project, replace `YOUR-USERNAME`, confirm the MIT licence and author name are correct, and create a `v0.3.0` release from the tested commit.

## Test

```powershell
python -m unittest discover -s tests -v
```

## Licence

MIT. The public engine can remain open source while private policy packs and hosted audit workflows are licensed separately.


## Research paper

This tool was evaluated, with and without each tool, in an open preprint: Oluwawalemi, O. J. (2026). Do Verification Tools Improve on an AI Reader? A With-and-Without Evaluation of Fifteen Open-Source Tools for AI-Assisted Research. Zenodo. https://doi.org/10.5281/zenodo.23404947

The test corpora, truth labels, verdicts and scripts are in the same Zenodo record. Independent replication and testing are welcome. Please open an issue to share results.
