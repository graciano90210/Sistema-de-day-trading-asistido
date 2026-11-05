"""Backtest in-sample. Uso: uv run python .claude/skills/backtester/scripts/backtest.py [--help]"""

import sys

from daytrader.cli import app

if __name__ == "__main__":
    sys.exit(app(["backtest", *sys.argv[1:]]))
