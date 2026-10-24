from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .engine import audit_document
from .reporters import render_json, render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-audit",
        description="Audit a research manuscript for citation, structure, consistency, and disclosure issues.",
    )
    parser.add_argument("document", help="path to a .docx, .md, or .txt manuscript")
    parser.add_argument("--profile", choices=("auto", "thesis", "journal", "report"), default="auto")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", dest="output_format")
    parser.add_argument("--output", "-o", help="write the report to this file instead of stdout")
    parser.add_argument("--online-references", action="store_true", help="verify bibliography metadata using Crossref, DataCite, and DOI-linked OpenAlex records")
    parser.add_argument("--email", help="contact email for polite API pools (never inferred or invented)")
    parser.add_argument("--reference-cache", help="optional JSON cache for repeatable online metadata requests")
    parser.add_argument("--openalex-api-key", help="optional OpenAlex key for a larger free daily API budget")
    parser.add_argument("--online-workers", type=int, default=4, help="bounded concurrent reference lookups (default: 4)")
    parser.add_argument("--fail-on", choices=("none", "high", "medium", "low", "info"), default="high")
    parser.add_argument("--min-confidence", choices=("high", "medium", "low"), default="low", help="minimum confidence considered by --fail-on")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.online_workers < 1 or args.online_workers > 16:
        print("research-audit: error: --online-workers must be between 1 and 16", file=sys.stderr)
        return 2

    def progress(completed, total, entry):
        print(f"Checked reference {completed}/{total}: {entry.raw[:70]}", file=sys.stderr)

    try:
        report = audit_document(
            args.document,
            profile=args.profile,
            online_references=args.online_references,
            email=args.email,
            reference_cache=args.reference_cache,
            openalex_api_key=args.openalex_api_key,
            online_workers=args.online_workers,
            progress=progress if args.online_references else None,
        )
    except (OSError, ValueError) as exc:
        print(f"research-audit: error: {exc}", file=sys.stderr)
        return 2

    rendered = render_json(report) if args.output_format == "json" else render_markdown(report)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote audit report to {output}")
    else:
        print(rendered)

    if args.fail_on == "none":
        return 0
    ranks = {"high": 4, "medium": 3, "low": 2, "info": 1}
    confidence_ranks = {"high": 3, "medium": 2, "low": 1}
    threshold = ranks[args.fail_on]
    confidence_threshold = confidence_ranks[args.min_confidence]
    return 1 if any(
        ranks.get(finding.severity, 0) >= threshold
        and confidence_ranks.get(finding.confidence, 0) >= confidence_threshold
        for finding in report.findings
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
