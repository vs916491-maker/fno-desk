"""Signal log for the Track record tab, plus what each idea is judged on beyond the
live Top 5 score.

Per signal (computed by the screener, desk/screener.py):
  hourly    futures OI and price change over the signal hour: the change since the
            snapshot taken just after the signal candle opened (the screener saves OI
            for all F&O stocks after every scan). Signal on the day's first candle:
            since yesterday's last snapshot, i.e. the same as the day's change.
  context   daily trend (vs 20-day average), breakout volume vs the same hourly
            candle on recent sessions, 50 EMA crosses in the ~3 sessions before
            (chop), stop distance, results date, F&O ban, market regime light.
  warnings  plain-language flags from the above. Warnings never block an idea.
  score_v2  proposed score (signal-hour OI 35, day OI 25, candle shape 25 + size 15, plus the same
            sector boost; volume not scored). Logged only; the live Top 5 is unchanged.

Log (Supabase table signal_log, supabase/010_signal_log.sql): every idea, and every
signal rejected only because the day's futures build-up was against it, the first
time a scan lists it. Later scans fill in the result with the strategy's own exits
(stop, 1:2 target, close back across the 50 EMA, or 5 sessions) and, as alt_*, the
result with only stop / target / 5 sessions (how "My trades" closes your trades).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config
from .journal import sessions_between

SNAP_KEY = "stock_oi_snaps"
LOG_TABLE = "signal_log"


# ------------------------------------------------------------------ helpers
def get_doc(db, key: str):
    try:
        rows = db.select("docs", {"key": f"eq.{key}", "select": "data"})
        return rows[0]["data"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def _r(v, d=2):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), d)


# ------------------------------------------------------------------ hourly futures OI snapshots
def load_snaps(db) -> list[dict]:
    d = get_doc(db, SNAP_KEY) or {}
    return d.get("snaps") or []


def take_snapshot(db, nse_cls, symbols: list[str], now_fn, snaps: list[dict]) -> str:
    """Futures OI (all expiries) and spot price of every F&O stock, saved for the next
    scans' signal-hour OI. Runs after the scan results are published."""
    now = now_fn()
    if snaps:
        last = datetime.fromisoformat(snaps[-1]["ts"])
        if (now - last).total_seconds() < config.OI_SNAP_MIN_AGE_MIN * 60 and last.date() == now.date():
            return f"snapshot skipped (last one at {last:%H:%M})"
    nse = nse_cls(gap=config.OI_SNAP_GAP)
    t0, data, fails = time.time(), {}, 0
    for sym in symbols:
        if time.time() - t0 > config.OI_SNAP_MAX_SEC:
            break
        try:
            f = nse.stock_futures(sym)
        except Exception:  # noqa: BLE001
            fails += 1
            if fails >= 15 and not data:
                break
            continue
        if f and f.get("oi_total"):
            data[sym] = [f["oi_total"], f.get("spot") or f.get("ltp")]
    if not data:
        return f"snapshot failed ({fails} errors)"
    snaps = (snaps + [{"ts": now.strftime("%Y-%m-%dT%H:%M"), "d": data}])[-config.OI_SNAP_KEEP:]
    db.put_doc(SNAP_KEY, {"snaps": snaps})
    return f"snapshot {len(data)}/{len(symbols)} stocks in {time.time() - t0:.0f}s"


def buildup(px_pct: float, oi_pct: float) -> str:
    if abs(oi_pct) < config.HOUR_FLAT_PCT:
        return "OI flat"
    if oi_pct > 0:
        return "Long build-up" if px_pct >= 0 else "Short build-up"
    return "Short covering" if px_pct >= 0 else "Long unwinding"


