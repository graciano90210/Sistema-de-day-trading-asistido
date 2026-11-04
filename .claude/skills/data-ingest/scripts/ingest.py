"""Descarga/actualiza barras. Uso: uv run python .claude/skills/data-ingest/scripts/ingest.py [--help]"""

import sys

from daytrader.cli import app

if __name__ == "__main__":
    sys.exit(app(["ingest", *sys.argv[1:]]))
