from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_auditor.citations import CitationKey, ReferenceEntry, citation_data
from research_auditor.checks import check_extraction_coverage, check_required_statements
from research_auditor.cli import main as cli_main
from research_auditor.engine import audit_document
from research_auditor.extractors import load_document
from research_auditor.models import AuditReport, Document, Finding
from research_auditor.reference_engines.doi_registry import (
    _redact,
    JsonRequestCache,
    NEGATIVE_TTL_SECONDS,
    DoiRegistryEngine,
)


def audit_markdown(text: str, **kwargs):
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
        handle.write(text)
        path = Path(handle.name)
    try:
        return audit_document(path, **kwargs)
    finally:
        path.unlink(missing_ok=True)


def load_minimal_docx(xml: str):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "probe.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", xml)
        return load_document(path)


class AuditRegressionTests(unittest.TestCase):
    def test_year_ranges_and_appendix_labels_are_not_citations(self):
        report = audit_markdown(
            "# Body\nThe period was (2010 to 2020). See (see Appendix A, 2020 edition). "
            "Evidence exists (Adeyemi, 2020).\n# References\n"
            "Adeyemi, T. (2020). Evidence title. Journal.\n"
        )
        self.assertEqual(report.stats["citation_occurrences"], 1)
        self.assertFalse(any(item.code == "CIT002" for item in report.findings))

    def test_numeric_style_abstains_from_author_date_matching(self):
        report = audit_markdown(
            "# Introduction\nThis follows earlier work [1-3].\n# References\n"
            "1. Smith J. First title. BMJ. 2020.\n2. Doe J. Second title. Nature. 2021.\n"
        )
        codes = {item.code for item in report.findings}
        self.assertEqual(report.stats["citation_style"], "numeric")
        self.assertIn("CIT007", codes)
        self.assertFalse(codes & {"CIT002", "CIT003"})

    def test_multiple_chapter_reference_sections_are_aggregated(self):
        report = audit_markdown(
            "# Chapter 1\nEvidence (Smith, 2020).\n# References\nSmith, J. (2020). First. Journal.\n"
            "# Chapter 2\nEvidence (Doe, 2021).\n# List of References\nDoe, J. (2021). Second. Journal.\n"
        )
        self.assertEqual(report.stats["bibliography_sections"], 2)
        self.assertEqual(report.stats["citation_occurrences"], 2)
        self.assertEqual(report.stats["bibliography_entries"], 2)
        self.assertFalse({item.code for item in report.findings} & {"CIT002", "CIT003"})

    def test_appendix_b_closes_reference_section(self):
        report = audit_markdown(
            "# Body\nEvidence (Smith, 2020).\n# References\nSmith, J. (2020). Study. Journal.\n"
            "Appendix B: Survey Instrument\nRespondent age: ______\n"
        )
        self.assertEqual(report.stats["bibliography_entries"], 1)

    def test_docx_content_controls_and_table_citations_are_extracted(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:sdt><w:sdtContent><w:p><w:r><w:t>Controlled evidence text.</w:t></w:r></w:p></w:sdtContent></w:sdt>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Source: (Smith, 2020)</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>References</w:t></w:r></w:p>
<w:p><w:r><w:t>Smith, J. (2020). Study title. Journal.</w:t></w:r></w:p>
</w:body></w:document>"""
        document = load_minimal_docx(xml)
        self.assertIn("Controlled evidence text.", document.text)
        self.assertEqual(document.extraction_coverage, 1.0)
        citations, references, _ = citation_data(document)
        self.assertEqual(len(citations), 1)
        self.assertEqual(len(references), 1)

    def test_single_letters_are_not_reported_as_abbreviations(self):
        report = audit_markdown(
            "# Body\nA result was significant at P = 0.05.\n# References\nSmith, J. (2020). Study. Journal.\n"
        )
        evidence = " ".join(
            evidence for item in report.findings if item.code == "ABR001" for evidence in item.evidence
        )
        self.assertNotIn("A", evidence.split())
        self.assertNotIn("P", evidence.split())

    def test_required_section_heading_counts_but_incidental_word_does_not(self):
        report = audit_markdown(
            "# Literature Review\nPrior studies discuss limitations generally.\n"
            "# References\nSmith, J. (2020). Study. Journal.\n"
        )
        self.assertIn("REQ_LIMITATIONS", {item.code for item in report.findings})
        with_heading = audit_markdown(
            "# Limitations\nThe available data constrained interpretation.\n"
            "# References\nSmith, J. (2020). Study. Journal.\n"
        )
        self.assertNotIn("REQ_LIMITATIONS", {item.code for item in with_heading.findings})

    def test_low_docx_extraction_coverage_is_high_severity(self):
        document = Document(Path("probe.docx"), [], [], raw_word_count=100, extraction_coverage=0.4)
        findings = check_extraction_coverage(document)
        self.assertEqual([(item.code, item.severity) for item in findings], [("DOC001", "high")])

    @patch("research_auditor.cli.audit_document")
    def test_minimum_confidence_controls_cli_failure_gate(self, mocked_audit):
        mocked_audit.return_value = AuditReport(
            "probe.md", "report", [Finding("ALG999", "high", "Heuristic", "Probe", confidence="low")],
            {}, {},
        )
        with patch("research_auditor.cli.render_markdown", return_value="report"), patch("builtins.print"):
            self.assertEqual(cli_main(["probe.md", "--fail-on", "high", "--min-confidence", "medium"]), 0)
            self.assertEqual(cli_main(["probe.md", "--fail-on", "high", "--min-confidence", "low"]), 1)

    def test_findings_sort_by_severity_then_confidence(self):
        report = audit_markdown(
            "# Objectives\nMeasure banana retention outcomes.\n# Research Questions\n"
            "How does staffing affect turnover?\n# Findings\nStaffing improved turnover.\n"
            "# References\nSmith, J. (2020). Study. Journal.\n"
        )
        severity = {"high": 0, "medium": 1, "low": 2, "info": 3}
        confidence = {"high": 0, "medium": 1, "low": 2}
        observed = [(severity[item.severity], confidence[item.confidence]) for item in report.findings]
        self.assertEqual(observed, sorted(observed))

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_parallel_reference_audit_reports_progress(self, get_json):
        get_json.return_value = (200, {"message": {"items": []}}, None)
        entries = [
            ReferenceEntry(CitationKey("smith", "2020"), 3, "Smith, J. (2020). First title.", None),
            ReferenceEntry(CitationKey("doe", "2021"), 4, "Doe, J. (2021). Second title.", None),
        ]
        progress = []
        DoiRegistryEngine(delay=0, workers=2, progress=lambda done, total, entry: progress.append((done, total))).audit(entries)
        self.assertEqual(progress, [(1, 2), (2, 2)])

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_openalex_uses_doi_shorthand_and_detects_retraction(self, get_json):
        get_json.side_effect = [
            (200, {"message": {"title": ["Study title"], "issued": {"date-parts": [[2020]]}}}, None),
            (200, {"is_retracted": True}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("smith", "2020"), 4,
            "Smith, J. (2020). Study title. https://doi.org/10.9999/example", "10.9999/example",
        )
        findings = DoiRegistryEngine(delay=0).audit([entry])
        self.assertIn("REF005", {item.code for item in findings})
        self.assertIn("/works/doi:10.9999/example", get_json.call_args_list[1].args[0])

    def test_reference_cache_hashes_urls_trims_payloads_and_expires_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            url = "https://api.crossref.org/works?query.bibliographic=Private+Draft+Title"
            cache = JsonRequestCache(path)
            cache.put(url, 200, {"message": {"items": [{"title": ["Match"], "abstract": "sensitive"}]}}, None)
            cache.save()
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("Private+Draft+Title", raw)
            self.assertNotIn("sensitive", raw)

            expired_url = "https://api.datacite.org/dois/10.9999/missing"
            key = JsonRequestCache._key(expired_url)
            path.write_text(json.dumps({"version": 2, "entries": {key: {
                "status": 404, "body": None, "timestamp": time.time() - NEGATIVE_TTL_SECONDS - 1,
            }}}), encoding="utf-8")
            self.assertIsNone(JsonRequestCache(path).get(expired_url))

    def test_harvard_citations_without_a_comma_are_matched(self):
        report = audit_markdown(
            "# Body\nEarlier work (Adeyemi 2019) shaped this, and (Okafor and Bello 2021) confirmed it.\n"
            "# References\nAdeyemi, K. (2019). Something. Journal.\n"
            "Okafor, T., & Bello, A. (2021). Another thing. Journal.\n"
        )
        self.assertEqual(report.stats["citation_occurrences"], 2)
        self.assertFalse(any(item.code in {"CIT002", "CIT003"} for item in report.findings))

    def test_standard_numbers_survive_the_year_range_guard(self):
        report = audit_markdown(
            "# Body\nThe standard (ISO 14001, 2015) applied. The period (2010 to 2020) was covered.\n"
            "# References\nISO. (2015). ISO 14001 Environmental management systems. ISO.\n"
        )
        self.assertEqual(report.stats["citation_occurrences"], 1)
        self.assertFalse(any(item.code == "CIT002" for item in report.findings))

    def test_disclosures_without_an_auxiliary_verb_are_recognised(self):
        for statement in (
            "Ethical approval obtained from the committee.",
            "Ethical clearance was granted by the review board.",
            "Informed consent was obtained from every participant.",
        ):
            with self.subTest(statement=statement):
                report = audit_markdown(f"# Methods\n{statement}\n# References\nSmith, J. (2020). Study. Journal.\n")
                self.assertNotIn("REQ_ETHICS", {item.code for item in report.findings})

        for statement in ("Limitations are noted below.", "Limitations of this study include sampling."):
            with self.subTest(statement=statement):
                report = audit_markdown(f"# Discussion\n{statement}\n# References\nSmith, J. (2020). Study. Journal.\n")
                self.assertNotIn("REQ_LIMITATIONS", {item.code for item in report.findings})

    def test_prose_mentioning_references_does_not_open_a_bibliography(self):
        report = audit_markdown(
            "# Body\nSee the references section.\nEvidence exists (Adeyemi, 2020) across sites in 2019.\n"
            "# References\nAdeyemi, T. (2020). Evidence title. Journal.\n"
        )
        self.assertEqual(report.stats["bibliography_sections"], 1)
        self.assertEqual(report.stats["citation_occurrences"], 1)

    def test_openalex_receives_contact_and_key_as_query_parameters(self):
        with patch("research_auditor.reference_engines.doi_registry._get_json") as get_json:
            get_json.side_effect = [
                (200, {"message": {"title": ["Study title"], "issued": {"date-parts": [[2020]]}}}, None),
                (200, {"is_retracted": False}, None),
            ]
            entry = ReferenceEntry(
                CitationKey("smith", "2020"), 4,
                "Smith, J. (2020). Study title. https://doi.org/10.9999/example", "10.9999/example",
            )
            DoiRegistryEngine("person@example.com", delay=0, openalex_api_key="SECRET").audit([entry])
        openalex_url = get_json.call_args_list[1].args[0]
        self.assertIn("mailto=person%40example.com", openalex_url)
        self.assertIn("api_key=SECRET", openalex_url)
        self.assertEqual(len(get_json.call_args_list[1].args), 1)

    def test_service_errors_do_not_leak_the_api_key(self):
        self.assertEqual(
            _redact("<urlopen error works/doi:10.1/x?mailto=a@b.com&api_key=SECRET failed>"),
            "<urlopen error works/doi:10.1/x?mailto=a@b.com&api_key=[redacted] failed>",
        )


if __name__ == "__main__":
    unittest.main()
