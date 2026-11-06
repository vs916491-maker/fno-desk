"""Base breakout rules for the F&O stock screener (decided 6 Nov 2026).

Two screener tabs use the same chart rules:
  Price Action  chart only; futures OI is shown but not used.
  Price+OI      chart + futures OI: the build-up must surge in the breakout candle, or in
                the next candle (one-candle wait; entry then moves one candle later).
All thresholds are in desk/config.py (BB_*). The old 50 EMA cross rules still run in
desk/screener.py and are logged for the Track record.

Chart rules (Long; Short is listed separately)
  EMA state   slope of the hourly 50 EMA over the 20 candles before the signal:
              rising > +0.5%, flat within +-0.5%, falling < -0.5%.
  Base        7-30 candles before the breakout whose high-low range is at most
              1.5x the stock's average daily range (20 sessions).
  Breakout    a solid candle (body >= 50% of its range, close in the top third) closes
              above the base high and above the 50 EMA.
  Rising/flat 1st or 2nd base since price crossed the EMA (later bases are "late"),
              with 80% of the base's closes at or above the EMA.
  Falling     the 1st breakout above a falling EMA is ignored (selling not absorbed): price
              must first hold above the EMA for 7+ candles and form a base.
Short
  Falling     a base below the EMA breaks down, or a rejection: the candle's high touches the
              falling EMA and a solid bearish candle closes back below it.
  Flat        a base sitting more than 1% below the EMA (80% of its closes) breaks down.
  Rising      no shorts; the 1st breakdown below a rising EMA is ignored.
Stop   breakout candle's range >= 2% of price: beyond the candle's low (high); otherwise
       beyond the base low (high). 0.1% buffer. More than 5% from entry: skipped.
Target 1:2 (shown). Track record: stop, target or 5 sessions. Your trades: stop or by hand.

Price+OI
  Signal-hour OI  build-up in the trade's direction of at least 1.5x the stock's usual
                  hourly OI change (average over the stored snapshots; the first hour has
                  its own usual). Rising or falling EMA also needs the day's build-up in
                  the trade's direction; flat EMA scores the day's OI only.
  One-candle wait if the breakout candle has no surge, the next candle may supply it (price
                  must stay beyond the base); otherwise the setup is dropped and logged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import config

OPEN = "09:15"


def lin(x: float | None, a: float, b: float) -> float:
    if x is None:
        return 0.0
    return float(max(0.0, min(1.0, (x - a) / (b - a))))


def slope_pct(e: pd.Series, i: int) -> float | None:
    n = config.BB_SLOPE_BARS
    if i < n:
        return None
    return float(e.iloc[i] / e.iloc[i - n] - 1) * 100


def ema_state(s: float | None) -> str | None:
    if s is None:
        return None
    return "rising" if s > config.BB_FLAT_PCT else "falling" if s < -config.BB_FLAT_PCT else "flat"


def adr_pct(df: pd.DataFrame, day) -> float | None:
    """Average daily range (high - low as % of close) over the sessions before `day`."""
    prev = df[df.index.date < day]
    if prev.empty:
        return None
    g = prev.groupby(prev.index.date).agg(h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
    g = g.tail(config.BB_ADR_DAYS)
    if len(g) < 5:
        return None
    return float(((g.h - g.l) / g.c * 100).mean())


def _same_hour_ratio(df: pd.DataFrame, j: int, col: str) -> float | None:
    t, d = df.index[j].time(), df.index[j].date()
    prev = df.iloc[:j]
    same = prev[[(x.time() == t and x.date() != d) for x in prev.index]].tail(config.VOL_SESSIONS)
    if col == "range":
        vals, now = (same.High - same.Low), float(df.High.iloc[j] - df.Low.iloc[j])
    else:
        vals, now = same.Volume, float(df.Volume.iloc[j] or 0)
    vals = vals[vals > 0]
    if len(vals) < 3 or now <= 0:
        return None
    return float(now / vals.mean())


def find_bases(H: np.ndarray, L: np.ndarray, j: int, limit: float, C: np.ndarray | None = None,
               start_min: int = 0) -> list[dict]:
    """Every window of 7-30 candles ending just before candle j with range <= limit %,
    starting at or after start_min, longest first. With C: sideways windows only (the move
    from the first to the last close is at most BB_BASE_DRIFT of the range)."""
    out = []
    hi, lo = -np.inf, np.inf
    for n in range(1, config.BB_BASE_MAX + 1):
        i = j - n
        if i < max(0, start_min):
            break
        hi, lo = max(hi, H[i]), min(lo, L[i])
        rng = (hi / lo - 1) * 100
        if rng > limit:
            break
        if n >= config.BB_BASE_MIN:
            if C is not None and abs(C[j - 1] - C[i]) > config.BB_BASE_DRIFT * (hi - lo):
                continue
            out.append({"n": n, "hi": float(hi), "lo": float(lo), "rng": float(rng)})
    return out[::-1]


def detect(df: pd.DataFrame, e: pd.Series, j: int) -> list[dict]:
    """Setups whose breakout candle is j. Each has side, setup, state, reject (None = valid),
    stop, chart score parts (0-1) and details. Entry (next candle) is set by the caller.
    The longest base that qualifies is used; if none qualifies, the longest base broken
    is reported with the reason."""
    O, H, L, C = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    E = e.to_numpy(dtype=float)
    if j < config.EF_EMA + config.BB_SLOPE_BARS:
        return []
    rng = H[j] - L[j]
    if rng <= 0:
        return []
    s0 = slope_pct(e, j - 1)
    state = ema_state(s0)
    rb = config.BB_ROLL_BARS
    roll_flat = j - 1 - rb >= 0 and abs(E[j - 1] / E[j - 1 - rb] - 1) * 100 <= config.BB_ROLL_FLAT_PCT
    day = df.index[j].date()
    adr = adr_pct(df, day)
    if adr is None:
        return []
    limit = config.BB_BASE_ADR * adr
    bases = find_bases(H, L, j, limit, C)
    candle_pct = rng / C[j] * 100
    size_x, vol_x = _same_hour_ratio(df, j, "range"), _same_hour_ratio(df, j, "volume")
    out = []

    def side_share(n, end, long_):
        """Share of a window's closes on the trade's side of the EMA (Long above, Short below)."""
        return sum((C[i] >= E[i] * 0.998) if long_ else (C[i] <= E[i] * 1.002) for i in range(end - n, end)) / n

    stairs = {}

    def staircase(k, long_):
        """His base count: sideways bases on the trade's side of the EMA, broken in the trade's
        direction since price crossed the EMA at k; each new base starts after the previous
        breakout. A cross to the other side resets it (k moves). Returns (count, last breakout)."""
        if (k, long_) in stairs:
            return stairs[(k, long_)]
        count, last = 0, None
        for i in range(max(k + 1, j - config.BB_COUNT_LOOKBACK), j):
            start = (last + 1) if last is not None else k
            for bb in find_bases(H, L, i, limit, C, start):   # longest first, as the setups do
                if side_share(bb["n"], i, long_) < config.BB_BASE_HELD:
                    continue
                if (C[i] > bb["hi"] and C[i] > O[i]) if long_ else (C[i] < bb["lo"] and C[i] < O[i]):
                    count, last = count + 1, i
                    break
        stairs[(k, long_)] = (count, last)
        return count, last

    def shape(d):
        """Body and close position for a candle in direction d. A gap in the trade's
        direction counts as part of the candle: measured from the previous close."""
        o, hi, lo, pc = O[j], H[j], L[j], C[j - 1]
        if d > 0 and o > pc:
            o, lo = pc, min(lo, pc)
        elif d < 0 and o < pc:
            o, hi = pc, max(hi, pc)
        r = hi - lo
        if r <= 0:
            return 0.0, 0.5, o
        return abs(C[j] - o) / r, (C[j] - lo) / r, o

    def judge(d, b):
        """Rules for one side and one base. Returns (setup, reject, details)."""
        long_ = d > 0
        k = j
        while k > 0 and ((C[k - 1] > E[k - 1]) if long_ else (C[k - 1] < E[k - 1])):
            k -= 1
        run = j - k
        prior = ema_state(slope_pct(e, k - 1)) if k > 0 else state
        count, last = staircase(k, long_)
        base_no = count + 1
        if last is not None and j - b["n"] <= last:
            return None, "No fresh base since the previous breakout", {"prior": prior, "run": run, "base_no": base_no, "held": 0.0}
        span = range(j - b["n"], j)
        if long_:
            held = sum(C[i] >= E[i] * 0.998 for i in span) / b["n"]
        elif state == "flat":
            held = sum(C[i] <= E[i] * (1 - config.BB_FLAT_SHORT_GAP / 100) for i in span) / b["n"]
        else:
            held = sum(C[i] <= E[i] * 1.002 for i in span) / b["n"]
        held_ok = held >= config.BB_BASE_HELD
        # flattening EMA: flat over the last 7 candles, base sitting on it
        nr = config.BB_ROLL_NEAR_PCT / 100
        near = sum((C[i] >= E[i] * (1 - nr)) if long_ else (C[i] <= E[i] * (1 + nr)) for i in span) / b["n"]
        against = "falling" if long_ else "rising"
        roll_ok = (roll_flat and near >= config.BB_BASE_HELD and state in (("falling", "flat") if long_ else ("rising", "flat"))
                   and (state == against or prior == against or not held_ok))
        info = {"prior": prior, "run": run, "base_no": base_no, "held": held}
        if roll_ok:
            was = f" (was {against})" if (state == against or prior == against) else ""
            if base_no > config.BB_MAX_BASE_NO:
                return None, f"Flattening EMA, base {base_no}: late", info
            return f"Flattening EMA{was}, base {base_no}", None, info
        if long_:
            if prior == "falling" and run < config.BB_HOLD_BARS:
                return None, "Falling 50 EMA: 1st breakout above it (selling not absorbed yet)", info
            if not held_ok:
                return None, "Base not held above the 50 EMA", info
            if state == "falling":
                return "Held above a falling EMA, base breakout", None, info
        else:
            if state == "rising":
                return None, "Rising 50 EMA: no shorts (not flattening yet)", info
            if prior == "rising" and run < config.BB_HOLD_BARS:
                return None, "Rising 50 EMA: 1st breakdown below it", info
            if not held_ok:
                return None, ("Flat EMA: base not more than 1% below the EMA" if state == "flat"
                              else "Base not held below the 50 EMA"), info
        if base_no > config.BB_MAX_BASE_NO:
            return None, f"{state.title()} EMA, base {base_no}: late", info
        return f"{state.title()} EMA, base {base_no}", None, info

    for d in (1, -1):
        long_ = d > 0
        body, pos, o_eff = shape(d)
        solid = body >= config.EF_BODY and (pos >= config.EF_CLOSE_ZONE if long_ else pos <= 1 - config.EF_CLOSE_ZONE)
        if not solid or not ((C[j] > o_eff and C[j] > E[j]) if long_ else (C[j] < o_eff and C[j] < E[j])):
            continue
        broken = [b for b in bases if (C[j] > b["hi"] if long_ else C[j] < b["lo"])]
        if not broken:
            continue
        pick = None
        for b in broken:                               # longest qualifying base first
            setup, reject, info = judge(d, b)
            if setup:
                pick = (b, setup, None, info)
                break
            if pick is None:
                pick = (b, None, reject, info)         # longest base's reason, if none qualifies
        b, setup, reject, info = pick
        big = candle_pct >= config.BB_BIG_CANDLE_PCT
        ext = (L[j] if big else b["lo"]) if long_ else (H[j] if big else b["hi"])
        stop = float(ext * (1 - config.BB_STOP_BUFFER) if long_ else ext * (1 + config.BB_STOP_BUFFER))
        beyond = (C[j] / b["hi"] - 1) * 100 if long_ else (1 - C[j] / b["lo"]) * 100
        parts = {"strength": (lin(body, 0.5, 0.8) + lin(pos if long_ else 1 - pos, 2 / 3, 0.9)) / 2,
                 "size": 0.5 if size_x is None else lin(size_x, 1, 2),
                 "volume": 0.5 if vol_x is None else lin(vol_x, 1, 2),
                 "tight": 1 - lin(b["rng"] / adr, 0.5, 1.5), "length": lin(b["n"], 7, 21),
                 "ema": 1 - lin(abs(C[j] / E[j] - 1) * 100, 2, 6), "margin": lin(beyond, 0, 1)}
        out.append({"side": "Long" if long_ else "Short", "dir": d, "bar": j, "setup": setup, "reject": reject,
                    "kind": "base", "state": state, "prior": info["prior"], "slope": _r(s0), "base_no": info["base_no"],
                    "run": info["run"],
                    "base": {"n": b["n"], "hi": _r(b["hi"]), "lo": _r(b["lo"]), "range_pct": _r(b["rng"]),
                             "adr_pct": _r(adr), "held": _r(info["held"])},
                    "stop": stop, "stop_from": "breakout candle" if big else "base",
                    "level": b["hi"] if long_ else b["lo"], "candle_pct": _r(candle_pct),
                    "size_ratio": _r(size_x), "vol_ratio": _r(vol_x), "parts": parts,
                    "close": float(C[j]), "ema": float(E[j])})

    # Short: rejection at a falling 50 EMA (no base needed)
    body, pos, o_eff = shape(-1)
    solid_bear = body >= config.EF_BODY and pos <= 1 - config.EF_CLOSE_ZONE
    if (state == "falling" and solid_bear and H[j] >= E[j] * (1 - config.BB_TOUCH_PCT / 100)
            and C[j] < E[j] and C[j] < o_eff and not any(x["side"] == "Short" for x in out)):
        stop = float(H[j] * (1 + config.BB_STOP_BUFFER))
        parts = {"strength": (lin(body, 0.5, 0.8) + lin(1 - pos, 2 / 3, 0.9)) / 2,
                 "size": 0.5 if size_x is None else lin(size_x, 1, 2),
                 "volume": 0.5 if vol_x is None else lin(vol_x, 1, 2),
                 "tight": 0.5, "length": 0.5, "ema": 1.0, "margin": 0.5}
        out.append({"side": "Short", "dir": -1, "bar": j, "setup": "Falling EMA, rejection at the EMA", "reject": None,
                    "kind": "rejection", "state": state, "prior": state, "slope": _r(s0), "base_no": None, "run": 0,
                    "base": None, "stop": stop, "stop_from": "rejection candle", "level": float(L[j]),
                    "candle_pct": _r(candle_pct), "size_ratio": _r(size_x), "vol_ratio": _r(vol_x), "parts": parts,
                    "close": float(C[j]), "ema": float(E[j])})
    return out


def levels(st: dict, entry: float) -> dict | None:
    d, stop = st["dir"], st["stop"]
    risk = (entry - stop) * d
    if risk <= 0:
        return None
    return {"entry": entry, "stop": stop, "target": entry + d * config.BB_TARGET_R * risk,
            "risk_pct": risk / entry * 100, "stop_from": st["stop_from"]}


# ------------------------------------------------------------------ futures OI over a candle
def _ts(s: dict) -> datetime:
    return datetime.fromisoformat(s["ts"])


def _prev_eod(snaps: list[dict], sym: str, day, fut_now: dict | None, today) -> float | None:
    """Futures OI at the previous session's close: stored with each snapshot (OI minus
    the day's change), or from the live quote for today."""
    for s in snaps:
        if _ts(s).date() == day and sym in s["d"] and len(s["d"][sym]) > 2 and s["d"][sym][2]:
            return float(s["d"][sym][2])
    if day == today and fut_now and fut_now.get("oi_total") and fut_now.get("chg_oi_total") is not None:
        v = fut_now["oi_total"] - fut_now["chg_oi_total"]
        return float(v) if v > 0 else None
    return None


