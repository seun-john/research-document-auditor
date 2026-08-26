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


def bibliography_start(document: Document) -> int | None:
    candidates: list[tuple[int, int]] = []
    for paragraph in document.paragraphs:
        normalized = re.sub(r"[^a-z ]", "", paragraph.text.lower()).strip()
        if normalized in BIBLIOGRAPHY_HEADINGS:
            if re.search(r"\d\s*$", paragraph.text):
                continue
            following = [p.text for p in document.paragraphs if paragraph.index < p.index <= paragraph.index + 25]
            reference_like = sum(
                1
                for text in following
                if len(text) >= 20 and re.search(r"\b(?:19|20)\d{2}[a-z]?\b", text, re.I)
            )
            candidates.append((reference_like, paragraph.index))
    if not candidates:
        return None
    # TOC labels usually have no reference-like entries immediately after them.
    # Prefer the densest candidate, using the later one as the tie-breaker.
    return max(candidates)[1]


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


def parse_in_text_citations(document: Document, before: int | None) -> list[CitationOccurrence]:
    occurrences: list[CitationOccurrence] = []
    limit = before or 10**9
    for paragraph in document.paragraphs:
        if paragraph.index >= limit:
            continue
        text = paragraph.text
        # Parenthetical author-date groups: (Smith, 2020; Doe & Roe, 2021).
        for group in re.findall(r"\(([^()]*?(?:19|20)\d{2}[a-z]?[^()]*)\)", text):
            for part in re.split(r"\s*;\s*", group):
                match = re.search(r"(.+?)[, ]+((?:19|20)\d{2}[a-z]?)\b", part, re.I)
                if match:
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
            if author in {"classification", "figure", "table", "chapter", "section", "model", "method", "source", "version", "phase"}:
                continue
            key = CitationKey(author, match.group(2).lower())
            occurrences.append(CitationOccurrence(key, paragraph.index, match.group(0)))

    unique: dict[tuple[CitationKey, int], CitationOccurrence] = {}
    for occurrence in occurrences:
        unique[(occurrence.key, occurrence.paragraph)] = occurrence
    return list(unique.values())


def parse_references(document: Document, start: int | None) -> list[ReferenceEntry]:
    if start is None:
        return []
    entries: list[ReferenceEntry] = []
    paragraphs = [p for p in document.paragraphs if p.index > start]
    for paragraph in paragraphs:
        # A new level-1 heading after the bibliography closes the section.
        heading = next((h for h in document.headings if h.paragraph_index == paragraph.index), None)
        if heading and heading.level == 1:
            break
        raw = paragraph.text.strip()
        if len(raw) < 8:
            continue
        # Appendices are commonly formatted as ordinary paragraphs rather than
        # Word headings, so style metadata alone cannot close the bibliography.
        boundary = re.sub(r"[^a-z0-9 ]+", "", raw.casefold()).strip()
        if re.match(r"^(?:appendix|annex)(?:\s+[a-z0-9]+)?(?:\s+questionnaire)?$", boundary):
            break
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


def citation_data(document: Document) -> tuple[list[CitationOccurrence], list[ReferenceEntry], int | None]:
    start = bibliography_start(document)
    return parse_in_text_citations(document, start), parse_references(document, start), start
