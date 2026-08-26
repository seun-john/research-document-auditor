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
    normalized = re.sub(r"[^a-z ]", " ", text.casefold())
    normalized = " ".join(normalized.split())
    if normalized in BIBLIOGRAPHY_HEADINGS:
        return True
    words = normalized.split()
    return len(words) <= 5 and (
        any(word.startswith("bibliograph") for word in words)
        or "references" in words
        or ("reference" in words and any(word in {"list", "cited"} for word in words))
    )


def _is_appendix_boundary(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.casefold()).strip()
    return bool(re.match(r"^(?:appendix|annex)\b", normalized))


def bibliography_ranges(document: Document) -> BibliographyRanges:
    candidates: list[tuple[int, int]] = []
    for paragraph in document.paragraphs:
        if _is_bibliography_heading(paragraph.text):
            if re.search(r"\d\s*$", paragraph.text):
                continue
            if paragraph.style.casefold().startswith(("toc", "tm")):
                continue
            following = [p.text for p in document.paragraphs if paragraph.index < p.index <= paragraph.index + 25]
            reference_like = sum(
                1
                for text in following
                if len(text) >= 20 and re.search(r"\b(?:19|20)\d{2}[a-z]?\b", text, re.I)
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


def _valid_parenthetical_author(value: str) -> bool:
    cleaned = re.sub(r"^(?:see|e\.g\.|cf\.)\s+", "", value.strip(), flags=re.I)
    if not cleaned or not cleaned[0].isupper() or re.search(r"\d", cleaned):
        return False
    if re.search(r"\b(?:appendix|annex|edition|table|figure|chapter|section|from|to|between)\b", cleaned, re.I):
        return False
    surname = _surname(cleaned)
    return len(surname) >= 2 and surname not in {
        "a", "an", "the", "to", "from", "since", "between", "appendix", "edition",
    }


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
                match = re.match(r"\s*(.+?)\s*,\s*((?:19|20)\d{2}[a-z]?)\b", part)
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
            if len(author) < 2 or author in {
                "a", "classification", "figure", "table", "chapter", "section", "model",
                "method", "source", "version", "phase", "appendix", "edition", "to", "from",
            }:
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


def detect_citation_style(document: Document, ranges: BibliographyRanges | None = None) -> str:
    selected = ranges if ranges is not None else bibliography_ranges(document)
    body = "\n".join(
        paragraph.text for paragraph in document.paragraphs
        if not _inside_ranges(paragraph.index, selected)
    )
    numeric = len(re.findall(r"\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]", body))
    author_date = len(parse_in_text_citations(document, ranges=selected))
    return "numeric" if numeric > 0 and author_date == 0 else "author-date"


def citation_data(document: Document) -> tuple[list[CitationOccurrence], list[ReferenceEntry], int | None]:
    ranges = bibliography_ranges(document)
    start = ranges[0][0] if ranges else None
    return (
        parse_in_text_citations(document, ranges=ranges),
        parse_references(document, ranges=ranges),
        start,
    )
