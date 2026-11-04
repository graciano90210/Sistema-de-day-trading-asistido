"""Genera reports/data_quality.md. Uso: uv run python .claude/skills/data-ingest/scripts/quality_report.py"""

import sys

from daytrader.cli import app

if __name__ == "__main__":
    sys.exit(app(["quality", *sys.argv[1:]]))
