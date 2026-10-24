from __future__ import annotations

from collections import Counter
from pathlib import Path

from .checks import (
    check_abbreviations,
    check_alignment,
    check_citation_integrity,
    check_extraction_coverage,
    check_headings,
    check_numeric_consistency,
    check_required_statements,
    check_tables_and_figures,
)
from .citations import bibliography_ranges, citation_data, detect_citation_style
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
    online_workers: int = 4,
    progress=None,
) -> AuditReport:
    document = load_document(filename)
    selected_profile = detect_profile(document.text) if profile == "auto" else profile
    bibliography_sections = bibliography_ranges(document)
    citations, references, bibliography = citation_data(document, bibliography_sections)
    citation_style = detect_citation_style(document, bibliography_sections, citations)

    findings = []
    findings.extend(check_extraction_coverage(document))
    findings.extend(check_citation_integrity(citations, references, bibliography_sections or None, citation_style))
    findings.extend(check_numeric_consistency(document, bibliography_sections or None))
    findings.extend(check_alignment(document))
    findings.extend(check_tables_and_figures(document, bibliography_sections or None))
    findings.extend(check_abbreviations(document, bibliography_sections or None))
    findings.extend(check_headings(document))
    findings.extend(check_required_statements(document, selected_profile, bibliography_sections or None))

    reference_verifications = []
    if online_references:
        reference_findings, reference_verifications = DoiRegistryEngine(
            email, reference_cache, openalex_api_key=openalex_api_key,
            workers=online_workers, progress=progress,
        ).audit_with_results(references)
        findings.extend(reference_findings)

    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda finding: (
        severity_order.get(finding.severity, 9), confidence_order.get(finding.confidence, 9),
        finding.code, finding.location.paragraph or 0,
    ))
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
        "bibliography_sections": len(bibliography_sections),
        "body_paragraphs_analysed": sum(
            1 for paragraph in document.paragraphs
            if not any(start <= paragraph.index < end for start, end in bibliography_sections)
        ),
        "citation_style": citation_style,
        "docx_extraction_coverage": round(document.extraction_coverage, 4),
        "finding_codes": dict(Counter(finding.code for finding in findings)),
    }
    coverage = {
        "citation_bibliography_matching": (
            "not run (numeric style detected)" if citation_style == "numeric"
            else "automated (author–date styles)"
        ),
        "document_extraction": f"{document.extraction_coverage:.1%} of visible DOCX text recovered",
        "numeric_consistency": "automated heuristic screening",
        "objective_question_finding_alignment": "automated lexical screening",
        "reference_existence_and_metadata": "live DOI and bibliographic metadata checks" if online_references else "not run (use --online-references)",
        "retraction_status": (
            "DOI-linked OpenAlex checks; each result records checked, retracted, or unavailable"
            if online_references else "not run (use --online-references)"
        ),
        "claim_to_source_support": "not automated in v0.3; requires reliable source full text",
        "institutional_rules": "default public profile; custom NovaPoint rules are a later private layer",
    }
    # Preserve the caller's path spelling so reports generated from relative inputs remain portable.
    return AuditReport(
        str(Path(filename).expanduser()), selected_profile, findings, stats, coverage,
        reference_verifications,
    )
