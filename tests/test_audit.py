from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from research_auditor.citations import CitationKey, ReferenceEntry, bibliography_start, citation_data
from research_auditor.checks import check_citation_integrity, check_numeric_consistency
from research_auditor.engine import audit_document
from research_auditor.extractors import load_document
from research_auditor.reference_engines.doi_registry import DoiRegistryEngine
from research_auditor.reporters import render_json, render_markdown


FIXTURE = Path(__file__).parent / "fixtures" / "sample_manuscript.md"


class AuditTests(unittest.TestCase):
    def test_extracts_citations_and_references(self):
        document = load_document(FIXTURE)
        citations, references, start = citation_data(document)
        self.assertIsNotNone(start)
        self.assertEqual({item.key.author for item in citations}, {"doe"})
        self.assertEqual({item.key.author for item in references if item.key}, {"smith"})

    def test_narrative_possessive_citation_uses_author_surname(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write("# Findings\n\nOliver’s (1980) model remains influential.\n\n# References\n\nOliver, R. (1980). A cognitive model.\n")
            path = Path(handle.name)
        try:
            citations, references, _ = citation_data(load_document(path))
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([item.key.author for item in citations], ["oliver"])
        self.assertEqual([item.key.author for item in references if item.key], ["oliver"])

    def test_bibliography_selection_ignores_table_of_contents_label(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(
                "# Contents\nReferences 20\n# Chapter 1\nBody text (Smith, 2020).\n"
                "# References\nSmith, J. (2020). A real reference title. Journal Name.\n"
            )
            path = Path(handle.name)
        try:
            document = load_document(path)
            start = bibliography_start(document)
            citations, references, _ = citation_data(document)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(document.paragraphs[start - 1].text, "References")
        self.assertEqual(len(citations), 1)
        self.assertEqual(len(references), 1)

    def test_unstyled_appendix_closes_bibliography(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(
                "# References\nSmith, J. (2020). A study.\n"
                "APPENDIX I QUESTIONNAIRE\nDear Respondent, please complete this form.\n"
            )
            path = Path(handle.name)
        try:
            _, references, _ = citation_data(load_document(path))
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([entry.raw for entry in references], ["Smith, J. (2020). A study."])

    def test_typographic_dashes_in_doi_are_normalized(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(
                "# References\nSmith, J. (2020). A study. https://doi.org/10.1007/978–3–031–34688–0_2\n"
            )
            path = Path(handle.name)
        try:
            _, references, _ = citation_data(load_document(path))
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(references[0].doi, "10.1007/978-3-031-34688-0_2")

    def test_corporate_author_aliases_and_year_suffixes_match(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(
                "# Body\nGuidelines apply (WHO, 2016), as does prior evidence (Ayantobo, 2014).\n"
                "# References\nWorld Health Organization. (2016). Guidelines.\n"
                "Ayantobo, O. (2014a). Evidence title.\n"
            )
            path = Path(handle.name)
        try:
            document = load_document(path)
            citations, references, start = citation_data(document)
            findings = check_citation_integrity(citations, references, start)
        finally:
            path.unlink(missing_ok=True)
        self.assertFalse(any(item.code in {"CIT002", "CIT003"} for item in findings))

    def test_subgroup_counts_are_not_sample_size_conflicts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
            handle.write(
                "# Results\nThe sample size was 189 respondents. Table values were N = 17, N = 53, and N = 80.\n"
                "# References\nSmith, J. (2020). Reference title.\n"
            )
            path = Path(handle.name)
        try:
            document = load_document(path)
            findings = check_numeric_consistency(document, bibliography_start(document))
        finally:
            path.unlink(missing_ok=True)
        self.assertFalse(any(item.code == "NUM001" for item in findings))

    def test_expected_findings_are_reported(self):
        report = audit_document(FIXTURE, profile="thesis")
        codes = {finding.code for finding in report.findings}
        self.assertTrue({"CIT002", "CIT003", "NUM001", "NUM002", "VIS001"}.issubset(codes))
        self.assertIn("REQ_ETHICS", codes)
        self.assertIn("REQ_AI_USE", codes)
        self.assertNotIn("REQ_LIMITATIONS", codes)
        numeric_evidence = {
            finding.code: finding.evidence for finding in report.findings if finding.code.startswith("NUM")
        }
        self.assertEqual(numeric_evidence["NUM001"], ["n=120 at paragraph(s) 6", "n=140 at paragraph(s) 8"])
        self.assertEqual(numeric_evidence["NUM002"], ["80% at paragraph(s) 8", "75% at paragraph(s) 8"])

    def test_reports_are_serializable(self):
        report = audit_document(FIXTURE)
        self.assertIn('"schema_version": "1.2"', render_json(report))
        self.assertIn("# Research Document Audit", render_markdown(report))

    def test_rejects_unsupported_format(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            with self.assertRaises(ValueError):
                load_document(handle.name)

    def test_extracts_minimal_docx_structure(self):
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Methods</w:t></w:r></w:p>
    <w:p><w:r><w:t>The sample included 100 respondents.</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  </w:body>
</w:document>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "minimal.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document_xml)
            document = load_document(path)
        self.assertEqual(document.table_count, 1)
        self.assertEqual(document.table_text, ["Value"])
        self.assertEqual([(heading.text, heading.level) for heading in document.headings], [("Methods", 1)])

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_unregistered_doi_requires_two_registry_misses(self, get_json):
        get_json.side_effect = [(404, None, None), (404, None, None)]
        entry = ReferenceEntry(CitationKey("smith", "2020"), 8, "Smith (2020). A title. doi:10.9999/missing", "10.9999/missing")
        findings = DoiRegistryEngine().audit([entry])
        self.assertEqual([finding.code for finding in findings], ["REF001"])
        self.assertEqual(get_json.call_count, 2)

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_doi_metadata_and_retraction_findings(self, get_json):
        get_json.side_effect = [
            (200, {"message": {"title": ["A completely different work"], "issued": {"date-parts": [[2019]]}}}, None),
            (200, {"is_retracted": True}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("smith", "2020"),
            8,
            "Smith, J. (2020). Hospital staff retention. Journal Name. https://doi.org/10.9999/example",
            "10.9999/example",
        )
        codes = {finding.code for finding in DoiRegistryEngine().audit([entry])}
        self.assertEqual(codes, {"REF002", "REF003", "REF005"})

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_online_title_search_records_verified_reference(self, get_json):
        get_json.side_effect = [
            (
                200,
                {
                    "message": {
                        "items": [
                            {
                                "title": ["Hospital staff retention"],
                                "author": [{"given": "Jane", "family": "Smith"}],
                                "issued": {"date-parts": [[2020]]},
                                "DOI": "10.9999/example",
                                "URL": "https://doi.org/10.9999/example",
                            }
                        ]
                    }
                },
                None,
            ),
            (200, {"is_retracted": False}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("smith", "2020"), 8,
            "Smith, J. (2020). Hospital staff retention. Journal Name.", None,
        )
        findings, results = DoiRegistryEngine(delay=0).audit_with_results([entry])
        self.assertEqual(findings, [])
        self.assertEqual(results[0].status, "VERIFIED")
        self.assertEqual(results[0].doi, "10.9999/example")

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_exact_title_and_year_can_verify_incomplete_author_metadata(self, get_json):
        get_json.side_effect = [
            (200, {"message": {"items": [{
                "title": ["Hospital staff retention"],
                "author": [{"family": "Different"}],
                "issued": {"date-parts": [[2020]]},
                "DOI": "10.9999/example",
            }]}}, None),
            (200, {"is_retracted": False}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("smith", "2020"), 8,
            "Smith, J. (2020). Hospital staff retention. Journal Name.", None,
        )
        findings, results = DoiRegistryEngine(delay=0).audit_with_results([entry])
        self.assertEqual(findings, [])
        self.assertEqual(results[0].status, "VERIFIED")
        self.assertEqual(results[0].confidence, "medium")

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_doi_main_title_matches_cited_subtitle(self, get_json):
        get_json.side_effect = [
            (200, {"message": {
                "title": ["Location and Land Use"],
                "issued": {"date-parts": [[1966]]},
            }}, None),
            (200, {"is_retracted": False}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("alonso", "1966"), 8,
            "Alonso, W. (1966). Location and land use: Toward a general theory of land rent. https://doi.org/10.9999/book",
            "10.9999/book",
        )
        findings, results = DoiRegistryEngine(delay=0).audit_with_results([entry])
        self.assertNotIn("REF002", {item.code for item in findings})
        self.assertEqual(results[0].status, "VERIFIED")

    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_online_title_search_uses_unverified_not_fabricated(self, get_json):
        get_json.return_value = (200, {"message": {"items": []}}, None)
        entry = ReferenceEntry(
            CitationKey("smith", "2020"), 8,
            "Smith, J. (2020). An uncertain source. Journal Name.", None,
        )
        findings, results = DoiRegistryEngine(delay=0).audit_with_results([entry])
        self.assertEqual([item.code for item in findings], ["REF008"])
        self.assertEqual(results[0].status, "UNVERIFIED")

    @patch("research_auditor.reference_engines.doi_registry.time.sleep")
    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_online_lookup_retries_rate_limit(self, get_json, sleep):
        get_json.side_effect = [
            (429, None, None),
            (200, {"message": {"items": []}}, None),
        ]
        entry = ReferenceEntry(
            CitationKey("smith", "2020"), 8,
            "Smith, J. (2020). An uncertain source. Journal Name.", None,
        )
        findings, results = DoiRegistryEngine(delay=0).audit_with_results([entry])
        self.assertEqual(get_json.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual([item.code for item in findings], ["REF008"])
        self.assertEqual(results[0].status, "UNVERIFIED")

    @patch("research_auditor.reference_engines.doi_registry.time.sleep")
    @patch("research_auditor.reference_engines.doi_registry._get_json")
    def test_retraction_service_disables_after_budget_exhaustion(self, get_json, sleep):
        registered = {
            "message": {
                "title": ["A title"],
                "issued": {"date-parts": [[2020]]},
            }
        }
        get_json.side_effect = [
            (200, registered, None), (429, None, None), (429, None, None), (429, None, None),
            (200, registered, None),
        ]
        entries = [
            ReferenceEntry(CitationKey("smith", "2020"), 8, "Smith (2020). A title.", f"10.9999/{suffix}")
            for suffix in ("one", "two")
        ]
        _, results = DoiRegistryEngine(delay=0).audit_with_results(entries)
        self.assertEqual(get_json.call_count, 5)
        self.assertEqual([item.retraction_status for item in results], ["UNAVAILABLE", "UNAVAILABLE"])


if __name__ == "__main__":
    unittest.main()