def signal_hour(snaps: list[dict], sym: str, sig_time: pd.Timestamp, fut_now: dict) -> dict | None:
    """Futures OI and price change from just after the signal candle opened until now."""
    start = pd.Timestamp(sig_time).to_pydatetime()
    if start.strftime("%H:%M") == config.MARKET_OPEN:
        # 9:15 candle: measure from yesterday's closing OI (NSE's day change), not from
        # yesterday's last snapshot. The ~15:19 snapshot does not match NSE's end-of-day OI
        # (median -1.2% to the next morning across all stocks, 6 Nov 2026), which made
        # almost every 9:15 signal show a false OI drop.
        oi1, coi = fut_now.get("oi_total"), fut_now.get("chg_oi_total")
        px_pct = fut_now.get("pchange")
        if oi1 and coi is not None and px_pct is not None and oi1 - coi > 0:
            oi_pct = coi / (oi1 - coi) * 100
            return {"oi_pct": _r(oi_pct), "px_pct": _r(px_pct), "buildup": buildup(px_pct, oi_pct),
                    "since": (start - timedelta(days=1)).strftime("%Y-%m-%dT15:30"), "from_prev_day": True}
    base = None
    for s in reversed(snaps):
        ts = datetime.fromisoformat(s["ts"])
        if ts <= start + timedelta(minutes=25) and sym in s["d"]:
            base = (ts, s["d"][sym])
            break
    if not base:
        return None
    ts, (oi0, px0) = base
    first_candle = start.strftime("%H:%M") == config.MARKET_OPEN
    if ts.date() < start.date() and not first_candle:
        return None                                   # a scan was missed: no clean base
    if ts.date() == start.date() and ts < start - timedelta(minutes=75):
        return None
    oi1, px1 = fut_now.get("oi_total"), fut_now.get("spot") or fut_now.get("ltp")
    if not (oi0 and px0 and oi1 and px1):
        return None
    oi_pct, px_pct = (oi1 / oi0 - 1) * 100, (px1 / px0 - 1) * 100
    return {"oi_pct": _r(oi_pct), "px_pct": _r(px_pct), "buildup": buildup(px_pct, oi_pct),
            "since": ts.strftime("%Y-%m-%dT%H:%M"), "from_prev_day": ts.date() < start.date()}


# ------------------------------------------------------------------ context and warnings
def daily_trend(df: pd.DataFrame, j: int) -> tuple[str | None, float | None]:
    closes = df.Close.iloc[: j + 1]
    days = closes.groupby(closes.index.date).last()
    prev = days.iloc[:-1]                              # sessions before the signal day
    if len(prev) < config.DAILY_SMA:
        return None, None
    sma = float(prev.iloc[-config.DAILY_SMA:].mean())
    c = float(df.Close.iloc[j])
    return ("up" if c > sma else "down"), _r((c / sma - 1) * 100)


def volume_ratio(df: pd.DataFrame, j: int) -> float | None:
    v = df.Volume.iloc[j] if "Volume" in df else None
    if v is None or pd.isna(v) or v <= 0:
        return None
    t, d = df.index[j].time(), df.index[j].date()
    prev = df.iloc[:j]
    same = prev[[(x.time() == t and x.date() != d) for x in prev.index]].Volume.tail(config.VOL_SESSIONS)
    same = same[same > 0]
    if len(same) < 3:
        return None
    return _r(float(v) / float(same.mean()))


def size_ratio(df: pd.DataFrame, j: int) -> float | None:
    """Signal candle's range vs the same hourly candle's average range over recent sessions."""
    rng = float(df.High.iloc[j] - df.Low.iloc[j])
    t, d = df.index[j].time(), df.index[j].date()
    prev = df.iloc[:j]
    same = prev[[(x.time() == t and x.date() != d) for x in prev.index]].tail(config.VOL_SESSIONS)
    usual = (same.High - same.Low)
    usual = usual[usual > 0]
    if len(usual) < 3 or rng <= 0:
        return None
    return _r(rng / float(usual.mean()))


def ema_crosses(df: pd.DataFrame, e: pd.Series, j: int) -> int:
    lo = max(1, j - config.CHOP_BARS)
    side = np.sign(df.Close.iloc[lo - 1:j].to_numpy() - e.iloc[lo - 1:j].to_numpy())
    side = side[side != 0]
    return int((np.diff(side) != 0).sum()) if len(side) > 1 else 0


def results_sessions(res: dict | None, today: date) -> tuple[str | None, int | None]:
    if not res or not res.get("date"):
        return None, None
    d = date.fromisoformat(res["date"])
    if d < today:
        return None, None
    return d.isoformat(), int(np.busday_count(today, d))


def context(df, e, j, side: str, lv: dict, results: dict | None, banned: bool, regime: str | None,
            today: date) -> dict:
    trend, vs_sma = daily_trend(df, j)
    rdate, rsess = results_sessions(results, today)
    return {"daily_trend": trend, "vs_sma20_pct": vs_sma, "vol_ratio": volume_ratio(df, j), "size_ratio": size_ratio(df, j),
            "ema_crosses": ema_crosses(df, e, j), "risk_pct": _r(lv.get("risk_pct")),
            "results_date": rdate, "results_sessions": rsess, "fo_ban": bool(banned), "regime": regime}


