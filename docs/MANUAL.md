# Manual de instrucciones — Sistema de day trading asistido

Versión 1.0 · noviembre de 2026 · fases 1 a 6 completas.

---

## 1. Qué es este sistema (y qué no es)

Es un **laboratorio de investigación y una herramienta de paper trading** para acciones de EE. UU.:

- descarga y guarda datos de mercado de 1 minuto y diarios, sin errores de "mirar el futuro" (*lookahead*);
- busca cada mañana las acciones con gap y su noticia (scanner + catalizadores);
- prueba estrategias con costos realistas y validación estricta (backtester);
- te deja **operar en la cuenta PAPER de Alpaca** con control de riesgo y confirmación obligatoria (y/n);
- registra cada operación en un journal y la muestra en un dashboard.

**Lo que NO es:**

- **No opera dinero real.** No existe ningún camino en el código hacia una cuenta real; hay tests que lo vigilan.
- **No es un sistema automático que gane dinero.** La investigación (fase 3) probó 25 configuraciones
  pre-registradas de estrategias intradía y **ninguna mostró ventaja después de costos** (ver §9).
  El sistema no te va a dar "señales para hacerte rico": te da herramientas para medir con honestidad.
- **No es consejo financiero.**

---

## 2. Instalación (una sola vez)

### 2.1 Requisitos
- Linux (probado en Pop!_OS), 8 GB de RAM como mínimo (16 GB recomendado), ~5 GB de disco libre.
- [uv](https://docs.astral.sh/uv/) y Python 3.12 (uv lo instala si falta).
- Una cuenta **paper** de Alpaca (gratis) — https://app.alpaca.markets/signup

### 2.2 Descargar el proyecto
```bash
git clone https://github.com/graciano90210/Sistema-de-day-trading-asistido.git
cd Sistema-de-day-trading-asistido
uv sync                 # instala todas las dependencias en .venv
uv run pytest           # deben pasar todos los tests (no necesitan internet ni keys)
```

### 2.3 Configurar las claves (`.env`)
1. En Alpaca, cambia a la cuenta **Paper** (arriba a la izquierda) → panel **API Keys** → **Generate New Keys**.
   La *Key ID* de paper empieza por **`PK`**. Si empieza por `AK`, es de la cuenta real: **bórrala y no la uses**.
2. Crea el archivo de configuración y pega tus datos:
   ```bash
   cp .env.example .env
   nano .env
   ```
   ```
   ALPACA_API_KEY=PKxxxxxxxxxxxxxxxx
   ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
   SEC_USER_AGENT=DaytraderResearch tu@email.com
   ```
   `SEC_USER_AGENT` lo exige la SEC para consultar acciones en circulación; tu email solo se envía a sec.gov.
3. `.env` está en `.gitignore`: **nunca se sube a GitHub**. No pegues tus claves en chats ni en capturas.

### 2.4 Primera carga de datos (~1–4 horas en total, en segundo plano)
```bash
uv run daytrader ingest        # 2 años de barras de 1 min de 50 tickers + diarias (~20–30 min)
uv run daytrader universe      # lista de acciones, splits y barras diarias de ~5.900 acciones (~5–10 min)
uv run daytrader quality       # reporte de calidad → reports/data_quality.md
uv run daytrader info          # estado de la base de datos
```
Las descargas son **incrementales y reanudables**: si se cortan, vuelve a ejecutar el mismo comando.
Solo hacen falta `backfill` y `opening` si vas a repetir la investigación (§9).

---

## 3. Reglas de seguridad (no negociables)

1. **Solo paper.** El ejecutor usa siempre `https://paper-api.alpaca.markets`; si detecta otra URL se detiene
   con `LiveTradingForbidden`.
2. **Ninguna orden sin tu "y".** El sistema te muestra el ticket y pregunta; cualquier otra respuesta,
   o no responder en 60 s, cancela.
3. **Los números los calcula Python**, nunca "a ojo" (tampoco Claude).
4. **Claves solo en `.env`.**
5. **Cero lookahead:** toda decisión usa solo datos disponibles en ese momento (hay tests que lo verifican).
6. **La cuenta real de Alpaca no se conecta al proyecto.** No generes claves `AK` "por si acaso".

---

## 4. Horarios

| Evento | Hora Nueva York (ET) | Colombia | Brasil (São Paulo) |
|---|---|---|---|
| Pre-market | 04:00 | 04:00* | 06:00* |
| Scanner (cutoff) | 09:25 | 09:25* | 11:25* |
| Apertura | 09:30 | 09:30* | 11:30* |
| Última entrada permitida | 15:45 | 15:45* | 17:45* |
| Cierre forzado | 15:50 | 15:50* | 17:50* |
| Cierre del mercado | 16:00 | 16:00* | 18:00* |

\* Válido de noviembre a marzo (EE. UU. en horario de invierno). De marzo a noviembre EE. UU. adelanta una hora:
la apertura pasa a las **08:30 en Colombia** y a las **10:30 en Brasil**. El sistema trabaja internamente en UTC y
maneja estos cambios solo.

---

## 5. Rutina diaria de paper trading


### 5.0 Automatización (opcional, recomendada)
```bash
scripts/auto/install_timers.sh               # instala los temporizadores de tu usuario
scripts/auto/install_timers.sh --uninstall   # los quita
systemctl --user list-timers 'daytrader-*'   # próximas ejecuciones
```
- **Lun–vie 20:30 ET**: `ingest` + `universe` (datos al día). **Lun–vie 09:40 ET**: `watchlist` del día.
- En festivos no hacen nada; si el PC estaba apagado, se ejecutan al encenderlo. Logs en `reports/auto/`.
- Funcionan mientras tu sesión de usuario esté iniciada (portátil encendido y con sesión abierta).

### 5.1 Noche anterior (o temprano en la mañana) — si no usas la automatización
```bash
uv run daytrader ingest        # actualiza barras 1 min de los 50 tickers
uv run daytrader universe      # actualiza barras diarias del mercado (necesarias para el scanner)
```

### 5.2 Antes de la apertura: la watchlist
```bash
uv run daytrader watchlist --date 2026-11-05     # → reports/watchlist_2026-11-05.md
```
Lista los gappers del día (gap, volumen relativo, ATR, liquidez, acciones en circulación) con sus noticias y la
etiqueta del catalizador.

> **Limitación del plan gratuito de Alpaca:** los datos SIP de los **últimos 15 minutos** no están disponibles.
> Para el scan de las 09:25 ET, ejecútalo a partir de las **09:40 ET**; los datos usados siguen siendo los de
> hasta las 09:25 (sin lookahead). Para tenerlo a las 09:25 exactas haría falta el plan de datos de pago.

### 5.3 Al empezar la sesión: el guardián
En una terminal aparte:
```bash
uv run daytrader guard
```
Te pregunta si **autorizas el cierre automático de todas las posiciones a las 15:50 ET**. Si respondes `y`,
a esa hora cancela órdenes y cierra todo, y después sincroniza el journal. Déjalo corriendo.

### 5.3b A mediodía: elegir candidato y dirección (práctica)
```bash
uv run daytrader mediodia            # resumen de los 3 mejores candidatos de la watchlist → tú eliges uno
uv run daytrader contexto APP        # VWAP, rangos, mercado, lecturas, stops candidatos y PATRONES de hoy
```
`contexto` muestra además si hoy se confirmó una **bandera (P1)** o un **doble suelo/techo (P2)** con el mismo
código del backtest de la ronda 4: entrada (orden stop), stop, objetivo y hasta qué hora vale la orden.
**Son material de práctica: en 2017–2025 no tuvieron edge** (R neto −0,06 y −0,02 por trade). Tú decides
la dirección y, si operas, lo haces con `trade` (§5.4) usando el stop y el objetivo que muestra.

### 5.3c Lista de momentum (swing, observación)
```bash
uv run daytrader momentum            # top 10 por momentum 12−1 de las 500 más líquidas + filtro SPY/SMA200
```
Es la hipótesis S1 de la fase 8 (exceso de +1 %/año sobre SPY en validación, **no significativo**, drawdown −40 %).
Sirve para observar y aprender; no pases estas posiciones por `trade`: el guardián cierra todo a las 15:50.

### 5.4 Proponer una operación
```bash
uv run daytrader trade NVDA largo --stop 182.50 --objetivo 190 --setup ORB --catalizador earnings
uv run daytrader trade TSLA corto --stop 251.00 --objetivo 240 --setup "VWAP" --notas "rechazo en VWAP"
uv run daytrader trade AMD largo --stop 158.00 --limite 160.20          # entrada con orden límite
```
| Parámetro | Obligatorio | Significado |
|---|---|---|
| `SYMBOL` | sí | Ticker |
| `largo` / `corto` | sí | Dirección |
| `--stop` | **sí** | Precio del stop de pérdida |
| `--objetivo` | no | Precio objetivo (si no, sale por stop o por el cierre forzado) |
| `--limite` | no | Entrar con orden límite a ese precio (si no, a mercado) |
| `--setup`, `--catalizador`, `--notas` | no | Contexto que se guarda en el journal |

**Qué hace el sistema:**
1. Toma la cotización actual (IEX, tiempo real).
2. Calcula el **tamaño**: acciones tales que, si salta el stop, pierdes el **1% del capital**.
3. Aplica las reglas de riesgo (§6). Si alguna falla, **rechaza** y te dice por qué (no pregunta nada).
4. Te muestra el **ticket** (operación, entrada, stop, objetivo, riesgo en $, recompensa/riesgo) y pregunta
   `¿Enviar esta orden a la cuenta PAPER? (y/n)`.
5. Si respondes `y`: vuelve a cotizar; si el precio se movió más de **0,25 R**, cancela (no persigue precios).
6. Envía una **orden bracket** (entrada + stop + objetivo juntos) a Alpaca paper y la registra en el journal.

### 5.5 Durante la sesión
```bash
uv run daytrader positions     # capital, PnL del día, trades usados, posiciones abiertas
uv run daytrader flatten       # cerrar TODO ahora (pide y/n)
```
El panel web de Alpaca (cuenta Paper) también muestra órdenes y posiciones. **No operes a mano en la misma cuenta
paper** mientras uses el sistema: desajusta los contadores de riesgo.

### 5.6 Después del cierre
```bash
uv run daytrader sync                                   # trae precios reales de ejecución al journal
uv run daytrader journal --days 30                      # métricas: win rate, R medio, PF, slippage real
uv run daytrader note <huella> "entré tarde, perseguí el precio" --error
uv run daytrader dashboard                              # ver todo en el navegador
```
La **huella** (*fingerprint*) de cada ticket aparece en el ticket y en `daytrader journal`.

---

## 6. Reglas de riesgo (`config/risk.yaml`)

| Regla | Valor por defecto |
|---|---|
| Riesgo por operación | 1% del capital |
| Kill switch diario | sin nuevas entradas si el PnL del día (realizado + flotante) ≤ −3% |
| Máximo de operaciones por día | 5 |
| Máximo de posiciones abiertas | 3 |
| Poder de compra | nocional total ≤ 4× capital |
| Distancia del stop | entre 0,2% y 10% del precio |
| Sin entradas | en los últimos 15 min de la sesión (respeta medias sesiones) |
| Cierre forzado | 15:50 ET (con tu autorización vía `guard`) |
| Confirmación | caduca a los 60 s |
| Deriva de precio | se cancela si el precio se movió > 0,25 R antes de enviar |

Puedes ajustar los valores editando el archivo; después corre `uv run pytest tests/test_execution.py`.
**Nunca relajes una regla para que pase una orden concreta.**

---

## 7. Cómo leer el dashboard

```bash
uv run daytrader dashboard     # http://localhost:8501
```
- **Mi operativa (paper):** tus operaciones cerradas. Lo más importante es el **R medio con su intervalo de
  confianza (IC 95%)**. Con menos de ~100 operaciones el dashboard te avisa que aún no es concluyente.
  Si el IC queda entero por debajo de cero, hay evidencia de que estás perdiendo de forma sistemática.
- **Slippage real:** cuánto peor que la cotización entraste, en R. Si es mayor que lo que modela el backtester
  (~0,01–0,04 R por lado), los backtests eran optimistas.
- **Investigación (backtests):** las 14 configuraciones guardadas de las rondas 1–3, con su curva frente a SPY.
- **Cómo leer esto:** glosario.

**Glosario rápido**
- **R:** resultado en unidades de riesgo. 1 R = lo que pierdes si salta el stop. +2 R = ganaste el doble de lo arriesgado.
- **R medio / expectancy:** promedio por operación. Si es negativo, operar más pierde más rápido.
- **Profit factor:** ganancias totales / pérdidas totales. > 1 gana.
- **Drawdown:** caída desde el máximo anterior del capital.
- **Win rate:** % de operaciones ganadoras (por sí solo no dice nada: importa junto al tamaño de ganancias y pérdidas).

---

## 8. Configuración (`config/`)

| Archivo | Qué controla |
|---|---|
| `settings.yaml` | Ruta de la base de datos, feed (SIP), fechas de historia, límites de la API |
| `universe.yaml` | Los 50 tickers con barras de 1 min (control) |
| `scanner.yaml` | Filtros del scanner: precio, liquidez, ATR, gap mínimo, volumen relativo, top N, hora del scan |
| `strategies.yaml` | Parámetros de cada estrategia (rondas 1–3; las de rondas 2–3 **no se modifican**: están pre-registradas) |
| `backtest.yaml` | Capital, reglas de cartera, costos calibrados, escenarios de costos, **inicio del OOS sellado** |
| `risk.yaml` | Reglas del risk-manager (§6) |

---

## 9. Investigación: resultados y cómo continuar sin engañarse

### 9.1 Qué se hizo
| Ronda | Qué se probó | Mejor resultado neto |
|---|---|---|
| 1 | ORB 5/15 min y reversión a VWAP, en gappers y en 50 líquidos | −0,06 R |
| 2 | ORB en *stocks in play* (réplica de Zarattini, Barbon y Aziz 2024), filtro de régimen HMM, meta-labeling LightGBM | −0,04 R |
| 3 | VWAP con órdenes límite y ajuste walk-forward (12 configuraciones) | −0,05 R (walk-forward) |
| 4 | Bandera, doble suelo/techo, VWAP, HMM y LightGBM con 10 años (2017–2025, universo sin sesgo de supervivencia) | −0,02 R (doble suelo) |
| 8 | Swing diario: momentum 12−1, reversión semanal, deriva tras shock de volumen, RSI(2) | momentum +1 %/año vs SPY (no significativo) |

- **Sin ningún costo**, ninguna configuración tiene un R medio distinto de cero → las señales no predicen.
- El paper de *stocks in play* solo se reproduce con ejecución perfecta y gratuita; con ejecución realista
  (calibrada con ticks reales) pierde ~1,3 R por operación.
- Los reportes están en `reports/` y los pre-registros en `docs/preregistro_ronda*.md`.

### 9.2 Garantías metodológicas
- **Point-in-time**: cada barra tiene `available_at`; las estrategias son funciones invariantes a prefijos (tests).
- **Ejecución conservadora**: entrada en la barra siguiente, stops con gaps, objetivos solo si se superan.
- **Costos calibrados** contra cotizaciones NBBO reales; **ejecución intrabarra calibrada** con trades tick.
- **Muestra fuera de muestra (OOS) 2026 sellada**: el backtester se niega a evaluarla sin `--unseal-oos`.
- **Pre-registro** (commit con fecha antes de ver resultados) y **Deflated Sharpe** según el número de intentos.

### 9.3 Si quieres probar una idea nueva
1. Escribe un pre-registro en `docs/` (hipótesis, parámetros, regla de decisión) y haz commit **antes** de correrla.
2. Añade la variante en `config/strategies.yaml` (sin tocar las existentes).
3. Corre solo en el periodo de desarrollo: `uv run daytrader backtest --strategies <nombre> --universes gappers`.
4. Suma el intento al conteo para el Deflated Sharpe (hoy N = 34).
5. Solo si pasa la regla de promoción, se evalúa **una vez** en el OOS 2026.

---

## 10. Trabajar con Claude Code

El proyecto incluye *skills* en `.claude/skills/` (data-ingest, scanner, catalysts, strategies, backtester,
risk-manager, paper-executor, journal, dashboard). Ejemplos de lo que puedes pedir:

- "Muéstrame la watchlist de hoy y explícame los catalizadores."
- "Analiza mis trades de las últimas dos semanas: ¿dónde estoy perdiendo?"
- "¿Por qué se rechazó mi orden de NVDA?"
- "Quiero probar esta idea: … — ayúdame a pre-registrarla."

Desde el celular: en la terminal ejecuta `claude`, luego `/remote-control`, y abre la sesión en la app Claude
(pestaña **Code**). Claude **nunca** responde la "y" de una orden por ti.

---

## 11. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY` | No existe `.env` o está vacío | §2.3 |
| `LiveTradingForbidden` | Algo apunta a una URL que no es paper | Detente y revisa; no lo "arregles" desactivando el control |
| `Could not set lock on file … market.duckdb` | Otro proceso está escribiendo en la base | Espera a que termine (DuckDB permite un solo escritor) |
| Error 403 / "subscription does not permit querying recent SIP data" | Datos SIP de los últimos 15 min (plan gratuito) | Ejecuta el comando 15 min más tarde (§5.2) |
| `Resultado: RECHAZADO …` | Una regla de riesgo no se cumple | Lee el motivo; ajusta stop/tamaño o espera al día siguiente |
| `Resultado: DERIVA` | El precio se movió > 0,25 R mientras confirmabas | Vuelve a proponer con precios actuales |
| Cotización con `ask 0.00` | Fuera de horario IEX no publica ambos lados | Normal fuera de sesión |
| El PC va lento durante descargas | Poca RAM (8 GB) | Cierra pestañas; se recomienda ampliar a 16–32 GB |
| El dashboard no abre | Puerto ocupado | `uv run daytrader dashboard --port 8502` |
| Tests fallan tras editar YAML | Un valor inválido | Revisa el cambio; `uv run pytest -x` muestra el primero |

---

## 12. Mapa del código

```
src/daytrader/
  config.py              claves (.env), YAML y guard de paper (assert_paper_url)
  market_calendar.py     sesiones NYSE, festivos, medias sesiones, pre/rth/post
  data/                  descarga Alpaca, DuckDB, calidad, acceso point-in-time, splits, SEC
  scanner/               universo, pre-market, gappers, histórico, stocks in play
  catalysts/             noticias y etiquetas de catalizador
  strategies/            ORB, ORB con orden stop, VWAP, VWAP con orden límite
  backtest/              motor, costos, cartera, métricas, calibración con NBBO/ticks, reportes
  research/              rondas 2 y 3, régimen HMM, meta-labeling
  execution/             risk-manager, broker PAPER, ejecutor y/n, journal, sincronización
  dashboard/             datos y app Streamlit
tests/                   seguridad, lookahead, calendario, scanner, estrategias, backtest, ejecución, dashboard
docs/                    pre-registros y este manual
reports/                 calidad de datos, watchlists, backtests, rondas
```
