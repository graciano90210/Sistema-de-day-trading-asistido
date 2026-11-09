"""Broker PAPER de Alpaca. Único módulo del proyecto que importa TradingClient (regla 1, ver test_safety).

- Siempre paper=True y verificación de la URL con assert_paper_url: si no es paper, LiveTradingForbidden.
- No decide nada: solo envía tickets que el ejecutor ya validó (huella) y el usuario confirmó (y/n).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from daytrader.config import assert_paper_url
from daytrader.execution.risk import AccountState, OrderTicket

log = logging.getLogger(__name__)


def _r2(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


class PaperBroker:
    def __init__(self, api_key: str, secret_key: str):
        self.client = TradingClient(api_key, secret_key, paper=True)
        base = self.client._base_url
        assert_paper_url(str(getattr(base, "value", base)))  # defensa en profundidad: aborta si no es paper
        self.data = StockHistoricalDataClient(api_key, secret_key)

    # ---------------------------------------------------------------- lectura
    def account_state(self, trades_today: int) -> AccountState:
        a = self.client.get_account()
        pos = self.client.get_all_positions()
        return AccountState(
            equity=float(a.equity), last_equity=float(a.last_equity), open_positions=len(pos),
            open_notional=sum(abs(float(p.market_value)) for p in pos), trades_today=trades_today,
        )  # fmt: skip

    def quote(self, symbol: str) -> dict:
        """Última cotización en tiempo real (feed IEX: el plan gratuito no da SIP en tiempo real)."""
        q = self.data.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))[
            symbol
        ]
        bid, ask = float(q.bid_price or 0), float(q.ask_price or 0)
        mid = (bid + ask) / 2 if bid and ask else (ask or bid)
        return {"bid": bid, "ask": ask, "mid": mid, "ts": q.timestamp}

    def positions(self) -> list[dict]:
        return [
            {"symbol": p.symbol, "qty": float(p.qty), "side": str(p.side), "avg_entry": float(p.avg_entry_price),
             "market_value": float(p.market_value), "unrealized_pl": float(p.unrealized_pl)}
            for p in self.client.get_all_positions()
        ]  # fmt: skip

    def orders_since(self, day: date) -> list:
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=datetime.combine(day, time(0), tzinfo=UTC),
                               nested=True, limit=500)  # fmt: skip
        return self.client.get_orders(req)

    # ---------------------------------------------------------------- escritura (solo tras confirmación)
    def submit(self, t: OrderTicket, client_order_id: str):
        side = OrderSide.BUY if t.side == "long" else OrderSide.SELL
        common = {
            "symbol": t.symbol, "qty": t.qty, "side": side, "time_in_force": TimeInForce.DAY,
            "client_order_id": client_order_id, "stop_loss": StopLossRequest(stop_price=_r2(t.stop_price)),
        }  # fmt: skip
        if t.target_price is not None:
            common |= {
                "order_class": OrderClass.BRACKET,
                "take_profit": TakeProfitRequest(limit_price=_r2(t.target_price)),
            }
        else:
            common |= {"order_class": OrderClass.OTO}
        req = (LimitOrderRequest(limit_price=_r2(t.limit_price), **common) if t.entry_type == "limit"
               else MarketOrderRequest(**common))  # fmt: skip
        return self.client.submit_order(req)

    def exit_info(self, symbol: str) -> dict | None:
        """Orden de salida (stop) abierta de una posición del sistema: id, stop, qty, lado y huella del ticket."""
        for o in self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True, symbols=[symbol])):
            coid = str(o.client_order_id or "")
            cands = [o, *(o.legs or [])]
            for x in cands:
                kind = str(getattr(x.order_type, "value", x.order_type)).lower()
                if kind == "stop" and x.stop_price is not None:
                    fp = coid.split("-")[1] if coid.startswith(("dt-", "dx-")) else None
                    if fp is None:  # stop de un bracket/OTO: la huella está en la orden de entrada (ya ejecutada)
                        today = datetime.now(UTC).date()
                        for parent in self.orders_since(today):
                            pc = str(parent.client_order_id or "")
                            if pc.startswith("dt-") and any(lg.id == x.id for lg in parent.legs or []):
                                fp = pc.split("-")[1]
                                break
                    side = str(getattr(x.side, "value", x.side)).lower()  # lado de la SALIDA
                    return {"order_id": x.id, "stop": float(x.stop_price), "qty": float(x.qty), "fingerprint": fp,
                            "exit_side": side, "has_target": coid.startswith("dx-")}  # fmt: skip
        return None

    def set_target(self, symbol: str, target: float, client_order_id: str) -> object:
        """Reemplaza el stop de una posición por una OCO (objetivo límite + el MISMO stop). Solo tras y/n.

        Si la OCO falla, vuelve a poner el stop original: la posición nunca queda sin stop más que unos segundos.
        """
        import time as _t

        from alpaca.trading.requests import StopOrderRequest

        info = self.exit_info(symbol)
        if info is None:
            raise RuntimeError(f"{symbol}: no hay orden de stop abierta del sistema")
        side = OrderSide.SELL if info["exit_side"] == "sell" else OrderSide.BUY
        self.client.cancel_order_by_id(info["order_id"])
        for _ in range(20):  # esperar a que Alpaca confirme la cancelación (libera las acciones)
            st = str(getattr(self.client.get_order_by_id(info["order_id"]).status, "value", "")).lower()
            if st in ("canceled", "cancelled", "filled", "expired"):
                break
            _t.sleep(0.5)
        if st == "filled":
            raise RuntimeError(f"{symbol}: el stop se ejecutó mientras se cambiaba; posición cerrada")
        qty = int(info["qty"])
        try:
            return self.client.submit_order(LimitOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY, limit_price=_r2(target),
                order_class=OrderClass.OCO, take_profit=TakeProfitRequest(limit_price=_r2(target)),
                stop_loss=StopLossRequest(stop_price=_r2(info["stop"])), client_order_id=client_order_id,
            ))  # fmt: skip
        except Exception:
            self.client.submit_order(StopOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY, stop_price=_r2(info["stop"]),
                client_order_id=client_order_id + "-s",
            ))  # fmt: skip
            raise

    def cancel_pending_entries(self) -> int:
        """Cancela órdenes de ENTRADA del sistema (prefijo dt-) que aún no se ejecutaron. Devuelve cuántas."""
        n = 0
        for o in self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True)):
            filled = float(o.filled_qty or 0)
            if str(o.client_order_id or "").startswith("dt-") and filled == 0:
                self.client.cancel_order_by_id(o.id)
                n += 1
        return n

    def flatten(self):
        """Cancela órdenes abiertas y cierra todas las posiciones (requiere autorización previa del usuario)."""
        return self.client.close_all_positions(cancel_orders=True)
