from __future__ import annotations

import re
from collections import defaultdict

from .citations import BibliographyRanges, CitationOccurrence, ReferenceEntry
from .models import Document, Finding, Location

BibliographyScope = int | BibliographyRanges | None


def _in_bibliography(paragraph_index: int, bibliography: BibliographyScope) -> bool:
    if bibliography is None:
        return False
    if isinstance(bibliography, int):
        return paragraph_index >= bibliography
    return any(start <= paragraph_index < end for start, end in bibliography)


def _body_paragraphs(document: Document, bibliography: BibliographyScope):
    return [
        paragraph for paragraph in document.paragraphs
        if not _in_bibliography(paragraph.index, bibliography)
    ]


def check_citation_integrity(
    citations: list[CitationOccurrence], references: list[ReferenceEntry], bibliography: BibliographyScope,
    citation_style: str = "author-date",
) -> list[Finding]:
    findings: list[Finding] = []
    if bibliography is None:
        return [
            Finding(
                "CIT001",
                "high",
                "Bibliography section not found",
                "No heading named References, Bibliography, Works Cited, or Literature Cited was found.",
                suggestion="Add or correctly label the bibliography section.",
            )
        ]

    if citation_style == "numeric":
        return [
            Finding(
                "CIT007", "info", "Numeric citation style detected",
                "Author–date citation matching was not applied because bracketed numeric citations were detected.",
                suggestion="Use a numeric-style parser or review citation-to-reference numbering manually.",
                confidence="high",
            )
        ]

    cited = {item.key for item in citations}
    listed = {item.key for item in references if item.key}
    ref_by_key = {item.key: item for item in references if item.key}

    def matches(citation_key, reference_key) -> bool:
        if citation_key.author != reference_key.author:
            return False
        if citation_key.year == reference_key.year:
            return True
        return citation_key.year[:4] == reference_key.year[:4] and (
            len(citation_key.year) == 4 or len(reference_key.year) == 4
        )

    for key in sorted(key for key in cited if not any(matches(key, reference) for reference in listed)):
        samples = [item for item in citations if item.key == key]
        findings.append(
            Finding(
                "CIT002",
                "high",
                "In-text citation missing from bibliography",
                f"{key.display()} appears in the text but no matching bibliography entry was found.",
                Location(samples[0].paragraph),
                [sample.raw for sample in samples[:3]],
                "Add the source to the bibliography or correct the in-text citation.",
            )
        )

    for key in sorted(key for key in listed if not any(matches(citation, key) for citation in cited)):
        entry = ref_by_key[key]
        findings.append(
            Finding(
                "CIT003",
                "medium",
                "Bibliography entry is not cited",
                f"{key.display()} is listed in the bibliography but was not found in the body text.",
                Location(entry.paragraph, "References"),
                [entry.raw],
                "Cite the source in the text or remove it from the bibliography.",
                "medium",
            )
        )

    for key in sorted(cited):
        matching = [reference for reference in listed if matches(key, reference)]
        if len(key.year) == 4 and len(matching) > 1:
            samples = [item for item in citations if item.key == key]
            findings.append(
                Finding(
                    "CIT006",
                    "medium",
                    "Citation needs a year suffix",
                    f"{key.display()} matches multiple bibliography entries with year suffixes.",
                    Location(samples[0].paragraph),
                    [reference.display() for reference in sorted(matching)],
                    "Use the correct suffix, such as 2024a or 2024b, in the in-text citation.",
                )
            )

    unparsed = [entry for entry in references if entry.key is None]
    for entry in unparsed:
        findings.append(
            Finding(
                "CIT004",
                "low",
                "Bibliography entry could not be parsed",
                "The entry has no recognisable author–year key, so citation matching may be incomplete.",
                Location(entry.paragraph, "References"),
                [entry.raw],
                "Check the entry format or review this item manually.",
                "medium",
            )
        )

    duplicates: dict[object, list[ReferenceEntry]] = defaultdict(list)
    for entry in references:
        if entry.key:
            duplicates[entry.key].append(entry)
    for key, entries in duplicates.items():
        if len(entries) > 1:
            findings.append(
                Finding(
                    "CIT005",
                    "medium",
                    "Possible duplicate bibliography entries",
                    f"{key.display()} occurs {len(entries)} times in the bibliography.",
                    Location(entries[0].paragraph, "References"),
                    [entry.raw for entry in entries],
                    "Merge duplicates, or add year suffixes such as 2024a and 2024b where appropriate.",
                    "medium",
                )
            )
    return findings


