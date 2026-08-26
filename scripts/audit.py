#!/usr/bin/env python3
"""Run the bundled Research Document Auditor without installing the package."""

from pathlib import Path
import sys


SKILL_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SKILL_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from research_auditor.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

