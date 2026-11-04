"""Etiquetado determinista de catalizadores a partir de titular + resumen (reglas, sin LLM).

El orden de LABELS es la prioridad: la etiqueta principal es la primera que coincide.
`analyst_pt` (mantiene rating y mueve precio objetivo) es ruido rutinario y va al final.
"""

from __future__ import annotations

import html
import re


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


_FIN = (
    r"(EPS|revenue|sales|income|profit|loss|margin|ARR|bookings|free cash flow|FCF|results|earnings|deliveries|"
    r"gain|charges?|impairment|includes)"
)

LABELS: list[tuple[str, re.Pattern]] = [
    ("offering", _rx(
        r"\b(public offering|(prices?|priced|pricing|announces|launches|proposed) .{0,30}offering|"
        r"offering of (common )?(stock|shares)|private placement|registered direct|"
        r"at[- ]the[- ]market|ATM (program|offering)|shelf registration|convertible (senior )?notes offering|"
        r"secondary offering|stock offering|share offering|dilutive offering|"
        r"(share|shareholder|stockholder|equity) dilution|dilution to (existing )?shareholders)\b"
        # no "diluted EPS" ni "margin dilution"
    )),
    ("m&a", _rx(
        r"\b(acquisition|acqui(re|res|red|ring)|merger|merge with|to buy|buyout|takeover|tender offer|"
        r"take[- ]private|go[- ]private|definitive agreement|bid for|to be acquired|stake in)\b"
    )),
    ("fda_clinical", _rx(
        r"\b(FDA|PDUFA|clinical|phase (1|2|3|I{1,3})|trial|topline|data readout|EMA|breakthrough therapy|"
        r"NDA|BLA|(drug|therapy|treatment|vaccine|device) (approv\w+|clearance))\b"
    )),
    ("earnings", _rx(
        rf"\b(earnings|EPS|quarterly results|(first|second|third|fourth)[- ]quarter|"
        rf"Q[1-4]( (FY)?20\d\d)?\b.{{0,40}}\b{_FIN}|reports? (results|revenue)|"
        rf"beats?|miss(es|ed)? (estimates|expectations))\b"
    )),
    ("guidance", _rx(
        r"\b(guidance|outlook|forecast|sees (Q[1-4]|FY|full[- ]year)|raises? (its )?(full[- ]year|FY|annual)|"
        r"lowers? (its )?(full[- ]year|FY|annual)|reaffirms?|affirms?|cuts? (its )?outlook)\b"
    )),
    ("analyst", _rx(
        r"\b(upgrades?|downgrades?|upgraded|downgraded|initiates? coverage|initiated (at|with)|"
        r"assumes coverage|resumes coverage)\b"
    )),
    ("contract", _rx(
        r"\b(contract|partnership|collaboration|agreement with|awarded|wins? .{0,30}order|"
        r"supply deal|licens(e|ing) (deal|agreement))\b"
    )),
    ("legal_regulatory", _rx(
        r"\b(lawsuit|sues|sued|investigation|probe|subpoena|DOJ|FTC|antitrust|SEC charges|recall|class action|"
        r"settle(s|d|ment)? (lawsuit|charges|claims|case|with (the )?(SEC|DOJ|FTC))|export (controls?|restrictions?))\b"
    )),
    ("management", _rx(
        r"\b(steps down|step down|resign(s|ed|ation)?|appoint(s|ed|ment)?|names? new|to succeed|"
        r"(CEO|CFO) (transition|departure|exit|succession))\b"
    )),
    ("analyst_pt", _rx(r"\b(price target|maintains (buy|sell|hold|neutral|overweight|underweight|outperform))\b")),
]  # fmt: skip
NO_CATALYST = "sin_catalizador"
MOVERS = "lista_movers"  # artículos-lista ("X, Y And Other Stocks Moving Premarket"): contexto, no catalizador
_MOVERS_RX = _rx(
    r"(stocks? (moving|to watch|making the biggest moves)|other (big )?stocks|movers|here are \d+ stocks|"
    r"why these \d+ stocks|stock market today|(top|biggest) (gainers|losers)|on investors' radars)"
)
PRIORITY = {name: i for i, (name, _) in enumerate(LABELS)} | {NO_CATALYST: len(LABELS), MOVERS: len(LABELS) + 1}


def clean(text: str | None) -> str:
    return html.unescape(text or "").strip()


def classify(headline: str | None, summary: str | None = None) -> tuple[str, list[str]]:
    """(etiqueta principal, todas las etiquetas). El titular manda; el resumen solo añade."""
    h, s = clean(headline), clean(summary)
    if _MOVERS_RX.search(h):
        return MOVERS, []
    in_headline = [n for n, p in LABELS if p.search(h)]
    in_summary = [n for n, p in LABELS if p.search(s) and n not in in_headline]
    found = in_headline + in_summary
    if not found:
        return NO_CATALYST, []
    primary = (in_headline or in_summary)[0]
    # Un titular de resultados trimestrales que menciona un deal/contrato es un detalle de los resultados
    # ("Q1 Includes Gain Tied To ... Acquisition Financing"), no un catalizador de M&A.
    group = in_headline or in_summary
    if "earnings" in group and primary in {"m&a", "contract", "fda_clinical", "legal_regulatory"}:
        primary = "earnings"
    return primary, found


_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|n\.?v|s\.?a|ag|se|"
    r"class [a-c]|common stock|ordinary shares|american depositary shares|ads|the)\b\.?",
    re.I,
)


def short_name(name: str | None) -> str:
    """'NVIDIA Corporation Common Stock' → 'NVIDIA'."""
    words = [w for w in _SUFFIXES.sub(" ", name or "").replace(",", " ").split() if len(w) >= 3]
    return words[0] if words else ""


def _mentions(text: str, symbol: str, company: str) -> bool:
    if re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", text):
        return True
    return bool(company) and re.search(rf"\b{re.escape(company)}", text, re.I) is not None


def is_relevant(
    symbol: str, company: str, headline: str, n_symbols: int, max_symbols: int, summary: str | None = None
) -> bool:
    """Noticia *sobre* la empresa: la nombra en titular o resumen.

    Sin mención, solo cuenta si es una nota de un único ticker sin resumen (típico de titulares
    cortos de Benzinga). Evita casos como 'Shield Therapeutics' etiquetada con el ticker de Seagate.
    """
    h, s = clean(headline), clean(summary)
    if _mentions(h, symbol, company) or _mentions(s, symbol, company):
        return True
    return n_symbols <= min(max_symbols, 1) and not s
