# Audit method and evidence boundaries

Read this reference when interpreting findings, explaining coverage, or deciding whether an online reference warning supports a stronger conclusion.

## Current coverage

The bundled v0.3 engine checks:

- APA/Harvard-style author–date citations against bibliography author–year keys, including table citations;
- multiple bibliography sections and common reference-heading variants;
- bracketed numeric-style detection with explicit abstention from unsupported matching;
- duplicate and unparseable bibliography entries;
- conflicting sample-size and named-percentage candidates;
- lexical alignment among objectives, research questions, and findings;
- table and figure cross-references and possible missing captions;
- repeated abbreviations without a detected definition;
- skipped or duplicate headings;
- missing ethics, limitations, and AI-use statements;
- DOI registration through Crossref with DataCite fallback;
- title/author/year candidate matching for references without DOIs;
- DOI/title/year consistency for registered identifiers;
- DOI-linked OpenAlex retraction status when `--online-references` is used, with per-reference coverage labels.
- visible DOCX extraction through common content controls, with a raw-text coverage warning.

## Finding families

- `CIT`: citation and bibliography matching. `CIT002` and `CIT003` are high-value screens but can be affected by name variants and formatting.
- `CIT007`: bracketed numeric citations were detected; author–date matching was not run.
- `DOC001`: extracted DOCX text fell below the coverage threshold; inspect unsupported Word structures.
- `REF001`: both Crossref and DataCite returned 404 for the supplied DOI. Verify the title independently before alleging fabrication.
- `REF002`: a DOI resolves, but the registered title materially differs.
- `REF003`: the supplied year differs from the registry year. Online-first and issue dates can legitimately differ.
- `REF004`: a registry could not be checked. Retry; this is not evidence against the source.
- `REF005`: OpenAlex marks the DOI as retracted. Review the retraction notice and context.
- `REF006`: a strong title candidate exists but author or year metadata differs.
- `REF007`: a plausible but inconclusive metadata candidate needs manual review.
- `REF008`: no sufficiently strong Crossref match was found. This means unverified, not fabricated.
- `NUM`: potentially inconsistent sample sizes or named percentages. Different analysis populations or time points can be legitimate.
- `ALG`: lexical alignment screen. Low confidence by design; conceptual alignment requires human judgment.
- `VIS`: table and figure caption/cross-reference checks. Decorative drawings and layout tables can create false positives.
- `ABR`: repeated uppercase tokens without a detected parenthetical definition.
- `STR`: semantic heading hierarchy.
- `REQ`: required-statement screening under the selected document profile.

## Verdict discipline

Use “not found” or “could not verify” unless independent evidence supports more. Open indexes have incomplete coverage of books, theses, standards, older works, regional journals, and grey literature.

A strong fabrication finding requires corroborating searches beyond a DOI miss: title variants, author and year, appropriate disciplinary indexes, and author-output checks. The bundled engine does not yet perform that complete cascade.

Claim-support findings require access to the source content. Distinguish full-text comparison from abstract-only comparison. The bundled engine performs neither in v0.3.

Retraction results use four states: `RETRACTED`, `NOT_RETRACTED`, `UNAVAILABLE`, and `NOT_CHECKED_NO_DOI`. Only the first two mean OpenAlex actually returned a DOI-linked work record. Anonymous OpenAlex access has a smaller daily budget; use `--openalex-api-key` with a user-supplied free key for larger batches. Never store the key in a report or cache.

## Known format limits

- Numeric styles such as Vancouver are detected but not matched to numbered bibliography entries.
- Footnotes, endnotes, comments, tracked changes, and embedded citation-manager fields are not inspected.
- Author-name variants beyond the bundled corporate aliases, translated titles, and complex multi-work parentheticals need further hardening.
- Structural requirements are generic until institutional or journal policy profiles are added.
