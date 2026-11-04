"""F&O stock screener - hourly 50 EMA + futures OI (Stocks_trade_setup.pdf).

Long (Short is the mirror image)
  1  Trend switch: a solid bullish hourly candle closes above the 50 EMA after
     the previous candle closed at or below it. "Solid": body at least half the
     candle's range, close in the top third.
  2  Futures (mandatory): Long build-up = futures price up AND futures OI up
     (all expiries added, today vs yesterday). Short covering / long unwinding
     are skipped.
  3  Entry at the next candle's open. Stop just beyond the breakout candle or
     the recent swing (10 candles), whichever is closer to the entry.
     Target 1:2. Exit when a candle closes back across the 50 EMA, at 1:2, or
     after 5 sessions.

Top 5 (win rate removed): candle clarity 60% + OI change size 40%, plus a
+10 boost when the stock's sector is Leading/Improving (Longs) or
Lagging/Weakening (Shorts) on the Sector Strength site.

Each idea also gets the signal hour's futures OI, warnings (results, F&O ban,
stop distance, daily trend, regime, volume, chop) and a proposed score; ideas and
signals rejected by the day's futures build-up go to the signal log, whose results
feed the Track record tab (desk/signals.py). After the results are published, the
scan saves futures OI for all F&O stocks for the next scans' signal-hour OI.

Runs ~5 minutes after each hourly candle closes (GitHub Actions).
Run:  python -m desk.screener [--force]
"""

from __future__ import annotations

import argparse
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from . import config, journal, signals, store
from .snapshot import now_ist
from .sources import NSE, yahoo_chart

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def candle_end(t: pd.Timestamp) -> pd.Timestamp:
    return min(t + pd.Timedelta(hours=1), t.normalize() + pd.Timedelta(hours=15, minutes=30))