def check_abbreviations(document: Document, bibliography: BibliographyScope) -> list[Finding]:
    body_paragraphs = []
    for paragraph in document.paragraphs:
        if _in_bibliography(paragraph.index, bibliography):
            continue
        letters = [char for char in paragraph.text if char.isalpha()]
        uppercase_ratio = sum(char.isupper() for char in letters) / max(1, len(letters))
        if uppercase_ratio >= 0.65 or paragraph.style.casefold().startswith(("toc", "tm")):
            continue
        body_paragraphs.append(paragraph)
    body = "\n".join(p.text for p in body_paragraphs)
    definitions = {
        match.group(1)
        for match in re.finditer(r"\b[A-Za-z][A-Za-z /&-]{3,80}\s+\(([A-Z][A-Z0-9-]{1,7})\)", body)
    }
    definitions.update(
        match.group(1)
        for match in re.finditer(r"\b([A-Z][A-Z0-9-]{1,7})\s+\([A-Za-z][A-Za-z /&-]{3,80}\)", body)
    )
    tokens = list(re.finditer(r"\b[A-Z][A-Z0-9-]{0,5}[A-Z0-9]\b", body))
    ignored = {
        "AI", "APA", "DOI", "URL", "PDF", "HTML", "XML", "OR", "AND", "CI", "SD",
        "UK", "US", "USA", "EU", "UN", "WHO", "IBM", "SPSS", "ANOVA", "COVID-19",
        "THE", "OF", "IN", "ON", "TO", "FOR", "HEALTH", "CHAPTER", "LIST", "DR",
    }
    counts: dict[str, int] = defaultdict(int)
    for match in tokens:
        counts[match.group(0)] += 1
    undefined = sorted(token for token, count in counts.items() if token not in definitions | ignored and count >= 2)
    findings: list[Finding] = []
    for token in undefined:
        paragraph = next((p.index for p in body_paragraphs if re.search(rf"\b{re.escape(token)}\b", p.text)), None)
        findings.append(
            Finding(
                "ABR001",
                "low",
                "Possibly undefined abbreviation",
                f"{token} appears {counts[token]} times but no expansion in parentheses was found.",
                Location(paragraph),
                [token],
                "Define the abbreviation at first use or add it to the institutional allow-list.",
                "medium",
            )
        )
    return findings


def check_headings(document: Document) -> list[Finding]:
    findings: list[Finding] = []
    previous = None
    seen: dict[str, int] = {}
    for heading in document.headings:
        normalized = heading.text.casefold().strip()
        if normalized in seen:
            findings.append(
                Finding(
                    "STR002",
                    "low",
                    "Duplicate heading",
                    f'The heading “{heading.text}” also occurs at paragraph {seen[normalized]}.' ,
                    Location(heading.paragraph_index, heading.text),
                    suggestion="Rename or consolidate duplicate sections.",
                    confidence="medium",
                )
            )
        else:
            seen[normalized] = heading.paragraph_index
        if previous is not None and heading.level > previous.level + 1:
            findings.append(
                Finding(
                    "STR001",
                    "medium",
                    "Heading level is skipped",
                    f'“{heading.text}” is level {heading.level} immediately after a level {previous.level} heading.',
                    Location(heading.paragraph_index, heading.text),
                    suggestion="Use consecutive heading levels to preserve document hierarchy.",
                )
            )
        previous = heading
    if not document.headings:
        findings.append(
            Finding(
                "STR003",
                "medium",
                "No heading structure detected",
                "The document contains no Word Heading styles, Markdown headings, chapter headings, or numbered headings.",
                suggestion="Apply semantic heading styles so structure can be checked reliably.",
                confidence="medium",
            )
        )
    return findings


