"""Journal de operaciones en DuckDB propio (data/journal.duckdb), separado de los datos de mercado."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl

from daytrader.execution.risk import OrderTicket, ticket_dict

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    fingerprint VARCHAR PRIMARY KEY, created_at TIMESTAMP, session_date DATE, symbol VARCHAR, side VARCHAR,
    qty INTEGER, entry_type VARCHAR, ref_price DOUBLE, limit_price DOUBLE, stop_price DOUBLE, target_price DOUBLE,
    risk_usd DOUBLE, setup VARCHAR, catalyst VARCHAR, notes VARCHAR,
    status VARCHAR,            -- rechazado | declinado | caducado | deriva | enviado | error
    reasons VARCHAR, decided_at TIMESTAMP, order_id VARCHAR, client_order_id VARCHAR
);
CREATE TABLE IF NOT EXISTS trades (
    fingerprint VARCHAR PRIMARY KEY, session_date DATE, symbol VARCHAR, side VARCHAR, qty DOUBLE,
    entry_ts TIMESTAMP, entry_px DOUBLE, exit_ts TIMESTAMP, exit_px DOUBLE, exit_reason VARCHAR,
    pnl DOUBLE, r_multiple DOUBLE, entry_slippage DOUBLE, entry_slippage_r DOUBLE, synced_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notes (
    fingerprint VARCHAR, ts TIMESTAMP, kind VARCHAR, text VARCHAR   -- kind: nota | error
);
CREATE TABLE IF NOT EXISTS events (ts TIMESTAMP, kind VARCHAR, detail VARCHAR);
"""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Journal:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(SCHEMA)

    def record_ticket(self, t: OrderTicket, status: str, reasons: list[str] | None = None,
                      order_id: str | None = None, client_order_id: str | None = None) -> None:  # fmt: skip
        d = ticket_dict(t)
        row = {
            "fingerprint": d["fingerprint"], "created_at": t.created_at, "session_date": t.created_at.date(),
            "symbol": t.symbol, "side": t.side, "qty": t.qty, "entry_type": t.entry_type, "ref_price": t.ref_price,
            "limit_price": t.limit_price, "stop_price": t.stop_price, "target_price": t.target_price,
            "risk_usd": t.risk_usd, "setup": t.setup, "catalyst": t.catalyst, "notes": t.notes, "status": status,
            "reasons": "; ".join(reasons or []), "decided_at": _now(), "order_id": order_id,
            "client_order_id": client_order_id,
        }  # fmt: skip
        df = pl.DataFrame([row], schema_overrides={"limit_price": pl.Float64, "target_price": pl.Float64,
                                                   "order_id": pl.Utf8, "client_order_id": pl.Utf8})  # fmt: skip
        self.con.register("_t", df)
        self.con.execute("INSERT OR REPLACE INTO tickets BY NAME SELECT * FROM _t")
        self.con.unregister("_t")

    def event(self, kind: str, detail: str) -> None:
        self.con.execute("INSERT INTO events VALUES (?, ?, ?)", [_now(), kind, detail])

    def note(self, fingerprint: str, text: str, kind: str = "nota") -> None:
        if kind not in ("nota", "error"):
            raise ValueError("kind debe ser 'nota' o 'error'")
        self.con.execute("INSERT INTO notes VALUES (?, ?, ?, ?)", [fingerprint, _now(), kind, text])

    def trades_today(self, day) -> int:
        return self.con.execute(
            "SELECT count(*) FROM tickets WHERE session_date = ? AND status = 'enviado'", [day]
        ).fetchall()[0][0]

    def upsert_trade(self, row: dict) -> None:
        df = pl.DataFrame([{**row, "synced_at": _now()}])
        self.con.register("_r", df)
        self.con.execute("INSERT OR REPLACE INTO trades BY NAME SELECT * FROM _r")
        self.con.unregister("_r")

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        return self.con.sql(sql, params=params or None).pl()

    def close(self) -> None:
        self.con.close()
