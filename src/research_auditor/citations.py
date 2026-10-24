from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Document, Paragraph

BIBLIOGRAPHY_HEADINGS = {
    "references",
    "reference list",
    "bibliography",
    "works cited",
    "literature cited",
}

BibliographyRanges = list[tuple[int, int]]


@dataclass(frozen=True, order=True)
class CitationKey:
    author: str
    year: str

    def display(self) -> str:
        return f"{self.author.title()} ({self.year})"


@dataclass(frozen=True)
class CitationOccurrence:
    key: CitationKey
    paragraph: int
    raw: str


@dataclass(frozen=True)
class ReferenceEntry:
    key: CitationKey | None
    paragraph: int
    raw: str
    doi: str | None = None


def _is_bibliography_heading(text: str) -> bool:
    stripped = text.strip()
    normalized = re.sub(r"[^a-z ]", " ", stripped.casefold())
    normalized = " ".join(normalized.split())
    if normalized in BIBLIOGRAPHY_HEADINGS:
        return True
    # A section label is not a sentence. Without this, prose such as "See the
    # references section" would open a bibliography range and hide the rest of
    # the document from every body check.
    if re.search(r"[.,;:!?]$", stripped):
        return False
    words = normalized.split()
    return len(words) <= 5 and (
        any(word.startswith("bibliograph") for word in words)
        or "references" in words
        or ("reference" in words and any(word in {"list", "cited"} for word in words))
    )


def _is_appendix_boundary(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.casefold()).strip()
    return bool(re.match(r"^(?:appendix|annex)\b", normalized))


YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b", re.I)


def bibliography_ranges(document: Document) -> BibliographyRanges:
    candidates: list[tuple[int, int]] = []
    # Paragraph indexes are contiguous from 1, so the lookahead window is a
    # slice. Rescanning the whole document per candidate made this quadratic.
    ordered = list(document.paragraphs)
    for position, paragraph in enumerate(ordered):
        if _is_bibliography_heading(paragraph.text):
            if re.search(r"\d\s*$", paragraph.text):
                continue
            if paragraph.style.casefold().startswith(("toc", "tm")):
                continue
            following = ordered[position + 1 : position + 26]
            reference_like = sum(
                1
                for item in following
                if len(item.text) >= 20 and YEAR_PATTERN.search(item.text)
            )
            candidates.append((reference_like, paragraph.index))
    if not candidates:
        return []

    positive = sorted(index for score, index in candidates if score > 0)
    starts = positive or [max(candidates)[1]]
    heading_by_index = {heading.paragraph_index: heading for heading in document.headings}
    ranges: BibliographyRanges = []
    document_end = max((paragraph.index for paragraph in document.paragraphs), default=0) + 1
    for position, start in enumerate(starts):
        heading = heading_by_index.get(start)
        level = heading.level if heading else 1
        structural_end = min(
            (
                item.paragraph_index
                for item in document.headings
                if item.paragraph_index > start and item.level <= level
            ),
            default=document_end,
        )
        next_bibliography = starts[position + 1] if position + 1 < len(starts) else document_end
        end = min(structural_end, next_bibliography)
        appendix = next(
            (
                paragraph.index for paragraph in document.paragraphs
                if start < paragraph.index < end and _is_appendix_boundary(paragraph.text)
            ),
            None,
        )
        if appendix is not None:
            end = appendix
        ranges.append((start, end))
    return ranges


def bibliography_start(document: Document) -> int | None:
    ranges = bibliography_ranges(document)
    return ranges[0][0] if ranges else None


def _inside_ranges(paragraph_index: int, ranges: BibliographyRanges) -> bool:
    return any(start <= paragraph_index < end for start, end in ranges)


def _surname(value: str) -> str:
    value = re.sub(r"^(?:see|e\.g\.|cf\.)\s+", "", value.strip(), flags=re.I)
    value = re.sub(r"\bet\s+al\.?$", "", value, flags=re.I)
    corporate = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    aliases = {
        "who": "who",
        "world health organization": "who",
        "world health organisation": "who",
        "usgs": "usgs",
        "united states geological survey": "usgs",
        "unep": "unep",
        "united nations environment programme": "unep",
        "united nations environmental programme": "unep",
        "world bank": "world bank",
        "world bank group": "world bank",
    }
    for name, canonical in aliases.items():
        if corporate == name or corporate.startswith(name + " "):
            return canonical
    value = value.split("&")[0].split(" and ")[0].split(",")[0]
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", value)
    if not words:
        return ""
    surname = words[-1].casefold().replace("’", "'")
    return re.sub(r"'s$", "", surname)


NON_AUTHOR_WORDS = {
    "a", "an", "the", "to", "from", "since", "between", "until", "through", "during",
    "appendix", "annex", "edition", "table", "figure", "chapter", "section", "version",
    "model", "method", "source", "phase", "classification", "range", "period",
    "vol", "volume", "no", "pp", "p", "ed", "eds", "trans", "para", "fig",
}

# Structure words that never appear inside a real author position. A citation
# such as "(Ministry of Health, 2020)" keeps "of", so only the framing words
# that signal a cross-reference or a date range are rejected here.
_NON_AUTHOR_PATTERN = re.compile(
    r"\b(?:appendix|annex|edition|table|figure|chapter|section|see\s+also|"
    r"from|to|between|until|through)\b",
    re.I,
)