def check_tables_and_figures(document: Document, bibliography: BibliographyScope) -> list[Finding]:
    findings: list[Finding] = []
    body_paragraphs = _body_paragraphs(document, bibliography)
    caption_re = re.compile(r"^(Table|Figure)\s+([A-Za-z]?\d+(?:\.\d+)*)\b", re.I)
    captions: list[tuple[str, str, int, str]] = []
    for paragraph in body_paragraphs:
        match = caption_re.match(paragraph.text.strip())
        if match:
            captions.append((match.group(1).title(), match.group(2), paragraph.index, paragraph.text))

    for kind, number, paragraph_index, raw in captions:
        mention = re.compile(rf"\b{kind}\s+{re.escape(number)}\b", re.I)
        elsewhere = [p for p in body_paragraphs if p.index != paragraph_index and mention.search(p.text)]
        mentioned_in_table = any(mention.search(text) for text in document.table_text)
        if not elsewhere and not mentioned_in_table:
            findings.append(
                Finding(
                    "VIS001",
                    "medium",
                    f"{kind} is not mentioned in the text",
                    f"{kind} {number} has a caption but no cross-reference elsewhere in the manuscript.",
                    Location(paragraph_index),
                    [raw],
                    f"Discuss {kind} {number} in the body text.",
                )
            )

    table_captions = sum(1 for kind, *_ in captions if kind == "Table")
    if document.table_count > table_captions:
        findings.append(
            Finding(
                "VIS002",
                "medium",
                "Possible table without a caption",
                f"The DOCX contains {document.table_count} table(s) but only {table_captions} table caption(s) were detected.",
                suggestion="Add a numbered caption to every data table; exclude layout tables in a custom profile.",
                confidence="medium",
            )
        )
    figure_captions = sum(1 for kind, *_ in captions if kind == "Figure")
    if document.drawing_count > figure_captions:
        findings.append(
            Finding(
                "VIS003",
                "low",
                "Possible figure without a caption",
                f"The DOCX contains {document.drawing_count} drawing object(s) but only {figure_captions} figure caption(s) were detected.",
                suggestion="Review drawing objects and caption every research figure; decorative graphics may be ignored.",
                confidence="low",
            )
        )
    return findings


def check_numeric_consistency(document: Document, bibliography: BibliographyScope) -> list[Finding]:
    body = _body_paragraphs(document, bibliography)
    findings: list[Finding] = []
    sample_values: dict[int, list[int]] = defaultdict(list)
    sample_pattern = re.compile(
        r"\b(?:sample(?:\s+size)?)(?:\s+(?:was|is|of|included|comprised|consisted\s+of)|\s*[:=])\s*(?:n\s*=\s*)?(\d{2,7})"
        r"|\b(?:participants?|respondents?|subjects?)\s+(?:were|was|included|numbered|totalled)\s+(\d{2,7})",
        re.I,
    )
    for paragraph in body:
        for match in sample_pattern.finditer(paragraph.text):
            value = int(match.group(1) or match.group(2))
            sample_values[value].append(paragraph.index)
    if len(sample_values) > 1:
        evidence = [f"n={value} at paragraph(s) {', '.join(map(str, locations[:4]))}" for value, locations in sorted(sample_values.items())]
        findings.append(
            Finding(
                "NUM001",
                "medium",
                "Conflicting sample-size candidates",
                f"The manuscript appears to report {len(sample_values)} different sample sizes.",
                evidence=evidence,
                suggestion="Confirm whether these values describe recruited, eligible, analysed, or subgroup samples and label them explicitly.",
                confidence="medium",
            )
        )

    metric_pattern = re.compile(
        r"\b(response rate|prevalence|incidence|completion rate|retention rate|attrition rate)\b[^\d.%\n]{0,45}(\d+(?:\.\d+)?)\s*%",
        re.I,
    )
    metric_values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for paragraph in body:
        for match in metric_pattern.finditer(paragraph.text):
            metric_values[match.group(1).casefold()][match.group(2)].append(paragraph.index)
    for metric, values in metric_values.items():
        if len(values) > 1:
            findings.append(
                Finding(
                    "NUM002",
                    "medium",
                    "Conflicting percentage candidates",
                    f"Different values are reported for {metric}: {', '.join(value + '%' for value in values)}.",
                    evidence=[f"{value}% at paragraph(s) {', '.join(map(str, locations))}" for value, locations in values.items()],
                    suggestion="Confirm whether the percentages use different populations or time points and label the denominator for each.",
                    confidence="medium",
                )
            )
    return findings


def _section_items(document: Document, terms: tuple[str, ...]) -> list[tuple[int, str]]:
    matching = [h for h in document.headings if any(term in h.text.casefold() for term in terms)]
    if not matching:
        return []
    heading = matching[0]
    end = next(
        (h.paragraph_index for h in document.headings if h.paragraph_index > heading.paragraph_index and h.level <= heading.level),
        10**9,
    )
    items = []
    for p in document.paragraphs:
        if heading.paragraph_index < p.index < end and 8 <= len(p.text) <= 500:
            items.append((p.index, re.sub(r"^\s*(?:\d+[.)]|[a-z][.)]|[-•])\s*", "", p.text, flags=re.I)))
    return items


def _keywords(text: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into", "among", "between", "study",
        "research", "determine", "assess", "examine", "investigate", "evaluate", "identify", "what", "how",
        "was", "were", "are", "is", "of", "to", "in", "on", "a", "an", "its", "their", "findings", "results",
    }
    return {word for word in re.findall(r"[a-z]{3,}", text.casefold()) if word not in stop}


