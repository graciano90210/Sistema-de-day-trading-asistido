from datetime import datetime

import pytest

from daytrader.catalysts.labels import NO_CATALYST, classify, is_relevant, short_name
from daytrader.catalysts.news import catalyst_summary, ensure_news, news_for


@pytest.mark.parametrize(
    "headline,expected",
    [
        ("Acme Q3 EPS $1.20 Beats $1.05 Estimate, Sales $3.1B", "earnings"),
        ("Acme Raises FY25 Guidance After Strong Quarter", "guidance"),
        ("Acme Announces $200M Public Offering Of Common Stock", "offering"),
        ("Acme To Acquire Widget Co In $5B Deal", "m&a"),
        ("FDA Approves Acme's Drug For Rare Disease", "fda_clinical"),
        ("Morgan Stanley Upgrades Acme To Overweight, Raises Price Target", "analyst"),
        ("Acme Wins $1B Defense Contract", "contract"),
        ("DOJ Opens Antitrust Probe Into Acme", "legal_regulatory"),
        ("Acme CEO Steps Down", "management"),
        ("Stocks To Watch This Morning", "lista_movers"),
    ],
)
def test_classify(headline, expected):
    assert classify(headline)[0] == expected


def test_classify_unescapes_html_and_uses_summary():
    label, labels = classify("Acme shares jump", "Company &amp; partner sign licensing agreement")
    assert label == "contract" and labels == ["contract"]


def test_short_name_and_relevance():
    assert short_name("NVIDIA Corporation Common Stock") == "NVIDIA"
    assert short_name("Alphabet Inc. Class A Common Stock") == "Alphabet"
    assert is_relevant("NVDA", "NVIDIA", "Nvidia Tightens Export Rules", n_symbols=7, max_symbols=3)
    assert is_relevant("AMD", "Advanced", "AMD beats estimates", 5, 3)
    assert not is_relevant("MU", "Micron", "Cramer likes this industrial stock", 8, 3)
    assert is_relevant("MU", "Micron", "Cramer likes this stock", 8, 3, summary="He prefers Micron over WDC")
    assert is_relevant("MU", "Micron", "Short headline", 1, 3)  # nota de un solo ticker sin resumen
    # Caso real 2026-11-03: noticia de Shield Therapeutics (LSE: STX) etiquetada con el ticker de Seagate.
    assert not is_relevant(
        "STX", "Seagate", "Shield Therapeutics Reports Q3 2026 Trading Update", 1, 3,
        summary="Shield Therapeutics announced its Q3 2026 financial results",
    )  # fmt: skip


@pytest.mark.parametrize(
    "headline,expected",
    [  # titulares reales mal etiquetados en la primera corrida (2026-11-03)
        ("Reported Earlier, European Commission Conditionally Approves JD.com's Acquisition Of Ceconomy", "m&a"),
        ("Aehr Stock Surges As CEO Says AI Chip Complexity Is Accelerating Burn-In Demand", NO_CATALYST),
        ("Shopify Q3 Operating Income Up 66% To $568M", "earnings"),
        ("Sysco Q1 Free Cash Flow $230M Vs $(50)M YoY", "earnings"),
        ("Dynatrace Q2 ARR $2.21B, Up 16% YoY", "earnings"),
        ("Stock Market Today: Futures Mixed as Trump Touts Iran Settlement Hopes", "lista_movers"),
        ("Adeia Posts Downbeat Q3 Earnings, Joins Bioventus, Apple And Other Big Stocks Moving Lower", "lista_movers"),
        (
            "Why Aehr Test Systems Shares Are Trading Higher By Over 15%; Here Are 20 Stocks Moving Premarket",
            "lista_movers",
        ),
        ("Barclays Maintains Underweight on Apple, Raises Price Target to $261", "analyst_pt"),
        ("Backblaze Sees Q4 Sales $49.8M-$50.2M vs $46.988M Est", "earnings"),
        ("Dynatrace Q2 Adj. Diluted EPS $0.44 Beats $0.41 Estimate", "earnings"),
        ("Sysco Q1 Includes $234M Gain On Rate Locks Tied To Jetro Restaurant Depot Acquisition Financing", "earnings"),
        ("Acme Prices $300M Offering; Expects Dilution", "offering"),
        ("Dynatrace Lowers FY27 Adj. Operating Margin Guidance To 28%; Includes ~175 Bps Arize Dilution", "guidance"),
    ],
)
def test_classify_regressions(headline, expected):
    assert classify(headline)[0] == expected


def _item(i, created, symbols, headline):
    return {"id": i, "created_at": created, "updated_at": created, "headline": headline, "summary": "",
            "source": "benzinga", "url": "u", "symbols": symbols}  # fmt: skip


def test_news_point_in_time_and_cache(store):
    calls = []

    def fake(symbols, start, end):
        calls.append(tuple(symbols))
        return [
            _item(1, "2025-03-13T21:00:00Z", ["AAA"], "AAA Q4 EPS beats"),
            _item(2, "2025-03-14T13:20:00Z", ["AAA", "B", "C", "D", "E"], "Market movers"),
            _item(3, "2025-03-14T13:40:00Z", ["AAA"], "AAA To Acquire Foo"),  # después del cutoff 13:25 UTC
        ]

    start, cutoff = datetime(2025, 3, 13, 20, 0), datetime(2025, 3, 14, 13, 25)
    ensure_news(store, fake, ["AAA"], start, cutoff)
    ensure_news(store, fake, ["AAA"], start, cutoff)
    assert len(calls) == 1  # segunda vez desde caché
    news = news_for(store, ["AAA"], start, cutoff, {"AAA": "Alpha Inc"})
    assert news["id"].to_list() == [2, 1]  # la noticia 3 (13:40) no existe todavía a las 13:25
    assert news.filter(news["id"] == 2)["relevant"][0] is False
    cat = catalyst_summary(news).row(0, named=True)
    assert cat["catalyst"] == "earnings" and cat["n_news"] == 2 and cat["n_relevant"] == 1