def candle_oi(snaps: list[dict], sym: str, start: pd.Timestamp, fut_now: dict | None, now: datetime) -> float | None:
    """Futures OI change (%) over one hourly candle: from the snapshot taken just after it
    opened (yesterday's closing OI for the 9:15 candle) to the one taken just after it
    closed, or the live quote if that snapshot is not there yet."""
    start = pd.Timestamp(start).to_pydatetime()
    end = min(start + timedelta(hours=1), start.replace(hour=15, minute=30))
    if start.strftime("%H:%M") == OPEN:
        oi0 = _prev_eod(snaps, sym, start.date(), fut_now, now.date())
    else:
        base = [s for s in snaps if sym in s["d"] and start - timedelta(minutes=75) <= _ts(s) <= start + timedelta(minutes=25)]
        oi0 = float(base[-1]["d"][sym][0]) if base else None
    after = [s for s in snaps if sym in s["d"] and end <= _ts(s) <= end + timedelta(minutes=25)]
    if after:
        oi1 = float(after[0]["d"][sym][0])
    elif fut_now and fut_now.get("oi_total") and end <= now <= end + timedelta(minutes=50):
        oi1 = float(fut_now["oi_total"])
    else:
        oi1 = None
    if not oi0 or not oi1:
        return None
    return (oi1 / oi0 - 1) * 100