def _similarity(left: str, right: str) -> float:
    a, b = _keywords(left), _keywords(right)
    return len(a & b) / max(1, len(a | b))


def check_alignment(document: Document) -> list[Finding]:
    objectives = _section_items(document, ("objective", "aim of the study", "study aim"))
    questions = _section_items(document, ("research question",))
    findings = _section_items(document, ("findings", "results", "conclusion"))
    output: list[Finding] = []
    if objectives and questions and len(objectives) != len(questions):
        output.append(
            Finding(
                "ALG001",
                "medium",
                "Objective and research-question counts differ",
                f"Detected {len(objectives)} objective item(s) and {len(questions)} research-question item(s).",
                suggestion="Map each objective to a research question, or explain why the structure differs.",
                confidence="medium",
            )
        )
    for paragraph, objective in objectives:
        if questions:
            best = max((_similarity(objective, question), question) for _, question in questions)
            if best[0] < 0.12:
                output.append(
                    Finding(
                        "ALG002",
                        "medium",
                        "Objective may not align with a research question",
                        "No research question has strong keyword overlap with this objective.",
                        Location(paragraph, "Objectives"),
                        [objective, f"Closest question: {best[1]}"],
                        "Review the conceptual mapping; lexical checks are only a screening signal.",
                        "low",
                    )
                )
        if findings:
            best = max((_similarity(objective, finding), finding) for _, finding in findings)
            if best[0] < 0.08:
                output.append(
                    Finding(
                        "ALG003",
                        "medium",
                        "Objective may not be addressed in findings",
                        "No finding or conclusion item has strong keyword overlap with this objective.",
                        Location(paragraph, "Objectives"),
                        [objective, f"Closest finding: {best[1]}"],
                        "Confirm that the findings explicitly answer this objective.",
                        "low",
                    )
                )
    return output


def check_required_statements(
    document: Document, profile: str, bibliography: BibliographyScope = None
) -> list[Finding]:
    text = "\n".join(paragraph.text for paragraph in _body_paragraphs(document, bibliography)).casefold()
    headings = "\n".join(heading.text for heading in document.headings).casefold()
    requirements = {
        "ethics": (
            r"ethical approval (?:was|has been|was not)|ethical considerations?|ethics (?:approval|committee)|"
            r"institutional review board|informed consent (?:was|has been|was not)",
            "ethics or consent statement",
        ),
        "limitations": (
            r"\blimitations?\b\s*(?:of (?:this|the) study|were|was|include|included|noted|:)"
            r"|(?:this|the) study (?:was|is) limited by",
            "limitations statement",
        ),
        "ai_use": (
            r"(?:no|not|without) (?:generative |artificial )?ai (?:was )?used|"
            r"(?:used|use of|assistance from) (?:chatgpt|generative ai|artificial intelligence|a large language model)|"
            r"ai[- ]use (?:statement|disclosure)",
            "AI-use disclosure",
        ),
    }
    severity = {"ethics": "medium", "limitations": "medium", "ai_use": "low"}
    output = []
    for key, (pattern, label) in requirements.items():
        heading_patterns = {
            "ethics": r"(?:^|\n)(?:ethical considerations?|ethics|research ethics)(?:$|\n)",
            "limitations": r"(?:^|\n)(?:study )?limitations?(?:$|\n)",
            "ai_use": r"(?:^|\n)(?:ai[- ]use|artificial intelligence use|generative ai) (?:statement|disclosure)(?:$|\n)",
        }
        if not re.search(pattern, text, re.I) and not re.search(heading_patterns[key], headings, re.I):
            article = "an" if label[0].casefold() in "aeiou" else "a"
            output.append(
                Finding(
                    f"REQ_{key.upper()}",
                    severity[key],
                    f"Missing {label}",
                    f"No {label} was detected under the {profile} profile.",
                    suggestion=f"Add {article} {label}, or disable this rule in an institutional profile when it does not apply.",
                    confidence="medium",
                )
            )
    return output


def check_extraction_coverage(document: Document) -> list[Finding]:
    if document.raw_word_count is None or document.extraction_coverage >= 0.90:
        return []
    return [
        Finding(
            "DOC001", "high", "DOCX extraction may be incomplete",
            f"Only {document.extraction_coverage:.1%} of visible DOCX word tokens were recovered for analysis.",
            evidence=[f"Raw XML words: {document.raw_word_count}", f"Coverage: {document.extraction_coverage:.1%}"],
            suggestion="Inspect content controls, text boxes, embedded objects, or unsupported Word structures before trusting the audit.",
            confidence="high",
        )
    ]