def completed(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    ends = [candle_end(t) for t in df.index]
    return df[[e <= pd.Timestamp(now) for e in ends]]


def signal_at(df: pd.DataFrame, e: pd.Series, j: int) -> dict | None:
    if j < config.EF_EMA + config.EF_SWING_BARS:
        return None
    o, hi, lo, c = (float(df[k].iloc[j]) for k in ("Open", "High", "Low", "Close"))
    pc, pe, ce = float(df.Close.iloc[j - 1]), float(e.iloc[j - 1]), float(e.iloc[j])
    rng = hi - lo
    if rng <= 0:
        return None
    body, pos = abs(c - o) / rng, (c - lo) / rng
    if pc <= pe and c > ce and c > o and body >= config.EF_BODY and pos >= config.EF_CLOSE_ZONE:
        d = 1
    elif pc >= pe and c < ce and c < o and body >= config.EF_BODY and pos <= 1 - config.EF_CLOSE_ZONE:
        d = -1
    else:
        return None
    prev = slice(j - config.EF_SWING_BARS, j)
    swing = float(df.Low.iloc[prev].min()) if d > 0 else float(df.High.iloc[prev].max())
    return {"dir": d, "bar": j, "time": df.index[j], "close": c, "ema": ce,
            "candle_ext": lo if d > 0 else hi, "swing": swing, "body": round(body, 3),
            "extremity": round(pos if d > 0 else 1 - pos, 3)}


def levels(sig: dict, entry: float) -> dict:
    d = sig["dir"]
    cands = []
    for label, x in (("breakout candle", sig["candle_ext"]), ("recent swing", sig["swing"])):
        stop = x * (1 - config.EF_STOP_BUFFER) if d > 0 else x * (1 + config.EF_STOP_BUFFER)
        if (d > 0 and stop < entry) or (d < 0 and stop > entry):
            cands.append((abs(entry - stop), stop, label))
    if not cands:
        return {}
    risk, stop, label = min(cands)
    return {"entry": entry, "stop": stop, "target": entry + d * config.EF_TARGET_R * risk,
            "risk_pct": risk / entry * 100, "stop_from": label}


def follow(df: pd.DataFrame, e: pd.Series, sig: dict, lv: dict) -> tuple[str, str | None]:
    """Status of a signal after entry: open, or why it already ended."""
    d, j = sig["dir"], sig["bar"]
    for k in range(j + 1, len(df)):
        hi, lo, c = float(df.High.iloc[k]), float(df.Low.iloc[k]), float(df.Close.iloc[k])
        if (d > 0 and lo <= lv["stop"]) or (d < 0 and hi >= lv["stop"]):
            return "stopped", "Signal already stopped out"
        if (d > 0 and hi >= lv["target"]) or (d < 0 and lo <= lv["target"]):
            return "target", "Target already reached"
        if (d > 0 and c < float(e.iloc[k])) or (d < 0 and c > float(e.iloc[k])):
            return "ema_exit", "Closed back across the 50 EMA"
    return "open", None


def sector_view(db=None, extras: dict | None = None) -> dict[str, dict]:
    """symbol -> {"long": sector name or None, "short": sector name or None}.

    The Sector Strength website now keeps its data in the same private
    database (docs ss_sectors / ss_stocks); the old public files are the
    fallback."""
    sec = stk = None
    if db is not None and hasattr(db, "select"):
        try:
            rows = db.select("docs", {"key": "in.(ss_sectors,ss_stocks)", "select": "key,data"})
            got = {r["key"]: r["data"] for r in rows}
            sec, stk = got.get("ss_sectors"), got.get("ss_stocks")
        except Exception:  # noqa: BLE001
            sec = stk = None
    if not sec or not stk:
        try:
            sec = requests.get(f"{config.SECTOR_SITE}/sectors.json", timeout=20).json()
            stk = requests.get(f"{config.SECTOR_SITE}/stocks.json", timeout=30).json()
        except Exception:  # noqa: BLE001
            return {}
    if extras is not None:
        extras["results"] = stk.get("results") or {}
        reg = None
        if db is not None and hasattr(db, "select"):
            reg = signals.get_doc(db, "ss_regime")
        if not reg:
            try:
                reg = requests.get(f"{config.SECTOR_SITE}/regime.json", timeout=20).json()
            except Exception:  # noqa: BLE001
                reg = None
        extras["regime"] = (reg or {}).get("light")
    rows = sec["benchmarks"]["NIFTY500"]["rows"]
    names = sec.get("names", {})
    out = {}
    for sym, s in stk.get("stocks", {}).items():
        lead = [k for k in s.get("sectors", []) if rows.get(k, {}).get("quadrant") in ("Leading", "Improving")]
        lag = [k for k in s.get("sectors", []) if rows.get(k, {}).get("quadrant") in ("Lagging", "Weakening")]
        out[sym] = {"long": names.get(lead[0], lead[0]) if lead else None,
                    "short": names.get(lag[0], lag[0]) if lag else None,
                    "long_q": rows[lead[0]]["quadrant"] if lead else None,
                    "short_q": rows[lag[0]]["quadrant"] if lag else None}
    return out


def top5_score(idea: dict, sectors: dict) -> dict:
    clarity = (idea["candle_body"] + idea["candle_extremity"]) / 2 * 100
    oi = min(abs(idea["futures"].get("pchg_oi") or 0), config.OI_CHANGE_CAP) / config.OI_CHANGE_CAP * 100
    base = config.TOP5_WEIGHTS["clarity"] * clarity + config.TOP5_WEIGHTS["oi_change"] * oi
    sv = sectors.get(idea["symbol"], {})
    key = "long" if idea["side"] == "Long" else "short"
    sector = sv.get(key)
    boost = config.SECTOR_BOOST if sector else 0.0
    return {"score": round(min(100.0, base + boost), 1), "clarity": round(clarity, 1), "oi_change": round(oi, 1),
            "sector": sector, "sector_quadrant": sv.get(f"{key}_q"), "boost": boost}


DAY_KEY = "stock_screener_day"


def save_day_run(db, doc: dict) -> str:
    """Keep every scan's ideas for the day (Run 1, Run 2, ...); a new day starts fresh."""
    day = doc["ts"][:10]
    cur = signals.get_doc(db, DAY_KEY) or {}
    runs = cur.get("runs", []) if cur.get("date") == day else []
    runs = [r for r in runs if r.get("ts") != doc["ts"]]
    keep = ("symbol", "side", "signal_time", "entry_status", "levels", "futures_levels", "hourly", "warnings",
            "top_rank", "rank_v2", "lot_size", "v2")
    ideas = [{**{k: x.get(k) for k in keep},
              "futures": {k: (x.get("futures") or {}).get(k) for k in ("buildup", "pchg_oi", "pchange")},
              "scoring": {k: (x.get("scoring") or {}).get(k) for k in ("score", "clarity", "oi_change", "boost", "sector", "sector_quadrant")}}
             for x in doc.get("ideas", [])]
    runs.append({"ts": doc["ts"], "early": bool(doc.get("early")), "scanned": doc.get("scanned"),
                 "ideas": ideas, "others": len(doc.get("others", []))})
    runs.sort(key=lambda r: r["ts"])
    db.put_doc(DAY_KEY, {"date": day, "runs": runs})
    return f"day log: run {len(runs)} of {day}"


def last_candle_end(now: datetime) -> datetime:
    ends = [now.replace(hour=h, minute=15, second=0, microsecond=0) for h in range(10, 16)]
    ends.append(now.replace(hour=15, minute=30, second=0, microsecond=0))
    done = [e for e in ends if e <= now]
    return done[-1] if done else now.replace(hour=0, minute=0)


def already_scanned(db, now: datetime) -> bool:
    try:
        rows = db.select("docs", {"key": "eq.stock_screener", "select": "data->>ts"})
        ts = next(iter(rows[0].values())) if rows else None
        return bool(ts) and datetime.fromisoformat(str(ts)[:16]) >= last_candle_end(now)
    except Exception:  # noqa: BLE001
        return False



def save_trade_prices(db, candles: dict, now, lots: dict) -> int:
    """Check open stock trades on these candles (auto-close at stop/target/time) and
    save the current price of those still open for the My trades page."""
    # stock trades without a lot size: take today's F&O lot size (1 lot), and fill in the
    # rupee P&L of closed ones that had none
    if lots:
        for tr in db.select("trades", {"kind": "eq.stock", "lot_size": "is.null"}):
            lot = lots.get(tr["symbol"])
            if not lot:
                continue
            vals = {"lot_size": lot, "lots": tr.get("lots") or 1}
            if tr["status"] == "closed" and tr.get("exit") is not None and tr.get("pnl_inr") is None:
                vals["pnl_inr"] = journal.stock_inr({**tr, **vals}, float(tr["exit"]), journal.stock_qty({**tr, **vals}))
            db.update("trades", {"id": f"eq.{tr['id']}"}, vals)
    prices: dict = {}
    closed = journal.check_stock_trades(db, candles, now, prices, lots)
    db.put_doc("trade_prices_stock", {"ts": now.strftime("%Y-%m-%dT%H:%M"), "prices": prices})
    return closed


def quick_trade_prices(now, db=None) -> None:
    """Only the open stock trades: fetch their candles and update prices (fast)."""
    try:
        db = db or store.connect()
        trades = db.select("trades", {"kind": "eq.stock", "status": "eq.open"})
        if not trades:
            return
        syms = sorted({t["symbol"] for t in trades})
        candles = {s: yahoo_chart(f"{s}.NS", "60m", "1mo") for s in syms}
        try:
            lots = NSE().fno_lots()
        except Exception:  # noqa: BLE001
            lots = {}
        closed = save_trade_prices(db, candles, now, lots)
        print(f"::notice title=Open trades::prices updated for {len(syms)} stock(s), {closed} closed")
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::open-trade prices: {exc}")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    now = now_ist()
    if not args.force and (now.weekday() >= 5 or not ("10:10" <= now.strftime("%H:%M") <= "15:59")):
        print(f"{now:%a %H:%M} IST: outside scan hours.")
        if now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:59":
            quick_trade_prices(now)      # Run scan before 10:10: still refresh your open trades
        return 0
    db = store.connect()
    if not args.force and already_scanned(db, now):
        print("This candle has already been scanned (the other scheduler got there first).")
        quick_trade_prices(now, db)
        return 0
    nse = NSE()
    problems: list[str] = []
    lots = nse.fno_lots()
    symbols = sorted(s for s in lots if s not in INDEX_SYMBOLS)

    def get(sym):
        return sym, yahoo_chart(f"{sym}.NS", "60m", "3mo")

    with ThreadPoolExecutor(max_workers=8) as ex:
        candles = dict(ex.map(get, symbols))
    missing = [s for s, df in candles.items() if df.empty]

    raw = []
    last_completed = None
    for sym, df in candles.items():
        if df.empty:
            continue
        full = df
        df = completed(df, now)
        if len(df):
            last_completed = max(last_completed, df.index[-1]) if last_completed is not None else df.index[-1]
        if len(df) < config.EF_EMA + config.EF_SWING_BARS + 2:
            continue
        e = ema(df.Close, config.EF_EMA)
        last_day = df.index[-1].date()
        for j in range(len(df) - config.EF_SIGNAL_BARS, len(df)):
            sig = signal_at(df, e, j)
            if sig and sig["time"].date() == last_day:
                raw.append((sym, df, e, sig, full))

    extras: dict = {}
    sectors = sector_view(db, extras)
    snaps = signals.load_snaps(db)
    try:
        banned = nse.fo_ban()
    except Exception as exc:  # noqa: BLE001
        banned = set()
        problems.append(f"F&O ban list: {exc}"[:160])
    today = now.date()
    ideas, others, rejected = [], [], []
    for sym, df, e, sig, full in raw:
        side = "Long" if sig["dir"] > 0 else "Short"
        j = sig["bar"]
        has_next = j + 1 < len(df)
        # the next candle may be still in progress (e.g. today's 9:15 candle before 10:15):
        # its open is already known, so that is the real entry price
        later = full[full.index > sig["time"]]
        live_open = float(later.Open.iloc[0]) if not has_next and len(later) and pd.notna(later.Open.iloc[0]) else None
        entry = float(df.Open.iloc[j + 1]) if has_next else live_open if live_open else sig["close"]
        status_txt = ("entered at next open" if has_next else
                      f"entered at {later.index[0]:%H:%M} open (candle in progress)" if live_open else
                      "enter at the next candle's open")
        lv = levels(sig, entry)
        base = {"symbol": sym, "side": side, "signal_time": sig["time"].strftime("%Y-%m-%dT%H:%M"),
                "close": sig["close"], "ema": round(sig["ema"], 2), "candle_body": sig["body"],
                "candle_extremity": sig["extremity"], "entry_status": status_txt, "lot_size": lots.get(sym),
                "ema_now": round(float(e.iloc[-1]), 2), "last_price": float(df.Close.iloc[-1])}
        if not lv:
            others.append({**base, "reason": "No valid stop below/above entry"})
            continue
        base["levels"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in lv.items()}
        base["sig"] = {"candle_ext": round(sig["candle_ext"], 2), "swing": round(sig["swing"], 2)}
        status, why = follow(df, e, sig, lv)
        if status != "open":
            others.append({**base, "reason": why})
            continue
        try:
            fut = nse.stock_futures(sym)
        except Exception as exc:  # noqa: BLE001
            fut = None
            problems.append(f"{sym} futures: {exc}"[:160])
        if not fut:
            others.append({**base, "reason": "Futures OI unavailable"})
            continue
        st = ("Long build-up" if fut["pchange"] > 0 and fut["chg_oi_total"] > 0 else
              "Short build-up" if fut["pchange"] < 0 and fut["chg_oi_total"] > 0 else
              "Short covering" if fut["pchange"] > 0 else "Long unwinding")
        fut["buildup"] = st
        base["futures"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in fut.items()}
        basis = fut["ltp"] - (fut.get("spot") or base["last_price"])
        base["futures_levels"] = {k: round(base["levels"][k] + basis, 2) for k in ("entry", "stop", "target")}
        want = "Long build-up" if side == "Long" else "Short build-up"
        base["hourly"] = signals.signal_hour(snaps, sym, sig["time"], fut)
        base["info"] = signals.context(df, e, j, side, lv, extras.get("results", {}).get(sym), sym in banned,
                                       extras.get("regime"), today)
        base["warnings"] = signals.warnings(side, base["info"], base["hourly"], check_hour=(st == want))
        if st != want:
            reason = {"Short covering": "Short covering: ignore (fake rally)",
                      "Long unwinding": "Long unwinding: ignore (fake fall)"}.get(st, f"{st}: not the {want.lower()} needed")
            others.append({**base, "reason": reason})
            if st in ("Short build-up", "Long build-up", "Short covering", "Long unwinding"):
                rejected.append({**base, "reason": reason})
            continue
        base["scoring"] = top5_score(base, sectors)
        base["v2"] = signals.score_v2(base, base["hourly"], base["info"].get("size_ratio"), base["scoring"]["boost"])
        ideas.append(base)

    ranked = sorted(ideas, key=lambda x: -x["scoring"]["score"])
    for i, x in enumerate(ranked[:5], 1):
        x["top_rank"] = i
    for i, x in enumerate(sorted(ideas, key=lambda x: -x["v2"]["score"]), 1):
        x["rank_v2"] = i
    ideas.sort(key=lambda x: x["signal_time"], reverse=True)
    others.sort(key=lambda x: x["signal_time"], reverse=True)

    closed = 0
    try:
        closed = save_trade_prices(db, candles, now, lots)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"journal: {exc}"[:200])

    doc = {"ts": now.strftime("%Y-%m-%dT%H:%M"), "scanned": len(symbols), "no_candles": missing[:40],
           "ideas": ideas, "top5": [x["symbol"] + ":" + x["side"] for x in ranked[:5]],
           "others": others, "sector_boost_available": bool(sectors), "problems": problems,
           # before the day's first hourly candle closes (10:15), signals come from the previous
           # session's candles and the futures check covers only the first minutes of today
           "early": ({"last_candle": last_completed.strftime("%Y-%m-%dT%H:%M"),
                      "futures_minutes": max(0, int((now - now.replace(hour=9, minute=15, second=0, microsecond=0)).total_seconds() // 60))}
                     if last_completed is not None and last_completed.date() < now.date() and now.weekday() < 5
                     and now.strftime("%H:%M") >= "09:15" else None),
           "regime": extras.get("regime"), "fo_ban": sorted(banned),
           "rules": {"ema": config.EF_EMA, "target_r": config.EF_TARGET_R, "max_days": config.EF_MAX_DAYS,
                     "top5_weights": config.TOP5_WEIGHTS, "sector_boost": config.SECTOR_BOOST}}
    db.put_doc("stock_screener", doc)

    # after the results are out: day log of runs, signal log, results of earlier signals, OI snapshot
    after = []
    try:
        after.append(save_day_run(db, doc))
    except Exception as exc:  # noqa: BLE001
        after.append(f"day log not saved: {exc}"[:200])
    try:
        after.append(signals.write_log(db, signals.log_rows(ideas, "idea", doc["ts"]) +
                                       signals.log_rows(rejected, "rejected", doc["ts"])))
    except Exception as exc:  # noqa: BLE001
        after.append(f"signal log not written: {exc}"[:220] + (" (run supabase/010_signal_log.sql)" if "signal_log" in str(exc) else ""))
    try:
        after.append(signals.evaluate(db, candles, now, completed, ema, levels))
    except Exception as exc:  # noqa: BLE001
        after.append(f"results not checked: {exc}"[:220])
    try:
        after.append(signals.take_snapshot(db, NSE, symbols, now_ist, snaps))
    except Exception as exc:  # noqa: BLE001
        after.append(f"OI snapshot failed: {exc}"[:220])

    summary = (f"{doc['ts']}: scanned {len(symbols)} (no candles {len(missing)}), trend switches {len(raw)}, "
               f"ideas {len(ideas)}, others {len(others)}, sector data {'yes' if sectors else 'no'}, "
               f"trades closed {closed}, problems {len(problems)}\n"
               + "\n".join(f"#{x.get('top_rank', '-')} {x['symbol']} {x['side']} {x['signal_time']} "
                           f"entry {x['levels']['entry']:.2f} stop {x['levels']['stop']:.2f} "
                           f"target {x['levels']['target']:.2f} {x['futures']['buildup']} "
                           f"OI {x['futures']['pchg_oi']:+.1f}% score {x['scoring']['score']} {x['scoring']['sector'] or ''}"
                           for x in ranked[:8])
               + "\nOthers: " + "; ".join(f"{x['symbol']} {x['side']}: {x['reason']}" for x in others[:12])
               + "\nAfter: " + "; ".join(after))
    print(summary)
    for p in problems[:10]:
        print("PROBLEM:", p)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::notice title=Stock screener::" + summary.replace("%", "%25").replace("\n", "%0A"))
    return 0


def run() -> int:
    try:
        return main()
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=Stock screener crashed::" + tb[-3000:].replace("%", "%25").replace("\n", "%0A"))
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
