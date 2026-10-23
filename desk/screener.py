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

from . import config, journal, store
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


def sector_view() -> dict[str, dict]:
    """symbol -> {"long": sector name or None, "short": sector name or None}."""
    try:
        sec = requests.get(f"{config.SECTOR_SITE}/sectors.json", timeout=20).json()
        stk = requests.get(f"{config.SECTOR_SITE}/stocks.json", timeout=30).json()
    except Exception:  # noqa: BLE001
        return {}
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    now = now_ist()
    if not args.force and (now.weekday() >= 5 or not ("10:10" <= now.strftime("%H:%M") <= "15:59")):
        print(f"{now:%a %H:%M} IST: outside scan hours.")
        return 0
    db = store.connect()
    if not args.force and already_scanned(db, now):
        print("This candle has already been scanned (the other scheduler got there first).")
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
    for sym, df in candles.items():
        if df.empty:
            continue
        df = completed(df, now)
        if len(df) < config.EF_EMA + config.EF_SWING_BARS + 2:
            continue
        e = ema(df.Close, config.EF_EMA)
        last_day = df.index[-1].date()
        for j in range(len(df) - config.EF_SIGNAL_BARS, len(df)):
            sig = signal_at(df, e, j)
            if sig and sig["time"].date() == last_day:
                raw.append((sym, df, e, sig))

    sectors = sector_view()
    ideas, others = [], []
    for sym, df, e, sig in raw:
        side = "Long" if sig["dir"] > 0 else "Short"
        j = sig["bar"]
        has_next = j + 1 < len(df)
        entry = float(df.Open.iloc[j + 1]) if has_next else sig["close"]
        lv = levels(sig, entry)
        base = {"symbol": sym, "side": side, "signal_time": sig["time"].strftime("%Y-%m-%dT%H:%M"),
                "close": sig["close"], "ema": round(sig["ema"], 2), "candle_body": sig["body"],
                "candle_extremity": sig["extremity"], "entry_status": "entered at next open" if has_next
                else "enter at the next candle's open", "lot_size": lots.get(sym),
                "ema_now": round(float(e.iloc[-1]), 2), "last_price": float(df.Close.iloc[-1])}
        if not lv:
            others.append({**base, "reason": "No valid stop below/above entry"})
            continue
        base["levels"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in lv.items()}
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
        if st != want:
            reason = {"Short covering": "Short covering: ignore (fake rally)",
                      "Long unwinding": "Long unwinding: ignore (fake fall)"}.get(st, f"{st}: not the {want.lower()} needed")
            others.append({**base, "reason": reason})
            continue
        base["scoring"] = top5_score(base, sectors)
        ideas.append(base)

    ranked = sorted(ideas, key=lambda x: -x["scoring"]["score"])
    for i, x in enumerate(ranked[:5], 1):
        x["top_rank"] = i
    ideas.sort(key=lambda x: x["signal_time"], reverse=True)
    others.sort(key=lambda x: x["signal_time"], reverse=True)

    closed = 0
    try:
        closed = journal.check_stock_trades(db, candles, now)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"journal: {exc}"[:200])

    doc = {"ts": now.strftime("%Y-%m-%dT%H:%M"), "scanned": len(symbols), "no_candles": missing[:40],
           "ideas": ideas, "top5": [x["symbol"] + ":" + x["side"] for x in ranked[:5]],
           "others": others, "sector_boost_available": bool(sectors), "problems": problems,
           "rules": {"ema": config.EF_EMA, "target_r": config.EF_TARGET_R, "max_days": config.EF_MAX_DAYS,
                     "top5_weights": config.TOP5_WEIGHTS, "sector_boost": config.SECTOR_BOOST}}
    db.put_doc("stock_screener", doc)

    summary = (f"{doc['ts']}: scanned {len(symbols)} (no candles {len(missing)}), trend switches {len(raw)}, "
               f"ideas {len(ideas)}, others {len(others)}, sector data {'yes' if sectors else 'no'}, "
               f"trades closed {closed}, problems {len(problems)}\n"
               + "\n".join(f"#{x.get('top_rank', '-')} {x['symbol']} {x['side']} {x['signal_time']} "
                           f"entry {x['levels']['entry']:.2f} stop {x['levels']['stop']:.2f} "
                           f"target {x['levels']['target']:.2f} {x['futures']['buildup']} "
                           f"OI {x['futures']['pchg_oi']:+.1f}% score {x['scoring']['score']} {x['scoring']['sector'] or ''}"
                           for x in ranked[:8])
               + "\nOthers: " + "; ".join(f"{x['symbol']} {x['side']}: {x['reason']}" for x in others[:12]))
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
