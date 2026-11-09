# Guardián en la nube (Heroku Scheduler)

Cierra TODAS las posiciones de la cuenta **paper** ~10 min antes del cierre, aunque el portátil esté apagado.
Autorización permanente del usuario (2026-11-09). Solo cierra; nunca abre posiciones.

## Instalación (una vez)
```bash
heroku login
heroku create daytrader-guard-<algo>           # nombre único
heroku git:remote -a daytrader-guard-<algo>
heroku buildpacks:set heroku/python
heroku config:set ALPACA_API_KEY=<KEY PAPER> ALPACA_SECRET_KEY=<SECRET PAPER> DAYTRADER_AUTO_FLATTEN=1
git subtree push --prefix cloud heroku main    # sube SOLO esta carpeta
heroku addons:create scheduler:standard
heroku addons:open scheduler                   # Add Job → "Every 10 minutes" → python flatten_job.py
heroku run python flatten_job.py               # prueba: debe decir "fuera de ventana" o "sin posiciones"
```
Requiere un plan de dynos (Eco ≈ US$5/mes) para los one-off dynos del Scheduler.

## Operación
- Logs: `heroku logs --tail --source app`
- Apagar: `heroku config:set DAYTRADER_AUTO_FLATTEN=0` · Encender: `=1`
- Actualizar el código: `git subtree push --prefix cloud heroku main`
- Tras el cierre, en el portátil: `uv run daytrader sync` (trae las salidas al journal).
