"""Regla 1 (solo paper) y regla 4 (secretos fuera del código)."""

from __future__ import annotations

import re
import subprocess

import pytest

from daytrader.config import PAPER_TRADING_URL, ROOT, LiveTradingForbidden, assert_paper_url

CODE_DIRS = [ROOT / "src", ROOT / ".claude", ROOT / "config", ROOT / "cloud"]
CODE_EXT = {".py", ".yaml", ".yml", ".toml", ".md", ".json"}


def _code_files():
    for d in CODE_DIRS:
        if d.exists():
            yield from (p for p in d.rglob("*") if p.is_file() and p.suffix in CODE_EXT)


def test_paper_url_guard():
    assert assert_paper_url(PAPER_TRADING_URL + "/") == PAPER_TRADING_URL
    for bad in ("https://api.alpaca.markets", "https://paper-api.alpaca.markets.evil.com", ""):
        with pytest.raises(LiveTradingForbidden):
            assert_paper_url(bad)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(?<!paper-)api\.alpaca\.markets",  # endpoint de trading real
        r"paper\s*=\s*False",
        r"ALPACA_PAPER\s*=\s*false",
    ],
)
def test_no_live_trading_in_code(pattern):
    hits = [str(p.relative_to(ROOT)) for p in _code_files() if re.search(pattern, p.read_text(errors="ignore"), re.I)]
    assert not hits, f"Posible acceso a cuenta real ({pattern}) en: {hits}"


def test_no_trading_client_outside_executor():
    """TradingClient solo podrá vivir en el paper-executor (fase 5)."""
    allowed = {"src/daytrader/execution"}
    usage = re.compile(r"^\s*(from|import)\s[^\n]*(TradingClient|alpaca\.trading)|TradingClient\s*\(", re.M)
    hits = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if usage.search(p.read_text()) and not any(str(p.relative_to(ROOT)).startswith(a) for a in allowed)
    ]
    assert not hits, hits


def test_order_endpoints_only_in_executor():
    """Endpoints que mueven dinero (órdenes/posiciones) solo en el paper-executor (fase 5)."""
    pattern = re.compile(r"/v2/(orders|positions)")
    hits = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if pattern.search(p.read_text()) and not str(p.relative_to(ROOT)).startswith("src/daytrader/execution")
    ]
    assert not hits, hits


def test_no_hardcoded_keys():
    key_pattern = re.compile(r"\b(PK|AK|CK)[A-Z0-9]{16,}\b")
    hits = [str(p.relative_to(ROOT)) for p in _code_files() if key_pattern.search(p.read_text(errors="ignore"))]
    assert not hits, hits


def test_env_is_gitignored():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in lines
    if (ROOT / ".git").exists() and (ROOT / ".env").exists():
        r = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True)
        assert r.returncode == 0, ".env NO está ignorado por git"


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "KEY" in line:
            assert line.split("=", 1)[1].strip() == "", f"Valor en .env.example: {line.split('=')[0]}"