def warnings(side: str, info: dict, hourly: dict | None, check_hour: bool) -> list[str]:
    w = []
    if info.get("fo_ban"):
        w.append("In the F&O ban today: no new positions allowed")
    if info.get("results_sessions") is not None and info["results_sessions"] <= config.WARN_RESULTS_SESSIONS:
        d = datetime.fromisoformat(info["results_date"])
        w.append("Results today" if info["results_sessions"] == 0 else f"Results on {d:%d %b} (in {info['results_sessions']} sessions)")
    r = info.get("risk_pct")
    if r is not None and r < config.WARN_RISK_MIN:
        w.append(f"Stop only {r:.2f}% away: normal noise can hit it")
    elif r is not None and r > config.WARN_RISK_MAX:
        w.append(f"Stop {r:.1f}% away: large risk for a 5-session trade")
    t = info.get("daily_trend")
    if (side == "Long" and t == "down") or (side == "Short" and t == "up"):
        w.append(f"Against the daily trend: price {'below' if t == 'down' else 'above'} its {config.DAILY_SMA}-day average")
    g = info.get("regime")
    if (side == "Long" and g == "Red") or (side == "Short" and g == "Green"):
        w.append(f"{side} while the market regime light is {g}")
    v = info.get("vol_ratio")
    if v is not None and v < config.WARN_VOL_RATIO:
        w.append(f"Breakout volume {v:.1f}x the usual for this hour")
    z = info.get("size_ratio")
    if z is not None and z < config.WARN_SMALL_CANDLE:
        w.append(f"Small candle: {z:.1f}x the usual range for this hour")
    elif z is not None and z > config.WARN_BIG_CANDLE:
        w.append(f"Very big candle: {z:.1f}x the usual range for this hour (entry far from the 50 EMA, wide stop)")
    c = info.get("ema_crosses")
    if c is not None and c >= config.WARN_CHOP_CROSSES:
        w.append(f"Choppy: {c} crosses of the 50 EMA in the 3 sessions before")
    if check_hour and hourly:
        want = "Long build-up" if side == "Long" else "Short build-up"
        if hourly["buildup"] != want:
            w.append(f"Signal hour: {hourly['buildup'].lower()} (OI {hourly['oi_pct']:+.1f}%), not {want.lower()}")
    return w


# ------------------------------------------------------------------ proposed score (logged only)
def score_v2(idea: dict, hourly: dict | None, size: float | None, boost: float) -> dict:
    W = config.V2_WEIGHTS
    want = "Long build-up" if idea["side"] == "Long" else "Short build-up"
    day = min(abs(idea["futures"].get("pchg_oi") or 0), config.OI_CHANGE_CAP) / config.OI_CHANGE_CAP
    if hourly:
        hour = min(abs(hourly["oi_pct"]), config.V2_HOUR_OI_CAP) / config.V2_HOUR_OI_CAP if hourly["buildup"] == want else 0.0
    else:
        hour = day                                    # no snapshot yet: lean on the day's reading
    lo = (config.EF_BODY + config.EF_CLOSE_ZONE) / 2 * 100
    cl = (idea["candle_body"] + idea["candle_extremity"]) / 2 * 100
    shape = max(0.0, min(1.0, (cl - lo) / (config.V2_SHAPE_FULL - lo)))
    z = size if size is not None else 1.0            # unknown: treat as a normal-sized candle
    sz = max(0.0, min(1.0, (z - config.V2_SIZE_MIN) / (config.V2_SIZE_FULL - config.V2_SIZE_MIN)))
    parts = {"hour_oi": W["hour_oi"] * hour, "day_oi": W["day_oi"] * day,
             "shape": W["shape"] * shape, "size": W["size"] * sz}
    return {"score": round(min(100.0, sum(parts.values()) + boost), 1),
            **{k: round(v, 1) for k, v in parts.items()}, "hour_known": hourly is not None}


# ------------------------------------------------------------------ log
def log_rows(items: list[dict], kind: str, scan_ts: str) -> list[dict]:
    rows = []
    for x in items:
        lv = x.get("levels") or {}
        fut = x.get("futures") or {}
        info = {**(x.get("info") or {}), "warnings": x.get("warnings") or [], "hourly": x.get("hourly"),
                "futures": {k: fut.get(k) for k in ("buildup", "pchg_oi", "pchange")},
                "scoring": x.get("scoring"), "v2": x.get("v2"), "entry_status": x.get("entry_status"),
                "candle_ext": x.get("sig", {}).get("candle_ext"), "swing": x.get("sig", {}).get("swing"),
                "candle_body": x.get("candle_body"), "candle_extremity": x.get("candle_extremity"),
                "reason": x.get("reason"), "lot_size": x.get("lot_size")}
        rows.append({"key": f"{x['symbol']}|{x['side']}|{x['signal_time']}", "symbol": x["symbol"], "side": x["side"],
                     "signal_time": x["signal_time"], "scan_ts": scan_ts, "kind": kind,
                     "top_rank": x.get("top_rank"), "rank_v2": x.get("rank_v2"),
                     "score": (x.get("scoring") or {}).get("score"), "score_v2": (x.get("v2") or {}).get("score"),
                     "entry": lv.get("entry"), "stop": lv.get("stop"), "target": lv.get("target"), "info": info})
    return rows


