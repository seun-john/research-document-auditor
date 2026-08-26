from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Document, Heading, Paragraph

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _heading_level(text: str, style: str) -> int | None:
    style_match = re.search(r"heading\s*([1-9])", style, re.I)
    if style_match:
        return int(style_match.group(1))
    chapter = re.match(r"^chapter\s+([0-9ivxlcdm]+)\b", text.strip(), re.I)
    if chapter:
        return 1
    numbered = re.match(r"^(\d+(?:\.\d+)*)\s+\S", text.strip())
    if numbered:
        return min(numbered.group(1).count(".") + 1, 9)
    return None


def _plain_document(path: Path) -> Document:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    paragraphs: list[Paragraph] = []
    headings: list[Heading] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        style = ""
        level = None
        md = re.match(r"^(#{1,6})\s+(.+)$", text)
        if md:
            level, text, style = len(md.group(1)), md.group(2).strip(), f"Heading {len(md.group(1))}"
        else:
            level = _heading_level(text, style)
        index = len(paragraphs) + 1
        paragraphs.append(Paragraph(index, text, style))
        if level:
            headings.append(Heading(index, text, level))
    return Document(path, paragraphs, headings)


def _docx_document(path: Path) -> Document:
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"Cannot read DOCX file: {exc}") from exc

    body = root.find(f"{W}body")
    if body is None:
        raise ValueError("DOCX has no document body")

    paragraphs: list[Paragraph] = []
    headings: list[Heading] = []
    table_text: list[str] = []
    table_count = 0

    for child in body:
        if child.tag == f"{W}p":
            text = "".join(node.text or "" for node in child.iter(f"{W}t")).strip()
            if not text:
                continue
            style_node = child.find(f"{W}pPr/{W}pStyle")
            style = style_node.get(f"{W}val", "") if style_node is not None else ""
            index = len(paragraphs) + 1
            paragraphs.append(Paragraph(index, text, style))
            level = _heading_level(text, style)
            if level:
                headings.append(Heading(index, text, level))
        elif child.tag == f"{W}tbl":
            table_count += 1
            cells: list[str] = []
            for cell in child.iter(f"{W}tc"):
                value = " ".join(
                    "".join(n.text or "" for n in paragraph.iter(f"{W}t")).strip()
                    for paragraph in cell.iter(f"{W}p")
                ).strip()
                if value:
                    cells.append(value)
            table_text.append(" | ".join(cells))

    drawing_count = len(root.findall(f".//{W}drawing"))
    return Document(path, paragraphs, headings, table_count, drawing_count, table_text)


def load_document(filename: str | Path) -> Document:
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Document not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx_document(path)
    if suffix in {".txt", ".md"}:
        return _plain_document(path)
    raise ValueError("Supported input formats are .docx, .md, and .txt")

