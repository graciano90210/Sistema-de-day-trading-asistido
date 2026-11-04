"""Watchlist de una sesión. Uso: uv run python .claude/skills/scanner/scripts/watchlist.py --date YYYY-MM-DD"""

import sys

from daytrader.cli import app

if __name__ == "__main__":
    sys.exit(app(["watchlist", *sys.argv[1:]]))