def _valid_parenthetical_author(value: str) -> bool:
    cleaned = re.sub(r"^(?:see|e\.g\.|i\.e\.|cf\.)\s+", "", value.strip(), flags=re.I)
    if not cleaned or not cleaned[0].isupper():
        return False
    # A leading digit means the segment is a number, not a name; a second
    # four-digit year means this is a range such as "(2010 to 2020)". Interior
    # digits are kept so standards like "ISO 14001" still parse.
    if re.match(r"^\d", cleaned) or re.search(r"\b(?:19|20)\d{2}\b", cleaned):
        return False
    if _NON_AUTHOR_PATTERN.search(cleaned):
        return False
    surname = _surname(cleaned)
    return len(surname) >= 2 and surname not in NON_AUTHOR_WORDS


def parse_in_text_citations(
    document: Document,
    before: int | None = None,
    ranges: BibliographyRanges | None = None,
) -> list[CitationOccurrence]:
    occurrences: list[CitationOccurrence] = []
    limit = before or 10**9
    source_paragraphs = list(document.paragraphs)
    source_paragraphs.extend(Paragraph(0, text, "Table") for text in document.table_text if text)
    for paragraph in source_paragraphs:
        if ranges is not None and paragraph.index and _inside_ranges(paragraph.index, ranges):
            continue
        if ranges is None and paragraph.index >= limit:
            continue
        text = paragraph.text
        # Parenthetical author-date groups: (Smith, 2020; Doe & Roe, 2021).
        for group in re.findall(r"\(([^()]*?(?:19|20)\d{2}[a-z]?[^()]*)\)", text):
            for part in re.split(r"\s*;\s*", group):
                # Harvard omits the comma as often as APA includes it, so accept
                # either separator and let the author test reject non-citations.
                match = re.match(r"\s*(.+?)\s*(?:,\s*|\s+)((?:19|20)\d{2}[a-z]?)\b", part)
                if match and _valid_parenthetical_author(match.group(1)):
                    author = _surname(match.group(1))
                    if author:
                        key = CitationKey(author, match.group(2).lower())
                        occurrences.append(CitationOccurrence(key, paragraph.index, part.strip()))
        # Narrative form: Smith et al. (2020) or Smith and Doe (2020).
        for match in re.finditer(
            r"\b([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][\w'’-]+))?)\s*\(((?:19|20)\d{2}[a-z]?)\)",
            text,
        ):
            author = _surname(match.group(1))
            if len(author) < 2 or author in NON_AUTHOR_WORDS:
                continue
            key = CitationKey(author, match.group(2).lower())
            occurrences.append(CitationOccurrence(key, paragraph.index, match.group(0)))

    unique: dict[tuple[CitationKey, int], CitationOccurrence] = {}
    for occurrence in occurrences:
        unique[(occurrence.key, occurrence.paragraph)] = occurrence
    return list(unique.values())


def parse_references(
    document: Document, start: int | None = None, ranges: BibliographyRanges | None = None
) -> list[ReferenceEntry]:
    selected = ranges if ranges is not None else bibliography_ranges(document)
    if ranges is None and start is not None:
        selected = [item for item in selected if item[0] == start] or [(start, 10**9)]
    if not selected:
        return []
    entries: list[ReferenceEntry] = []
    paragraphs = [
        paragraph for paragraph in document.paragraphs
        if any(section_start < paragraph.index < section_end for section_start, section_end in selected)
    ]
    for paragraph in paragraphs:
        raw = paragraph.text.strip()
        if len(raw) < 8:
            continue
        # Appendices are commonly formatted as ordinary paragraphs rather than
        # Word headings, so style metadata alone cannot close the bibliography.
        if _is_appendix_boundary(raw):
            continue
        year_match = re.search(r"\(?((?:19|20)\d{2}[a-z]?)\)?", raw, re.I)
        author_text = raw[: year_match.start()] if year_match else raw[:80]
        author = _surname(author_text)
        key = CitationKey(author, year_match.group(1).lower()) if author and year_match else None
        # Word processors often autocorrect ASCII hyphens inside pasted DOI
        # URLs. Registries use ASCII, so normalise dash variants before parsing.
        doi_text = raw.translate(str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-"}))
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_text, re.I)
        doi = doi_match.group(0).rstrip(".,;:)]}>\"'") if doi_match else None
        entries.append(ReferenceEntry(key, paragraph.index, raw, doi))
    return entries


def detect_citation_style(
    document: Document,
    ranges: BibliographyRanges | None = None,
    citations: list[CitationOccurrence] | None = None,
) -> str:
    selected = ranges if ranges is not None else bibliography_ranges(document)
    body = "\n".join(
        paragraph.text for paragraph in document.paragraphs
        if not _inside_ranges(paragraph.index, selected)
    )
    numeric = len(re.findall(r"\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]", body))
    # Reuse the caller's parse when it has one; parsing a thesis twice is the
    # single largest avoidable cost in an offline audit.
    author_date = len(citations if citations is not None else parse_in_text_citations(document, ranges=selected))
    return "numeric" if numeric > 0 and author_date == 0 else "author-date"


def citation_data(
    document: Document, ranges: BibliographyRanges | None = None
) -> tuple[list[CitationOccurrence], list[ReferenceEntry], int | None]:
    selected = bibliography_ranges(document) if ranges is None else ranges
    start = selected[0][0] if selected else None
    return (
        parse_in_text_citations(document, ranges=selected),
        parse_references(document, ranges=selected),
        start,
    )
