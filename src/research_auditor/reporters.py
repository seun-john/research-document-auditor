from __future__ import annotations

import json
from typing import Any

from .models import AuditReport


def render_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def render_markdown(report: AuditReport) -> str:
    data = report.to_dict()
    counts = data["summary"]["by_severity"]
    lines = [
        "# Research Document Audit",
        "",
        f"**Document:** `{report.source}`  ",
        f"**Profile:** {report.profile}  ",
        f"**Findings:** {data['summary']['total']} total — {counts['high']} high, {counts['medium']} medium, {counts['low']} low, {counts['info']} info",
        "",
        "## Executive summary",
        "",
    ]
    if not report.findings:
        lines.append("No findings were produced by the enabled checks. This is not a guarantee that the manuscript is error-free.")
    else:
        for severity in ("high", "medium", "low", "info"):
            count = counts.get(severity, 0)
            if count:
                lines.append(f"- **{severity.title()}:** {count}")

    lines.extend(["", "## Findings", ""])
    for index, finding in enumerate(report.findings, 1):
        location = []
        if finding.location.section:
            location.append(finding.location.section)
        if finding.location.paragraph:
            location.append(f"paragraph {finding.location.paragraph}")
        where = f" ({', '.join(location)})" if location else ""
        lines.extend(
            [
                f"### {index}. [{finding.severity.upper()}] {finding.title}",
                "",
                f"`{finding.code}` · confidence: {finding.confidence}{where}",
                "",
                finding.message,
            ]
        )
        if finding.evidence:
            lines.extend(["", "Evidence:"])
            lines.extend(f"- {item}" for item in finding.evidence)
        if finding.suggestion:
            lines.extend(["", f"**Recommended action:** {finding.suggestion}"])
        lines.append("")

    if report.reference_verifications:
        reference_summary = data["reference_verification"]["summary"]
        lines.extend(["## Online reference verification", ""])
        lines.append(
            ", ".join(f"{count} {status.lower().replace('_', ' ')}" for status, count in reference_summary.items())
        )
        retraction_summary = data["reference_verification"]["retraction_summary"]
        lines.append(
            "Retraction checks: "
            + ", ".join(f"{count} {status.lower().replace('_', ' ')}" for status, count in retraction_summary.items())
        )
        lines.extend(["", "| Status | Retraction | Supplied reference | Best metadata match | Source |", "|---|---|---|---|---|"])
        for item in report.reference_verifications:
            supplied = item.supplied.replace("|", "\\|").replace("\n", " ")
            matched = item.matched_title.replace("|", "\\|") if item.matched_title else "—"
            if len(supplied) > 120:
                supplied = supplied[:117] + "..."
            if item.url and matched != "—":
                matched = f"[{matched}]({item.url})"
            lines.append(f"| {item.status} | {item.retraction_status} | {supplied} | {matched} | {item.source or '—'} |")
        lines.append("")

    lines.extend(["## Coverage and limits", ""])
    for check, status in report.coverage.items():
        lines.append(f"- **{check.replace('_', ' ').title()}:** {status}")
    lines.extend(["", "## Document statistics", ""])
    for key, value in report.stats.items():
        if key != "finding_codes":
            lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")
    lines.extend(
        [
            "",
            "> This report is a screening aid. Low-confidence heuristics require human review, and a source not found during an online check is not automatically fabricated.",
            "",
        ]
    )
    return "\n".join(lines)
