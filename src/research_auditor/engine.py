from __future__ import annotations

from collections import Counter
from pathlib import Path

from .checks import (
    check_abbreviations,
    check_alignment,
    check_citation_integrity,
    check_headings,
    check_numeric_consistency,
    check_required_statements,
    check_tables_and_figures,
)
from .citations import citation_data
from .extractors import load_document
from .models import AuditReport
from .reference_engines.doi_registry import DoiRegistryEngine


def detect_profile(text: str) -> str:
    lowered = text.casefold()
    if "research question" in lowered or lowered.count("chapter ") >= 2:
        return "thesis"
    if "abstract" in lowered and "references" in lowered:
        return "journal"
    return "report"


def audit_document(
    filename: str | Path,
    *,
    profile: str = "auto",
    online_references: bool = False,
    email: str | None = None,
    reference_cache: str | Path | None = None,
    openalex_api_key: str | None = None,
) -> AuditReport:
    document = load_document(filename)
    selected_profile = detect_profile(document.text) if profile == "auto" else profile
    citations, references, bibliography = citation_data(document)

    findings = []
    findings.extend(check_citation_integrity(citations, references, bibliography))
    findings.extend(check_numeric_consistency(document, bibliography))
    findings.extend(check_alignment(document))
    findings.extend(check_tables_and_figures(document, bibliography))
    findings.extend(check_abbreviations(document, bibliography))
    findings.extend(check_headings(document))
    findings.extend(check_required_statements(document, selected_profile))

    reference_verifications = []
    if online_references:
        reference_findings, reference_verifications = DoiRegistryEngine(
            email, reference_cache, openalex_api_key=openalex_api_key
        ).audit_with_results(references)
        findings.extend(reference_findings)

    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda finding: (severity_order.get(finding.severity, 9), finding.code, finding.location.paragraph or 0))
    parsed_references = sum(1 for reference in references if reference.key)
    stats = {
        "paragraphs": len(document.paragraphs),
        "words": len(document.text.split()),
        "headings": len(document.headings),
        "tables": document.table_count,
        "drawings": document.drawing_count,
        "citation_occurrences": len(citations),
        "unique_citations": len({citation.key for citation in citations}),
        "bibliography_entries": len(references),
        "parsed_bibliography_entries": parsed_references,
        "bibliography_entries_with_doi": sum(1 for reference in references if reference.doi),
        "finding_codes": dict(Counter(finding.code for finding in findings)),
    }
    coverage = {
        "citation_bibliography_matching": "automated (author–date styles)",
        "numeric_consistency": "automated heuristic screening",
        "objective_question_finding_alignment": "automated lexical screening",
        "reference_existence_and_metadata": "live DOI and bibliographic metadata checks" if online_references else "not run (use --online-references)",
        "retraction_status": (
            "DOI-linked OpenAlex checks; each result records checked, retracted, or unavailable"
            if online_references else "not run (use --online-references)"
        ),
        "claim_to_source_support": "not automated in v0.2; requires reliable source full text",
        "institutional_rules": "default public profile; custom NovaPoint rules are a later private layer",
    }
    # Preserve the caller's path spelling so reports generated from relative inputs remain portable.
    return AuditReport(
        str(Path(filename).expanduser()), selected_profile, findings, stats, coverage,
        reference_verifications,
    )
