---
name: catalysts
description: Noticias por ticker (Benzinga vía Alpaca News API) con etiqueta de catalizador determinista (earnings, guidance, FDA, M&A, offering, analyst, contract, legal, management) y filtro de relevancia, siempre point-in-time. Úsala para explicar por qué se mueve un ticker en una fecha, o al revisar la watchlist.
---

# catalysts

Wrapper sobre `src/daytrader/catalysts/`. Las etiquetas salen de reglas en `labels.py` (sin LLM).
Claude lee titulares/resúmenes y aporta la interpretación cualitativa.

## Uso
Las noticias se descargan y etiquetan automáticamente con la watchlist:
```bash
uv run python .claude/skills/scanner/scripts/watchlist.py --date 2026-11-03
```
Para un ticker suelto, desde Python:
```python
from daytrader.catalysts.news import ensure_news, news_for
```

## Reglas
- Solo noticias con `created_at <= as_of` (el cutoff del scan). `updated_at` posterior se ignora.
- Ventana por defecto: desde el cierre (16:00 ET) de la sesión anterior hasta el cutoff.
- Relevante = el ticker o el nombre corto de la empresa aparece en el titular, o la noticia etiqueta ≤ 3 tickers.
- Prioridad de etiquetas: offering > m&a > fda_clinical > earnings > guidance > analyst > contract > legal > management.

## Al interpretar
- Las reglas fallan con titulares ambiguos: revisar el titular antes de dar por buena la etiqueta.
- Varias noticias de "movers" con muchos tickers no son catalizador propio.