def usual_oi(snaps: list[dict], sym: str, before: datetime, first_hour: bool) -> float | None:
    """The stock's usual hourly futures OI change (average absolute %, snapshots before
    `before`). The first hour of the day has its own usual (from yesterday's close)."""
    pts = [(_ts(s), s["d"][sym]) for s in snaps if sym in s["d"] and _ts(s) < before]
    intra, first = [], []
    for (t0, a), (t1, b) in zip(pts, pts[1:]):
        if t0.date() == t1.date() and (t1 - t0) <= timedelta(minutes=80) and a[0] and b[0]:
            intra.append(abs(b[0] / a[0] - 1) * 100)
    for t, v in pts:
        if t.strftime("%H:%M") <= "10:45" and len(v) > 2 and v[2]:
            first.append(abs(v[0] / v[2] - 1) * 100)
    if len(intra) < 4:
        return None
    u = float(np.mean(intra))
    if not first_hour:
        return u
    return float(np.mean(first)) if len(first) >= 3 else u * config.BB_FIRST_HOUR_FACTOR


def oi_check(oi_pct: float | None, usual: float | None, px_move: float, d: int) -> dict:
    """Is this candle's futures OI a same-direction surge?"""
    if oi_pct is None or not usual:
        return {"ok": False, "oi_pct": _r(oi_pct), "usual": _r(usual), "mult": None,
                "why": "no OI reading" if oi_pct is None else "no usual OI yet"}
    mult = oi_pct / usual
    if oi_pct <= 0:
        why = "OI falling (covering/unwinding)"
    elif px_move * d < 0:
        why = "price moved against the trade (opposite build-up)"
    elif mult < config.BB_OI_SURGE:
        why = f"OI +{oi_pct:.2f}% = {mult:.1f}x usual (needs {config.BB_OI_SURGE}x)"
    else:
        why = None
    return {"ok": why is None, "oi_pct": _r(oi_pct), "usual": _r(usual), "mult": _r(mult, 1), "why": why}


# ------------------------------------------------------------------ scores
def score(parts: dict, weights: dict, hour_mult: float | None = None, day_oi: float | None = None,
          day_with: bool = False, sector: bool = False) -> dict:
    p = dict(parts)
    p["hour_oi"] = (config.BB_OI_MIN_POINTS + (1 - config.BB_OI_MIN_POINTS) * lin(hour_mult, config.BB_OI_SURGE, config.BB_OI_FULL)
                    if hour_mult is not None and hour_mult >= config.BB_OI_SURGE else 0.0)
    p["day_oi"] = lin(day_oi, 0, config.BB_DAY_OI_FULL) if day_with and day_oi is not None else 0.0
    p["sector"] = 1.0 if sector else 0.0
    pts = {k: round(weights[k] * p.get(k, 0.0), 1) for k in weights if weights[k]}
    return {"score": round(min(100.0, sum(pts.values())), 1), **pts}


def _r(v, d: int = 2):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), d)