def write_log(db, rows: list[dict]) -> str:
    if not rows:
        return "log: nothing new"
    db.insert_new(LOG_TABLE, rows, "key")
    return f"log: {len(rows)} signal(s) offered"


# ------------------------------------------------------------------ results
def _walk(df, e, j, d, lv, use_ema: bool):
    """Exit of a trade entered at the open of candle j+1. Returns (reason, price, time) or None."""
    entry_day = df.index[j + 1].date()
    for k in range(j + 1, len(df)):
        t = df.index[k]
        o, hi, lo, c = (float(df[x].iloc[k]) for x in ("Open", "High", "Low", "Close"))
        if d > 0:
            if lo <= lv["stop"]:
                return "stop", min(lv["stop"], o), t
            if hi >= lv["target"]:
                return "target", max(lv["target"], o), t
            if use_ema and c < float(e.iloc[k]):
                return "ema_exit", c, t
        else:
            if hi >= lv["stop"]:
                return "stop", max(lv["stop"], o), t
            if lo <= lv["target"]:
                return "target", min(lv["target"], o), t
            if use_ema and c > float(e.iloc[k]):
                return "ema_exit", c, t
        if sessions_between(entry_day, t.date()) >= config.EF_MAX_DAYS and t.strftime("%H:%M") >= "15:15":
            return "time", c, t
    return None


def evaluate(db, candles: dict[str, pd.DataFrame], now: datetime, completed_fn, ema_fn, levels_fn) -> str:
    """Fill in results for logged signals whose trade has finished."""
    rows = db.select(LOG_TABLE, {"done": "eq.false", "select": "*"})
    done = waiting = 0
    for r in rows:
        df = candles.get(r["symbol"])
        if df is None or df.empty:
            continue
        df = completed_fn(df, now)
        st = pd.Timestamp(str(r["signal_time"])[:16])
        if st not in df.index:
            if len(df) and df.index[0] > st:          # older than the candles we have: give up
                db.update(LOG_TABLE, {"id": f"eq.{r['id']}"}, {"done": True, "result": "no data"})
            continue
        j = df.index.get_loc(st)
        if j + 1 >= len(df):
            waiting += 1
            continue
        e = ema_fn(df.Close, config.EF_EMA)
        d = 1 if r["side"] == "Long" else -1
        info = r.get("info") or {}
        if info.get("candle_ext") is None or info.get("swing") is None:
            continue
        entry = float(df.Open.iloc[j + 1])
        lv = levels_fn({"dir": d, "candle_ext": info["candle_ext"], "swing": info["swing"]}, entry)
        if not lv:
            db.update(LOG_TABLE, {"id": f"eq.{r['id']}"}, {"done": True, "result": "no valid stop", "entry": entry})
            continue
        risk = abs(entry - lv["stop"])
        vals = {"entry": round(entry, 2), "stop": round(lv["stop"], 2), "target": round(lv["target"], 2)}
        main = _walk(df, e, j, d, lv, use_ema=True)
        if main and not r.get("result"):
            reason, px, t = main
            vals.update({"result": reason, "exit_price": round(px, 2), "exit_time": t.strftime("%Y-%m-%dT%H:%M"),
                         "net_pct": round((px / entry - 1) * 100 * d - config.COST_PCT, 3),
                         "r_mult": round((px - entry) * d / risk, 2)})
        alt = _walk(df, e, j, d, lv, use_ema=False)
        if alt:
            reason, px, t = alt
            k_end = df.index.get_loc(t)
            span = df.iloc[j + 1:k_end + 1]
            fav = ((span.High.max() - entry) if d > 0 else (entry - span.Low.min())) / risk
            adv = ((entry - span.Low.min()) if d > 0 else (span.High.max() - entry)) / risk
            vals.update({"alt_result": reason, "alt_net_pct": round((px / entry - 1) * 100 * d - config.COST_PCT, 3),
                         "alt_r_mult": round((px - entry) * d / risk, 2),
                         "mfe_r": round(float(fav), 2), "mae_r": round(float(adv), 2), "done": True})
        if main or alt:
            db.update(LOG_TABLE, {"id": f"eq.{r['id']}"}, vals)
            done += bool(alt)
        else:
            waiting += 1
    return f"results: {done} finished, {waiting} still running"
