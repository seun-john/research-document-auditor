from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Paragraph:
    index: int
    text: str
    style: str = ""


@dataclass(frozen=True)
class Heading:
    paragraph_index: int
    text: str
    level: int


@dataclass
class Document:
    source: Path
    paragraphs: list[Paragraph]
    headings: list[Heading]
    table_count: int = 0
    drawing_count: int = 0
    table_text: list[str] = field(default_factory=list)
    raw_word_count: int | None = None
    extraction_coverage: float = 1.0

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


@dataclass(frozen=True)
class Location:
    paragraph: int | None = None
    section: str | None = None


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    message: str
    location: Location = field(default_factory=Location)
    evidence: list[str] = field(default_factory=list)
    suggestion: str = ""
    confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceVerification:
    paragraph: int
    supplied: str
    status: str
    confidence: str
    source: str = ""
    matched_title: str = ""
    matched_authors: list[str] = field(default_factory=list)
    matched_year: int | None = None
    doi: str | None = None
    url: str | None = None
    evidence: list[str] = field(default_factory=list)
    retraction_status: str = "NOT_CHECKED_NO_DOI"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    source: str
    profile: str
    findings: list[Finding]
    stats: dict[str, Any]
    coverage: dict[str, str]
    reference_verifications: list[ReferenceVerification] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        counts = {severity: 0 for severity in ("high", "medium", "low", "info")}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return {
            "schema_version": "1.3",
            "source": self.source,
            "profile": self.profile,
            "summary": {"total": len(self.findings), "by_severity": counts},
            "stats": self.stats,
            "coverage": self.coverage,
            "reference_verification": {
                "enabled": bool(self.reference_verifications),
                "summary": dict(
                    sorted(
                        {
                            status: sum(1 for item in self.reference_verifications if item.status == status)
                            for status in {item.status for item in self.reference_verifications}
                        }.items()
                    )
                ),
                "retraction_summary": dict(
                    sorted(
                        {
                            status: sum(1 for item in self.reference_verifications if item.retraction_status == status)
                            for status in {item.retraction_status for item in self.reference_verifications}
                        }.items()
                    )
                ),
                "results": [item.to_dict() for item in self.reference_verifications],
            },
            "findings": [finding.to_dict() for finding in self.findings],
        }
