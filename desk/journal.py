"""My Trades: automatic closing of open trades you logged with "I took this trade".

Stock trades (hourly candles, checked by the screener job):
    stop hit, target hit, or time exit after 5 sessions (entry day = day 1).
    The 50 EMA close-back rule is NOT applied to your trades.
Index futures trades (checked every 15 minutes by the snapshot job):
    stop hit or target hit on the futures price, or time exit after 5 sessions.
P&L: stocks in % after 0.1% round-trip costs; index futures in rupees
    (points x lots x lot size, minus any charges you entered).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from . import config


def sessions_between(start: date, end: date) -> int:
    """Trading sessions from start to end inclusive (weekdays; exchange holidays not excluded)."""
    if end < start:
        return 0
    days = pd.bdate_range(start, end)
    return len(days)


def _pct(entry: float, exit_: float, side: str) -> float:
    sign = 1 if side == "Long" else -1
    return round(((exit_ / entry - 1) * 100 * sign) - config.COST_PCT, 3)


def _close_values(tr: dict, exit_price: float, reason: str, when: datetime) -> dict:
    vals = {"exit": round(exit_price, 2), "exit_time": when.strftime("%Y-%m-%dT%H:%M"),
            "exit_reason": reason, "status": "closed"}
    entry, side = float(tr["entry"]), tr["side"]
    if tr.get("kind") == "index":
        sign = 1 if side == "Long" else -1
        lots, lot = tr.get("lots") or 1, tr.get("lot_size") or 1
        vals["pnl_inr"] = round((exit_price - entry) * sign * lots * lot - float(tr.get("charges") or 0), 2)
        vals["net_pct_after_cost"] = round((exit_price / entry - 1) * 100 * sign, 3)
    else:
        vals["net_pct_after_cost"] = _pct(entry, exit_price, side)
        if tr.get("qty"):
            vals["pnl_inr"] = round((exit_price - entry) * (1 if side == "Long" else -1) * float(tr["qty"])
                                    - entry * float(tr["qty"]) * config.COST_PCT / 100, 2)
    return vals


def check_index_trades(db, fut_now: dict, spots: dict, now: datetime, prices: dict | None = None) -> int:
    """prices (optional): filled with {trade id: {"px", "t"}} for trades that stay open."""
    trades = db.select("trades", {"kind": "eq.index", "status": "eq.open"})
    closed = 0
    for tr in trades:
        sym, side = tr["symbol"], tr["side"]
        prices = fut_now.get(sym) or {}
        price = prices.get(str(tr.get("expiry"))) if tr.get("expiry") else None
        if price is None and prices:
            price = prices[sorted(prices)[0]]
        if price is None:
            price = spots.get(sym)
        if not price:
            continue
        stop, target = tr.get("stop"), tr.get("target")
        reason, exit_price = None, None
        if side == "Long":
            if stop and price <= stop:
                reason, exit_price = "stop hit (auto)", stop
            elif target and price >= target:
                reason, exit_price = "target hit (auto)", target
        else:
            if stop and price >= stop:
                reason, exit_price = "stop hit (auto)", stop
            elif target and price <= target:
                reason, exit_price = "target hit (auto)", target
        entry_day = datetime.fromisoformat(str(tr["entry_time"])[:16]).date()
        if not reason and sessions_between(entry_day, now.date()) >= config.SWING_MAX_SESSIONS \
                and now.strftime("%H:%M") >= "15:15":
            reason, exit_price = "time exit (auto)", price
        if reason:
            db.update("trades", {"id": f"eq.{tr['id']}"}, _close_values(tr, float(exit_price), reason, now))
            closed += 1
        elif prices is not None:
            prices[str(tr["id"])] = {"px": round(float(price), 2), "t": now.strftime("%Y-%m-%dT%H:%M")}
    return closed


def check_stock_trades(db, candles: dict[str, pd.DataFrame], now: datetime, prices: dict | None = None,
                       lots: dict | None = None) -> int:
    """candles: symbol -> hourly OHLC (IST index). Walks each open trade's candles
    after entry; the stop is checked before the target inside the same candle."""
    trades = db.select("trades", {"kind": "eq.stock", "status": "eq.open"})
    closed = 0
    for tr in trades:
        df = candles.get(tr["symbol"])
        if df is None or df.empty:
            continue
        entry_t = pd.Timestamp(str(tr["entry_time"])[:16])
        ends = pd.Series([min(t + pd.Timedelta(hours=1), t.normalize() + pd.Timedelta(hours=15, minutes=30))
                          for t in df.index], index=df.index)
        after = df[(ends > entry_t) & (ends <= pd.Timestamp(now))]
        side, stop, target = tr["side"], tr.get("stop"), tr.get("target")
        reason = exit_price = when = None
        for t, c in after.iterrows():
            if side == "Long":
                if stop and c.Low <= stop:                       # gap below the stop fills at the open
                    reason, exit_price = "stop hit (auto)", min(stop, c.Open)
                elif target and c.High >= target:
                    reason, exit_price = "target hit (auto)", max(target, c.Open)
            else:
                if stop and c.High >= stop:
                    reason, exit_price = "stop hit (auto)", max(stop, c.Open)
                elif target and c.Low <= target:
                    reason, exit_price = "target hit (auto)", min(target, c.Open)
            if reason:
                when = t.to_pydatetime()
                break
            if sessions_between(entry_t.date(), t.date()) >= config.EF_MAX_DAYS and t.strftime("%H:%M") >= "15:15":
                reason, exit_price, when = "time exit (auto)", float(c.Close), ends[t].to_pydatetime()
                break
        if reason:
            db.update("trades", {"id": f"eq.{tr['id']}"}, _close_values(tr, float(exit_price), reason, when))
            closed += 1
        elif prices is not None:
            px = df.attrs.get("price") or float(df.Close.iloc[-1])
            prices[str(tr["id"])] = {"px": round(float(px), 2), "t": now.strftime("%Y-%m-%dT%H:%M"),
                                     "lot": (lots or {}).get(tr["symbol"])}
    return closed
