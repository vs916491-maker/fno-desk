"""Index rules, ported from the OI Signal Desk.

Swing (monthly chain, up to 5 sessions), all five indices:
    score = OI shift (ATM +/-2, last 60 min) + PCR level + PCR intraday slope
            + change-in-OI PCR + futures OI build-up                  (-5..+5)
    LONG at >= +2.5, SHORT at <= -2.5; Strong at +/-3.5 or beyond.

NIFTY intraday trend scale (weekly chain): the four option factors
    + the futures build-up over the last 60 minutes                    (-5..+5)

Inputs are pandas frames:
    snaps  one symbol + expiry, today's snapshots: ts, spot, strike, ce_*, pe_*
    futs   futures snapshots: ts, expiry, ltp, prev_close, pchange, oi
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config


# ====================================================================== expiries
def monthly_expiries(expiries: list[date]) -> list[date]:
    last: dict = {}
    for e in sorted(expiries):
        last[(e.year, e.month)] = e
    return sorted(last.values())


def pick_monthly(expiries: list[date], today: date) -> date | None:
    for e in monthly_expiries(expiries):
        if (e - today).days >= config.MONTHLY_MIN_DTE:
            return e
    return None


def pick_weekly(expiries: list[date], today: date) -> date | None:
    for e in sorted(expiries):
        if (e - today).days >= config.WEEKLY_MIN_DTE:
            return e
    return None


# ====================================================================== helpers
def _factor(name, reading, score, note=""):
    return {"factor": name, "reading": reading, "score": round(float(score), 2), "note": note}


def strike_step(strikes, spot: float, fallback: float) -> float:
    s = np.sort(np.asarray(strikes, float))
    near = s[np.argsort(np.abs(s - spot))[:12]]
    diffs = np.diff(np.sort(near))
    diffs = diffs[diffs > 0]
    return float(pd.Series(diffs).mode().iloc[0]) if len(diffs) else float(fallback)


def pcr_series(snaps: pd.DataFrame) -> pd.DataFrame:
    g = snaps.groupby("ts").agg(ce=("ce_oi", "sum"), pe=("pe_oi", "sum"), spot=("spot", "first")).reset_index()
    g["pcr"] = np.where(g.ce > 0, g.pe / g.ce.replace(0, np.nan), np.nan)
    g["t"] = pd.to_datetime(g.ts)
    return g.dropna(subset=["pcr"])


def split_snaps(snaps: pd.DataFrame):
    """latest snapshot, the one ~60 min earlier (or the day's first), and a note."""
    ts_list = sorted(snaps.ts.unique())
    latest_ts = ts_list[-1]
    latest = snaps[snaps.ts == latest_ts].sort_values("strike").reset_index(drop=True)
    target = pd.Timestamp(latest_ts) - pd.Timedelta(minutes=config.OI_LOOKBACK_MIN)
    earlier = [t for t in ts_list if pd.Timestamp(t) <= target]
    warnings = []
    if earlier:
        past_ts = earlier[-1]
    elif len(ts_list) > 1 and (pd.Timestamp(latest_ts) - pd.Timestamp(ts_list[0])).total_seconds() >= 30 * 60:
        past_ts = ts_list[0]
        warnings.append(f"Only {int((pd.Timestamp(latest_ts) - pd.Timestamp(past_ts)).total_seconds() // 60)} "
                        "min of data today; OI shift uses that instead of 60 min.")
    else:   # under 30 minutes of data: a few minutes of OI change is noise, use the day's change
        past_ts = None
        warnings.append("Less than 30 min of snapshots today; OI shift uses the day's change in OI.")
    past = snaps[snaps.ts == past_ts].sort_values("strike") if past_ts is not None else None
    mins = int((pd.Timestamp(latest_ts) - pd.Timestamp(past_ts)).total_seconds() // 60) if past_ts is not None else 0
    mode = f"{mins} min" if past_ts is not None else "day's change"
    return latest, past, mode, warnings


# ====================================================================== the four option factors
def oi_shift(latest: pd.DataFrame, past: pd.DataFrame | None, spot: float, mode_note: str):
    strikes = latest.strike.values
    atm_idx = int(np.argmin(np.abs(strikes - spot)))
    lo, hi = max(0, atm_idx - config.ATM_WINDOW), min(len(strikes), atm_idx + config.ATM_WINDOW + 1)
    window = latest.iloc[lo:hi].strike
    if past is not None:
        m = latest.merge(past[["strike", "ce_oi", "pe_oi"]], on="strike", how="left", suffixes=("", "_p")).fillna(0)
        m["ce_d"], m["pe_d"] = m.ce_oi - m.ce_oi_p, m.pe_oi - m.pe_oi_p
    else:
        m = latest.copy()
        m["ce_d"], m["pe_d"] = m.ce_coi, m.pe_coi
    m = m.set_index("strike")
    w = m.loc[window]
    call_add, put_add = float(w.ce_d.sum()), float(w.pe_d.sum())
    above = m[m.index > spot].head(config.IMMEDIATE_LEVELS)
    below = m[m.index <= spot].tail(config.IMMEDIATE_LEVELS)
    call_unwind = float(above.ce_d.sum()) < 0
    put_unwind = float(below.pe_d.sum()) < 0
    total = abs(call_add) + abs(put_add)
    edge = (put_add - call_add) / total if total else 0.0
    score, note = 0.0, "No clear shift"
    if put_add > call_add and put_add > 0 and edge >= config.OI_SHIFT_MIN_EDGE:
        score = 1.0 if call_unwind else 0.5
        note = "Put writing leads" + (" + call unwinding at resistance" if call_unwind else " (no call unwinding yet)")
    elif call_add > put_add and call_add > 0 and -edge >= config.OI_SHIFT_MIN_EDGE:
        score = -1.0 if put_unwind else -0.5
        note = "Call writing leads" + (" + put unwinding at support" if put_unwind else " (no put unwinding yet)")
    reading = f"Put {put_add:+,.0f} vs Call {call_add:+,.0f}"
    detail = [{"strike": float(k), "call_change": float(r.ce_d), "put_change": float(r.pe_d)} for k, r in w.iterrows()]
    return (_factor(f"OI shift, ATM ±{config.ATM_WINDOW} ({mode_note})", reading, score, note),
            detail, float(strikes[atm_idx]))


def pcr_level(pcr: float):
    name = "PCR (total OI)"
    if not math.isfinite(pcr):
        return _factor(name, "–", 0.0, "No PCR")
    if pcr > config.PCR_BULL:
        if pcr > config.PCR_EXTREME_HIGH:
            return _factor(name, f"{pcr:.2f}", 0.5, "Bullish, but put writing looks crowded")
        return _factor(name, f"{pcr:.2f}", 1.0, f"Above {config.PCR_BULL:.2f}: bullish")
    if pcr < config.PCR_BEAR:
        if pcr < config.PCR_EXTREME_LOW:
            return _factor(name, f"{pcr:.2f}", -0.5, "Bearish, but call writing looks crowded")
        return _factor(name, f"{pcr:.2f}", -1.0, f"Below {config.PCR_BEAR:.2f}: bearish")
    if config.PCR_NEUTRAL_LOW <= pcr <= config.PCR_NEUTRAL_HIGH:
        return _factor(name, f"{pcr:.2f}", 0.0, "Neutral / range-bound zone")
    return _factor(name, f"{pcr:.2f}", 0.0, "Transition zone, no bias")


def pcr_slope(series: pd.DataFrame):
    name = "PCR intraday slope"
    if len(series) < config.PCR_SLOPE_MIN_POINTS:
        return _factor(name, "–", 0.0, f"Needs {config.PCR_SLOPE_MIN_POINTS}+ snapshots"), None
    span = (series.t.iloc[-1] - series.t.iloc[0]).total_seconds() / 60
    if span < config.PCR_SLOPE_MIN_SPAN_MIN:
        return _factor(name, "–", 0.0, f"Needs {config.PCR_SLOPE_MIN_SPAN_MIN}+ min of data"), None
    hours = (series.t - series.t.iloc[0]).dt.total_seconds() / 3600
    slope = float(np.polyfit(hours, series.pcr, 1)[0])
    if slope >= config.PCR_SLOPE_PER_HOUR:
        return _factor(name, f"{slope:+.3f}/hr", 1.0, "Trending up: bullish"), slope
    if slope <= -config.PCR_SLOPE_PER_HOUR:
        return _factor(name, f"{slope:+.3f}/hr", -1.0, "Trending down: bearish"), slope
    return _factor(name, f"{slope:+.3f}/hr", 0.0, "Flat"), slope


def coi_pcr(latest: pd.DataFrame):
    ce, pe = float(latest.ce_coi.sum()), float(latest.pe_coi.sum())
    name = "Change-in-OI PCR (day)"
    if ce > 0 and pe > 0:
        r = pe / ce
        if r > config.PCR_BULL:
            return _factor(name, f"{r:.2f}", 1.0, "Fresh puts outpace calls")
        if r < config.PCR_BEAR:
            return _factor(name, f"{r:.2f}", -1.0, "Fresh calls outpace puts")
        return _factor(name, f"{r:.2f}", 0.0, "Balanced additions")
    if pe > 0 >= ce:
        return _factor(name, "Puts added, calls cut", 1.0, "Bullish")
    if ce > 0 >= pe:
        return _factor(name, "Calls added, puts cut", -1.0, "Bearish")
    return _factor(name, "Both sides unwinding", 0.0, "No fresh positions")


# ====================================================================== futures
def _two_nearest(frame: pd.DataFrame, on_day: date) -> pd.DataFrame:
    alive = frame[pd.to_datetime(frame.expiry).dt.date >= on_day].sort_values("expiry")
    return alive.head(2)


def futures_change(futs: pd.DataFrame, t0, t1) -> dict | None:
    """Like-for-like OI change between two snapshot times on the current + next
    month contracts alive at both (an expiring contract is not read as an OI cut)."""
    a = futs[futs.ts == t0]
    b = futs[futs.ts == t1]
    if a.empty or b.empty:
        return None
    day1 = pd.Timestamp(t1).date()
    keep = _two_nearest(b, day1).expiry
    m = b[b.expiry.isin(keep)].merge(a[["expiry", "oi", "ltp"]], on="expiry", suffixes=("", "_0"))
    if m.empty:
        return None
    near = m.sort_values("expiry").iloc[0]
    rolled = len(a[pd.to_datetime(a.expiry).dt.date < day1]) > 0
    return {"oi_change": float((m.oi - m.oi_0).sum()), "oi_now": float(m.oi.sum()),
            "price_pct": float((near.ltp / near.ltp_0 - 1) * 100) if near.ltp_0 else 0.0,
            "rolled": rolled}


def buildup_state(pct: float, coi: float) -> str:
    if abs(pct) < config.FUT_FLAT_PCT or coi == 0:
        return "Flat"
    if pct > 0 and coi > 0:
        return "Long build-up"
    if pct < 0 and coi > 0:
        return "Short build-up"
    if pct > 0 > coi:
        return "Short covering"
    return "Long unwinding"


STATE_SCORE = {"Long build-up": 1.0, "Short build-up": -1.0, "Short covering": 0.5,
               "Long unwinding": -0.5, "Flat": 0.0}


def futures_day(futs: pd.DataFrame, today: date, target_expiry: date | None) -> dict | None:
    """Today's futures build-up: near/target contract % change vs previous close and
    OI change since the previous session's last snapshot, like-for-like."""
    if futs is None or futs.empty:
        return None
    last_ts = futs.ts.max()
    last = futs[futs.ts == last_ts].copy()
    last["exp"] = pd.to_datetime(last.expiry).dt.date
    pick = last[last.exp == target_expiry] if target_expiry else last.iloc[0:0]
    row = (pick if not pick.empty else last.sort_values("exp")).iloc[0]
    pct = float(row.pchange) if row.pchange else (float((row.ltp / row.prev_close - 1) * 100) if row.prev_close else 0.0)
    alive = _two_nearest(last, today)
    if "coi" in last and last.coi.abs().sum() > 0:
        coi = float(last.coi.sum())        # NSE's change in OI since yesterday, all months together
        src = "NSE day change, all months"
    else:
        prev_mask = pd.to_datetime(futs.ts).dt.date < today
        prev_ts = futs[prev_mask].ts.max() if prev_mask.any() else None
        ch = futures_change(futs, prev_ts, last_ts) if prev_ts is not None else None
        coi = ch["oi_change"] if ch else 0.0
        src = "since previous session" if ch else "no previous session yet"
    return {"fut_expiry": str(row.exp), "fut_ltp": float(row.ltp), "fut_pct": pct,
            "oi_total": float(alive.oi.sum()), "coi_total": coi, "source": src,
            "state": buildup_state(pct, coi)}


def futures_factor(info: dict | None):
    name = "Futures OI build-up"
    if not info:
        return _factor(name, "No data", 0.0, "No futures feed, factor skipped")
    reading = f"Price {info['fut_pct']:+.2f}%, OI {info['coi_total']:+,.0f}"
    return _factor(name, reading, STATE_SCORE[info["state"]], info["state"])


def interpret(fut_state: str | None, oi_score: float, levels: dict) -> str:
    if not fut_state or fut_state == "Flat":
        return "Futures give no confirmation; the call rests on option data alone."
    opt = "bullish" if oi_score > 0 else "bearish" if oi_score < 0 else "neutral"
    r, s = levels.get("resistance"), levels.get("support")
    fr = lambda x: f"{x:,.0f}" if x else "–"  # noqa: E731
    combos = {
        ("Long build-up", "bullish"): "Fresh longs in futures plus put writing: strongest bullish alignment.",
        ("Short build-up", "bearish"): "Fresh shorts in futures plus call writing: strongest bearish alignment.",
        ("Short covering", "bullish"): "Rally is short covering backed by put writing; follow-through is less certain than a long build-up.",
        ("Long unwinding", "bearish"): "Longs exiting while calls are written; weakness, but without fresh shorts.",
        ("Long build-up", "bearish"): f"Futures longs are adding but option writers cap the upside near {fr(r)}; wait for one side to give way.",
        ("Short build-up", "bullish"): f"Futures shorts are adding against put writers defending {fr(s)}; conflicting, size down.",
        ("Short covering", "bearish"): f"Short covering rally running into call writers at {fr(r)}; likely to stall there.",
        ("Long unwinding", "bullish"): f"Longs exiting while puts are written at {fr(s)}; dip may hold, but momentum is weak.",
    }
    return combos.get((fut_state, opt), f"Futures show {fut_state.lower()}; option flow is {opt}.")


# ====================================================================== chain summaries
def atm_iv(chain: pd.DataFrame, spot: float) -> float | None:
    c = chain.assign(d=(chain.strike - spot).abs()).sort_values("d")
    for _, r in c.head(3).iterrows():
        ivs = [v for v in (r.ce_iv, r.pe_iv) if v and v > 0]
        if ivs:
            return float(sum(ivs) / len(ivs))
    return None


def max_pain(chain: pd.DataFrame) -> float | None:
    if chain.empty:
        return None
    k = chain.strike.values
    ce, pe = chain.ce_oi.values, chain.pe_oi.values
    pain = [float((ce * np.maximum(0, x - k)).sum() + (pe * np.maximum(0, k - x)).sum()) for x in k]
    return float(k[int(np.argmin(pain))])


def chain_levels(latest: pd.DataFrame, spot: float, step_fallback: float) -> dict:
    above, below = latest[latest.strike > spot], latest[latest.strike <= spot]
    pcr = float(latest.pe_oi.sum() / latest.ce_oi.sum()) if latest.ce_oi.sum() else float("nan")
    return {
        "pcr": round(pcr, 3) if math.isfinite(pcr) else None,
        "step": strike_step(latest.strike.values, spot, step_fallback),
        "resistance": float(above.loc[above.ce_oi.idxmax(), "strike"]) if not above.empty and above.ce_oi.max() > 0 else None,
        "support": float(below.loc[below.pe_oi.idxmax(), "strike"]) if not below.empty and below.pe_oi.max() > 0 else None,
        "max_pain": max_pain(latest),
        "atm_iv": atm_iv(latest, spot),
    }


# ====================================================================== swing signal
def swing_signal(symbol: str, snaps: pd.DataFrame, futs: pd.DataFrame | None, expiry: date, today: date) -> dict:
    base = {"symbol": symbol, "direction": "NO DATA", "score": 0.0, "factors": [], "levels": {},
            "expiry": str(expiry) if expiry else None, "warnings": [], "trades": []}
    if snaps is None or snaps.empty:
        base["warnings"].append("No option chain snapshots yet today.")
        return base
    latest, past, mode, warnings = split_snaps(snaps)
    spot = float(latest.spot.iloc[0])
    f_oi, oi_detail, atm = oi_shift(latest, past, spot, mode)
    lv = chain_levels(latest, spot, config.INDICES[symbol]["strike_step"])
    lv["atm"] = atm
    f_pcr = pcr_level(lv["pcr"] if lv["pcr"] is not None else float("nan"))
    f_slope, slope = pcr_slope(pcr_series(snaps))
    f_coi = coi_pcr(latest)
    fut = futures_day(futs, today, expiry) if futs is not None and not futs.empty else None
    f_fut = futures_factor(fut)
    factors = [f_oi, f_pcr, f_slope, f_coi, f_fut]
    score = round(sum(f["score"] for f in factors), 2)
    thr = config.MONTHLY_MIN_SCORE
    direction = "LONG" if score >= thr else "SHORT" if score <= -thr else "NO TRADE"
    strength = ("Strong" if abs(score) >= thr + config.STRONG_EXTRA else "Moderate") if direction != "NO TRADE" else ""
    if f_oi["score"] * f_pcr["score"] < 0:
        warnings.append("OI shift and PCR point in opposite directions.")
    if fut:
        lv.update({k: fut[k] for k in ("fut_expiry", "fut_ltp", "fut_pct", "state")})
    lv["interpretation"] = interpret(fut["state"] if fut else None, f_oi["score"], lv)
    sig = {**base, "ts": str(latest.ts.iloc[0]), "spot": spot, "score": score, "threshold": thr,
           "direction": direction, "strength": strength, "factors": factors, "levels": lv,
           "dte": (expiry - today).days, "warnings": warnings, "oi_detail": oi_detail, "slope": slope}
    sig["trades"] = swing_trades(sig)
    return sig


def swing_trades(sig: dict) -> list[dict]:
    """Futures trade levels by two methods: OI walls, and the 5-day volatility move."""
    d = sig["direction"]
    if d not in ("LONG", "SHORT"):
        return []
    lv, spot = sig["levels"], sig["spot"]
    side = 1 if d == "LONG" else -1
    fut = lv.get("fut_ltp") or spot
    basis = fut - spot if lv.get("fut_ltp") else 0.0
    out = []
    s, r = lv.get("support"), lv.get("resistance")
    stop_k, tgt_k = (s, r) if side > 0 else (r, s)
    if stop_k and tgt_k:
        risk, reward = abs(spot - stop_k), abs(tgt_k - spot)
        rr = reward / risk if risk else None
        out.append({"method": "OI walls", "entry": fut, "stop": stop_k + basis, "target": tgt_k + basis,
                    "stop_spot": stop_k, "target_spot": tgt_k, "rr": rr,
                    "ok": bool(rr and rr >= config.SWING_MIN_RR),
                    "note": (f"Stop at the {'put' if side > 0 else 'call'} wall {stop_k:,.0f}, "
                             f"target at the {'call' if side > 0 else 'put'} wall {tgt_k:,.0f}"
                             + ("" if rr and rr >= config.SWING_MIN_RR else f"; R/R below {config.SWING_MIN_RR}"))})
    iv = lv.get("atm_iv")
    if iv:
        em = spot * iv / 100 * math.sqrt(config.SWING_DAYS / 365)
        stop_d = config.SWING_STOP_EM * em
        tgt_d = config.SWING_TARGET_R * stop_d
        tgt_spot = spot + side * tgt_d
        wall = r if side > 0 else s
        blocked = bool(wall and ((side > 0 and spot < wall < tgt_spot) or (side < 0 and tgt_spot < wall < spot)))
        out.append({"method": "Volatility", "entry": fut, "stop": fut - side * stop_d, "target": fut + side * tgt_d,
                    "stop_spot": spot - side * stop_d, "target_spot": tgt_spot, "rr": config.SWING_TARGET_R,
                    "ok": not blocked, "expected_move": em, "iv": iv,
                    "note": (f"5-day expected move ±{em:,.0f} at IV {iv:.1f}%"
                             + (f"; the {'call' if side > 0 else 'put'} wall at {wall:,.0f} sits before the target"
                                if blocked else ""))})
    return out


# ====================================================================== NIFTY intraday trend scale
def trend_scale(snaps: pd.DataFrame, futs: pd.DataFrame | None) -> dict | None:
    if snaps is None or snaps.empty:
        return None
    latest, past, mode, warnings = split_snaps(snaps)
    spot = float(latest.spot.iloc[0])
    f_oi, _, _ = oi_shift(latest, past, spot, mode)
    lv = chain_levels(latest, spot, 50)
    factors = [f_oi, pcr_level(lv["pcr"] if lv["pcr"] is not None else float("nan")),
               pcr_slope(pcr_series(snaps))[0], coi_pcr(latest)]
    name = "Futures build-up, last 60 min"
    if futs is not None and not futs.empty:
        t1 = futs.ts.max()
        cands = futs[futs.ts <= pd.Timestamp(t1) - pd.Timedelta(minutes=config.OI_LOOKBACK_MIN)].ts
        cands = cands[pd.to_datetime(cands).dt.date == pd.Timestamp(t1).date()]
        t0 = cands.max() if not cands.empty else futs[pd.to_datetime(futs.ts).dt.date == pd.Timestamp(t1).date()].ts.min()
        ch = futures_change(futs, t0, t1) if t0 is not None and t0 != t1 else None
        if ch:
            st = buildup_state(ch["price_pct"], ch["oi_change"])
            factors.append(_factor(name, f"Price {ch['price_pct']:+.2f}%, OI {ch['oi_change']:+,.0f}", STATE_SCORE[st], st))
        else:
            factors.append(_factor(name, "–", 0.0, "Needs two snapshots today"))
    else:
        factors.append(_factor(name, "No data", 0.0, "No futures feed"))
    score = round(sum(f["score"] for f in factors), 2)
    zone = "Neutral"
    for cut, label in config.TREND_ZONES:
        if abs(score) >= cut:
            zone = f"{label} {'bullish' if score > 0 else 'bearish'}"
            break
    return {"score": score, "zone": zone, "factors": factors, "ts": str(latest.ts.iloc[0])}


# ====================================================================== warnings
def squeeze_warning(snaps: pd.DataFrame, symbol: str) -> str | None:
    if snaps is None or snaps.empty:
        return None
    latest, past, _, _ = split_snaps(snaps)
    if past is None:
        return None
    spot, spot0 = float(latest.spot.iloc[0]), float(past.spot.iloc[0])
    move = (spot / spot0 - 1) * 100 if spot0 else 0.0
    pcr = float(latest.pe_oi.sum() / latest.ce_oi.sum()) if latest.ce_oi.sum() else float("nan")
    pcr0 = float(past.pe_oi.sum() / past.ce_oi.sum()) if past.ce_oi.sum() else float("nan")
    m = latest.merge(past[["strike", "ce_oi", "pe_oi"]], on="strike", suffixes=("", "_p"))
    atm_i = int(np.argmin(np.abs(m.strike.values - spot)))
    if pcr <= config.SQUEEZE_PCR_LOW and move >= config.SQUEEZE_SPOT_MOVE and pcr > pcr0:
        z = m.iloc[atm_i: atm_i + 3]
        fall = float((z.ce_oi - z.ce_oi_p).sum())
        if fall < 0:
            return (f"Short-covering squeeze risk on {symbol}: call OI at {z.strike.min():,.0f}–{z.strike.max():,.0f} "
                    f"fell by {abs(fall):,.0f} over the last 60 min while spot rose {move:+.2f}% (PCR {pcr:.2f}).")
    if pcr >= config.SQUEEZE_PCR_HIGH and move <= -config.SQUEEZE_SPOT_MOVE and pcr < pcr0:
        z = m.iloc[max(0, atm_i - 2): atm_i + 1]
        fall = float((z.pe_oi - z.pe_oi_p).sum())
        if fall < 0:
            return (f"Put-writer covering risk on {symbol}: put OI at {z.strike.min():,.0f}–{z.strike.max():,.0f} "
                    f"fell by {abs(fall):,.0f} over the last 60 min while spot fell {move:+.2f}% (PCR {pcr:.2f}).")
    return None


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def expiry_warning(symbol: str, nearest: date | None, today: date) -> str | None:
    if not nearest:
        return None
    if nearest == today:
        return f"Expiry day for {symbol} ({nearest:%d %b}): OI shift and change-in-OI readings are less reliable as positions close or roll."
    if nearest == next_weekday(today):
        return f"Expiry eve for {symbol}: contracts expire {nearest:%a %d %b}; OI readings are less reliable as positions roll."
    return None


# ====================================================================== hourly charts
def hourly_last(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """Last record in each market hour (09:15-10:14 -> 10:15 point, etc.)."""
    if df.empty:
        return df
    d = df.copy()
    d["t"] = pd.to_datetime(d.ts)
    d["hour"] = (d.t - pd.Timedelta(minutes=15)).dt.floor("h") + pd.Timedelta(minutes=15)
    return d.sort_values("t").groupby("hour").tail(1)


def futures_hourly(futs: pd.DataFrame) -> list[dict]:
    """Hourly combined current + next month OI with like-for-like change bars."""
    if futs is None or futs.empty:
        return []
    ts = pd.Series(sorted(futs.ts.unique()))
    t = pd.to_datetime(ts)
    hour = (t - pd.Timedelta(minutes=15)).dt.floor("h") + pd.Timedelta(minutes=15)
    picks = ts.groupby(hour.values).last().tolist()
    out, prev = [], None
    for p in picks:
        snap = futs[futs.ts == p]
        alive = _two_nearest(snap, pd.Timestamp(p).date())
        point = {"ts": str(p), "oi": float(alive.oi.sum()),
                 "near_ltp": float(alive.sort_values("expiry").ltp.iloc[0]) if not alive.empty else None,
                 "change": None, "rolled": False}
        if prev is not None:
            ch = futures_change(futs, prev, p)
            if ch:
                point["change"], point["rolled"] = ch["oi_change"], ch["rolled"]
        out.append(point)
        prev = p
    return out
