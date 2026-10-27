"""Evening check of open cash-market positional trades ("My Trades" on the
Sector Strength website, table cash_trades).

For each open trade it downloads daily candles (Yahoo, split-adjusted),
updates the last close, 50-day average and sessions held, and closes the
trade when its exit rule says so. Sessions after the entry day are checked
in order; inside one session the stop is checked before the target.

Exit rules
  stop_target  (and the older "system") closed automatically ONLY when the
               stop you entered is hit. Reaching the target, a close below the
               50-day average and 120+ sessions are shown as warnings only.
  manual       never closed automatically; warnings only

Trades that an earlier version closed for a 50-day / time / target reason are
re-opened (and then checked against their stop only).

P&L: (exit - entry) x quantity, minus your charges if you entered them,
otherwise minus 0.25% of the buy value (typical delivery costs).

Run:  python -m desk.cash_journal
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, store
from .sources import yahoo_chart

DEFAULT_COST_PCT = 0.25
MAX_SESSIONS = 120
YAHOO_ALIAS = {"M&M": "M&M.NS", "M&MFIN": "M&MFIN.NS"}


def candles(symbol: str) -> pd.DataFrame:
    df = yahoo_chart(YAHOO_ALIAS.get(symbol, f"{symbol}.NS"), "1d", "2y")
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index).normalize()
    df = df[~df.index.duplicated(keep="last")]
    df["SMA50"] = df.Close.rolling(50, min_periods=50).mean()
    return df


def pnl(tr: dict, exit_price: float) -> tuple[float, float]:
    qty, entry = float(tr["qty"]), float(tr["entry"])
    gross = (exit_price - entry) * qty
    cost = float(tr["charges"]) if tr.get("charges") not in (None, "") else entry * qty * DEFAULT_COST_PCT / 100
    net = gross - cost
    return round(net, 2), round(net / (entry * qty) * 100, 3)


def check(tr: dict, df: pd.DataFrame, today: date) -> dict:
    entry_day = pd.Timestamp(tr["entry_date"])
    after = df[(df.index > entry_day) & (df.index <= pd.Timestamp(today))]
    rule = tr.get("exit_rule") or "system"
    stop, target = tr.get("stop"), tr.get("target")
    vals: dict = {}
    reason = price = when = None
    n = 0
    for d, c in after.iterrows():
        n += 1
        if rule != "manual" and stop and c.Low <= stop:   # only your stop closes a trade
            reason, price = "Stop (auto)", min(float(stop), float(c.Open))
        if reason:
            when = d
            break
    last = df[df.index <= pd.Timestamp(today)].iloc[-1]
    vals.update({"last_close": round(float(last.Close), 2), "last_date": last.name.date().isoformat(),
                 "sma50": round(float(last.SMA50), 2) if pd.notna(last.SMA50) else None, "sessions_held": n})
    if reason:
        net, pct = pnl(tr, price)
        vals.update({"status": "closed", "exit": round(price, 2), "exit_date": when.date().isoformat(),
                     "exit_reason": reason, "pnl_inr": net, "net_pct": pct, "alert": None})
        return vals
    alerts = []
    if target and (after.High >= float(target)).any():
        alerts.append("Target reached")
    if pd.notna(last.SMA50) and last.Close < last.SMA50:
        alerts.append("Closed below its 50-day average")
    if stop and last.Close <= float(stop):
        alerts.append("Closed below the stop")
    elif stop and last.Close <= float(stop) * 1.02:
        alerts.append("Within 2% of the stop")
    if n >= MAX_SESSIONS:
        alerts.append(f"Held {MAX_SESSIONS}+ sessions")
    vals["alert"] = "; ".join(alerts) or None
    return vals


def check_watch(w: dict, df: pd.DataFrame, today: date) -> dict:
    """Watchlist entry from a Sector Strength setup: first day price reached the
    buy level (a "buy above" trigger needs the day's high; other setups buy at
    the setup day's close) and first day it traded at or below the stop."""
    day0 = pd.Timestamp(w.get("setup_date") or str(w["added_at"])[:10])
    after = df[(df.index > day0) & (df.index <= pd.Timestamp(today))]
    vals: dict = {}
    buy, stop = w.get("buy"), w.get("stop")
    buy_hit = w.get("buy_hit_on")
    if buy and not buy_hit:
        if not w.get("buy_is_trigger"):
            buy_hit = day0.date().isoformat()
        else:
            hit = after[after.High >= float(buy)]
            if len(hit):
                buy_hit = hit.index[0].date().isoformat()
        if buy_hit:
            vals["buy_hit_on"] = buy_hit
    if stop and not w.get("stop_hit_on"):
        hit = after[after.Low <= float(stop)]
        if len(hit):
            vals["stop_hit_on"] = hit.index[0].date().isoformat()
    last = df[df.index <= pd.Timestamp(today)].iloc[-1]
    vals.update({"last_close": round(float(last.Close), 2), "last_date": last.name.date().isoformat()})
    return vals


def watchlist(db, today: date) -> None:
    try:
        rows = db.select("fd_watchlist", {"buy": "not.is.null"})
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::watchlist not readable ({exc}); run supabase/001_watchlist.sql in the Fundamentals Desk repo")
        return
    n = 0
    for w in rows:
        df = candles(w["symbol"])
        time.sleep(0.4)
        if df.empty:
            continue
        db.update("fd_watchlist", {"id": f"eq.{w['id']}"}, check_watch(w, df, today))
        n += 1
    print(f"::notice::Watchlist setups checked: {n} of {len(rows)}")


OLD_AUTO_EXITS = ("Closed below 50-day (auto)", "Target (auto)")


def reopen(db) -> None:
    """Re-open trades an earlier version closed for anything other than the stop."""
    try:
        closed = db.select("cash_trades", {"status": "eq.closed"})
    except Exception:  # noqa: BLE001
        return
    for tr in closed:
        why = tr.get("exit_reason") or ""
        if why in OLD_AUTO_EXITS or (why.startswith("Time,") and why.endswith("(auto)")):
            db.update("cash_trades", {"id": f"eq.{tr['id']}"},
                      {"status": "open", "exit": None, "exit_date": None, "exit_reason": None,
                       "pnl_inr": None, "net_pct": None, "exit_rule": "stop_target"})
            print(f"::notice::{tr['symbol']} re-opened (it had been closed by '{why}', not by its stop)")
    # older open trades on the old default rule: same behaviour now, label it clearly
    try:
        db.update("cash_trades", {"status": "eq.open", "exit_rule": "eq.system"}, {"exit_rule": "stop_target"})
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    db = store.connect()
    today = datetime.now(ZoneInfo(config.TZ)).date()
    watchlist(db, today)
    reopen(db)
    try:
        trades = db.select("cash_trades", {"status": "eq.open"})
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::cash_trades table not readable ({exc}); run supabase/003_cash_trades.sql")
        return 0
    closed = updated = 0
    for tr in trades:
        df = candles(tr["symbol"])
        time.sleep(0.4)
        if df.empty:
            print(f"::warning::no daily candles for {tr['symbol']}")
            continue
        vals = check(tr, df, today)
        db.update("cash_trades", {"id": f"eq.{tr['id']}"}, vals)
        updated += 1
        if vals.get("status") == "closed":
            closed += 1
            print(f"::notice::{tr['symbol']} closed: {vals['exit_reason']} at {vals['exit']}, {vals['net_pct']:+.2f}%")
    print(f"::notice::Cash trades: {len(trades)} open, {updated} updated, {closed} closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
