"""Index view from Greeks + price (22 Nov 2026): direction, volatility regime, gamma regime.

Replaces the old 5-factor OI/PCR score on Suggested index trades. The old score lagged
because every factor measured positioning, which follows price. Here price leads:

Direction score -100..+100 = sum of weight x factor (each factor -1..+1):
    momentum  25  intraday: spot move over the last 30 min in expected-move units
                  (1.5 sigma = full); swing: today's move + the 3-day move, same units
    structure 20  intraday: place in the day's range, vs the open, vs yesterday's close;
                  swing: vs the 5- and 20-day averages of daily closes and their slope
    flow      20  delta-weighted change in OI (writers' delta), last 30 min / the day
    futures   15  futures build-up (last 60 min intraday, the day for swing); SENSEX has none
    skew      10  change in the 25-delta risk reversal: put skew rising = bearish
    ivpx      10  ATM IV against the price move: falling price + rising IV = fear (bearish),
                  rising price + rising IV = buyers chasing calls, etc.
Missing factors (no futures feed, no history yet) are left out and the weights rescaled.
Moderate at |30|, Strong at |55|. A direction also needs price to agree (momentum or
structure at least 0.15 the same way); otherwise "positions lean X, price has not moved".

Volatility regime: cheap / normal / rich from three votes: India VIX level, ATM IV vs 10-day
realised volatility, VIX rank (once 20 sessions are stored). Expanding / contracting from the
change in ATM IV (window as above) or India VIX today.

Gamma regime: call and put gamma walls (largest gamma x OI above / below the forward).
Spot between them and walls within 2.5 expected moves = range (pinning; suits selling);
spot beyond a wall = breakout (writers' hedging adds to the move); else open.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from . import config, engine, greeks


def _clip(x: float, lim: float = 1.0) -> float:
    return float(max(-lim, min(lim, x)))


def sigma_pts(spot: float, iv_pct: float, minutes: float) -> float:
    """Expected 1-sigma move in points over `minutes` of trading time."""
    return spot * iv_pct / 100.0 * math.sqrt(minutes / (config.TRADING_DAYS * config.SESSION_MIN))


def expected_move(spot: float, iv_pct: float | None, sessions: float) -> float | None:
    return spot * iv_pct / 100.0 * math.sqrt(sessions / config.TRADING_DAYS) if iv_pct else None


def _factor(key: str, name: str, reading: str, val: float | None, note: str = "") -> dict:
    return {"key": key, "factor": name, "reading": reading, "value": None if val is None else round(val, 3),
            "weight": config.EDGE_WEIGHTS[key], "note": note}


def _at_or_before(df: pd.DataFrame, t: pd.Timestamp, col: str):
    d = df[df.ts <= t]
    return None if d.empty else d.iloc[-1][col]


# ---------------------------------------------------------------------- factors
def f_momentum(mode, spot, iv, path, day_q, closes, now):
    if not iv:
        return _factor("momentum", "Price momentum", "–", None, "No IV")
    if mode == "intraday":
        t0 = pd.Timestamp(now) - pd.Timedelta(minutes=config.MOM_LOOKBACK_MIN)
        ref = _at_or_before(path, t0 + pd.Timedelta(minutes=5), "spot") if path is not None and not path.empty else None
        mins = config.MOM_LOOKBACK_MIN
        label = "last 30 min"
        if ref is None:
            ref = (day_q or {}).get("open") or (path.spot.iloc[0] if path is not None and not path.empty else None)
            open_t = datetime(now.year, now.month, now.day, 9, 15)
            mins = max(5.0, (now - open_t).total_seconds() / 60)
            label = "since the open"
        if not ref:
            return _factor("momentum", "Price momentum", "–", None, "No earlier price yet")
        move = spot - float(ref)
        z = move / sigma_pts(spot, iv, mins)
        return _factor("momentum", f"Price momentum ({label})", f"{move:+,.0f} pts ({z:+.1f}σ)", _clip(z / config.MOM_FULL_Z))
    pc = (day_q or {}).get("prev_close") or (float(closes.iloc[-1]) if closes is not None and len(closes) else None)
    if not pc:
        return _factor("momentum", "Price momentum", "–", None, "No previous close")
    z1 = (spot - pc) / sigma_pts(spot, iv, config.SESSION_MIN)
    parts, read = [z1], f"today {spot - pc:+,.0f} ({z1:+.1f}σ)"
    if closes is not None and len(closes) >= 3:
        c3 = float(closes.iloc[-3])
        z3 = (spot - c3) / sigma_pts(spot, iv, 3 * config.SESSION_MIN)
        parts.append(z3)
        read += f", 3 days {spot - c3:+,.0f} ({z3:+.1f}σ)"
    return _factor("momentum", "Price momentum (today, 3 days)", read, _clip(np.mean(parts) / config.MOM_FULL_Z))


def f_structure(mode, spot, iv, path, day_q, closes):
    if not iv:
        return _factor("structure", "Price structure", "–", None, "No IV")
    sd = sigma_pts(spot, iv, config.SESSION_MIN)
    if mode == "intraday":
        q = day_q or {}
        pts = list(path.spot) if path is not None and not path.empty else []
        hi = max([x for x in [q.get("high")] + pts if x] or [spot, spot])
        lo = min([x for x in [q.get("low")] + pts if x] or [spot, spot])
        op = q.get("open") or (pts[0] if pts else None)
        pc = q.get("prev_close")
        parts, read = [], []
        if hi - lo >= 0.3 * sd:
            loc = (spot - lo) / (hi - lo) * 2 - 1
            parts.append(loc)
            read.append(f"{(loc + 1) * 50:.0f}% up the day's range")
        if op:
            parts.append(_clip((spot - op) / (0.5 * sd)))
            read.append(f"{spot - op:+,.0f} vs open")
        if pc:
            parts.append(_clip((spot - pc) / (0.5 * sd)))
            read.append(f"{spot - pc:+,.0f} vs prev close")
        if not parts:
            return _factor("structure", "Price structure (day)", "–", None, "No day range yet")
        return _factor("structure", "Price structure (day)", ", ".join(read), _clip(float(np.mean(parts))))
    if closes is None or len(closes) < 5:
        return _factor("structure", "Price structure (5 / 20-day)", "–", None, "Needs 5+ sessions of closes")
    c = pd.concat([closes, pd.Series([spot])], ignore_index=True)
    s5, s20 = float(c.tail(5).mean()), float(c.tail(20).mean())
    parts = [_clip((spot - s20) / (2 * sd)), _clip((spot - s5) / sd), _clip((s5 - s20) / sd)]
    return _factor("structure", "Price structure (5 / 20-day)",
                   f"{spot - s5:+,.0f} vs 5-day, {spot - s20:+,.0f} vs {min(20, len(c))}-day avg", _clip(float(np.mean(parts))))


def f_flow(mode, g, past):
    use = past if mode == "intraday" else None
    v, parts = greeks.writer_flow(g, use)
    win = "last 30 min" if use is not None else "today"
    note = ("Writers adding bullish delta (puts written / calls covered)" if v > 0.1 else
            "Writers adding bearish delta (calls written / puts covered)" if v < -0.1 else "Balanced")
    return _factor("flow", f"Writer delta flow ({win})", f"calls {parts['calls']:+,.0f} · puts {parts['puts']:+,.0f} Δ-OI", _clip(v), note)


def f_futures(mode, futs, today, fut_expiry, now):
    name = "Futures build-up"
    if futs is None or futs.empty:
        return _factor("futures", name, "No futures feed", None)
    if mode == "swing":
        fd = engine.futures_day(futs, today, fut_expiry)
        if not fd:
            return _factor("futures", name, "–", None)
        return _factor("futures", f"{name} (today)", f"price {fd['fut_pct']:+.2f}%, OI {fd['coi_total']:+,.0f}",
                       engine.STATE_SCORE[fd["state"]], fd["state"])
    t1 = futs.ts.max()
    day = futs[pd.to_datetime(futs.ts).dt.date == pd.Timestamp(t1).date()]
    cands = day[day.ts <= pd.Timestamp(t1) - pd.Timedelta(minutes=config.FUT_LOOKBACK_MIN)].ts
    t0 = cands.max() if not cands.empty else (day.ts.min() if not day.empty else None)
    ch = engine.futures_change(futs, t0, t1) if t0 is not None and t0 != t1 else None
    if not ch:
        return _factor("futures", f"{name} (last 60 min)", "–", None, "Needs two snapshots today")
    st = engine.buildup_state(ch["price_pct"], ch["oi_change"])
    return _factor("futures", f"{name} (last 60 min)", f"price {ch['price_pct']:+.2f}%, OI {ch['oi_change']:+,.0f}",
                   engine.STATE_SCORE[st], st)


def _hist_ref(mode, hist, now):
    """The greeks_hist row to compare with: ~60 min earlier today (intraday) or the previous session's last (swing)."""
    if hist is None or hist.empty:
        return None
    h = hist.sort_values("ts")
    day = pd.Timestamp(now).normalize()
    if mode == "intraday":
        t0 = pd.Timestamp(now) - pd.Timedelta(minutes=config.SKEW_LOOKBACK_MIN)
        d = h[(h.ts >= day) & (h.ts <= t0 + pd.Timedelta(minutes=5))]
        return None if d.empty else d.iloc[-1]
    d = h[h.ts < day]
    return None if d.empty else d.iloc[-1]


def f_skew(mode, rr, ref):
    name = "Put skew change (25Δ)"
    if rr is None:
        return _factor("skew", name, "–", None, "Skew not measurable")
    if ref is None or ref.get("rr25") is None or not math.isfinite(float(ref.get("rr25"))):
        return _factor("skew", name, f"{rr:+.2f} vol pts", None, "No earlier reading yet")
    d = rr - float(ref["rr25"])
    note = "Downside protection getting dearer" if d > 0.2 else "Downside protection getting cheaper" if d < -0.2 else "Steady"
    return _factor("skew", name, f"{rr:+.2f} ({d:+.2f} {'60 min' if mode == 'intraday' else 'vs yesterday'})",
                   _clip(-d / config.SKEW_FULL), note)


def f_ivpx(mode, atm_iv, ref, mom_val):
    name = "IV vs price"
    if atm_iv is None or ref is None or ref.get("atm_iv") is None or mom_val is None:
        return _factor("ivpx", name, "–", None, "No earlier IV reading yet")
    d = atm_iv - float(ref["atm_iv"])
    if abs(mom_val) < 0.2:
        return _factor("ivpx", name, f"IV {d:+.2f} pts, price flat", 0.0, "Price flat")
    up = mom_val > 0
    if d >= config.IV_MOVE:
        v, note = (0.8, "Price up with IV up: buyers chasing calls") if up else (-1.0, "Price down with IV up: fear, sellers in control")
    elif d <= -config.IV_MOVE:
        v, note = (0.5, "Price up with IV easing: steady advance") if up else (-0.3, "Price down without fear: weak selling")
    else:
        v, note = (0.3 if up else -0.3), "IV steady"
    return _factor("ivpx", name, f"ATM IV {atm_iv:.1f}% ({d:+.2f})", v, note)


# ---------------------------------------------------------------------- regimes
def realised_vol(closes: pd.Series | None, n: int) -> float | None:
    if closes is None or len(closes) < n + 1:
        if closes is None or len(closes) < 6:
            return None
        n = len(closes) - 1
    r = np.log(closes.tail(n + 1).astype(float)).diff().dropna()
    return float(r.std(ddof=1) * math.sqrt(config.TRADING_DAYS) * 100) if len(r) >= 5 else None


def vol_regime(mode, atm_iv, ref, vix, rv, vix_days: pd.Series | None) -> dict:
    v, vpct = (vix or {}).get("last"), (vix or {}).get("pchange")
    votes, notes = 0, []
    if v is not None:
        if v <= config.VIX_LOW:
            votes -= 1
            notes.append(f"India VIX {v:.1f} is low")
        elif v >= config.VIX_HIGH:
            votes += 1
            notes.append(f"India VIX {v:.1f} is high")
        else:
            notes.append(f"India VIX {v:.1f} is normal")
    ivrv = atm_iv / rv if atm_iv and rv else None
    if ivrv is not None:
        if ivrv < config.IVRV_CHEAP:
            votes -= 1
            notes.append(f"IV {atm_iv:.1f}% is below 10-day realised {rv:.1f}% (cheap)")
        elif ivrv > config.IVRV_RICH:
            votes += 1
            notes.append(f"IV {atm_iv:.1f}% is well above 10-day realised {rv:.1f}% (rich)")
        else:
            notes.append(f"IV {atm_iv:.1f}% vs realised {rv:.1f}% (fair)")
    rank = None
    if v is not None and vix_days is not None and len(vix_days) >= config.VIX_RANK_MIN_DAYS:
        lo, hi = float(vix_days.min()), float(vix_days.max())
        rank = (v - lo) / (hi - lo) * 100 if hi > lo else 50.0
        if rank <= config.VIX_RANK_CHEAP:
            votes -= 1
        elif rank >= config.VIX_RANK_RICH:
            votes += 1
        notes.append(f"VIX rank {rank:.0f} of 100 over {len(vix_days)} sessions")
    state = "cheap" if votes <= -1 else "rich" if votes >= 1 else "normal"
    d_iv = atm_iv - float(ref["atm_iv"]) if atm_iv and ref is not None and ref.get("atm_iv") else None
    trend = "steady"
    if (d_iv is not None and d_iv >= config.VOL_EXPAND_IV) or (vpct is not None and vpct >= config.VIX_RISE_PCT):
        trend = "expanding"
    elif (d_iv is not None and d_iv <= -config.VOL_EXPAND_IV) or (vpct is not None and vpct <= -config.VIX_RISE_PCT):
        trend = "contracting"
    if trend != "steady":
        notes.append(f"volatility {trend}")
    return {"state": state, "trend": trend, "votes": votes, "vix": v, "vix_pct": vpct, "atm_iv": atm_iv,
            "rv10": rv, "iv_rv": ivrv, "vix_rank": rank, "d_iv": d_iv, "note": "; ".join(notes) + "."}


def gamma_regime(spot: float, info: dict, em: float | None) -> dict:
    cw, pw, pin = info.get("call_wall"), info.get("put_wall"), info.get("pin")
    out = {"call_wall": cw, "put_wall": pw, "pin": pin, "regime": "open", "near_pin": False}
    if pin and em:
        out["near_pin"] = abs(spot - pin) <= 0.25 * em
    if cw and spot > cw:
        out["regime"], out["note"] = "breakout_up", f"Spot above the call gamma wall {cw:,.0f}: call writers' hedging adds to rallies."
    elif pw and spot < pw:
        out["regime"], out["note"] = "breakout_down", f"Spot below the put gamma wall {pw:,.0f}: put writers' hedging adds to falls."
    elif cw and pw and em and (cw - pw) <= config.GAMMA_RANGE_EM * em:
        out["regime"], out["note"] = "range", f"Spot inside the gamma walls {pw:,.0f}–{cw:,.0f}: moves tend to stall (pinning)."
    else:
        out["note"] = "Gamma walls are far apart: no pinning."
    if out["near_pin"]:
        out["note"] += f" Spot is close to the pin strike {pin:,.0f}."
    return out


# ---------------------------------------------------------------------- the view
def build_view(mode: str, symbol: str, g: pd.DataFrame, info: dict, expiry, now: datetime, spot: float,
               past: pd.DataFrame | None, path: pd.DataFrame | None, day_q: dict | None, closes: pd.Series | None,
               hist: pd.DataFrame | None, futs: pd.DataFrame | None, fut_expiry, vix: dict | None,
               vix_days: pd.Series | None) -> dict:
    iv = info.get("atm_iv")
    ref = _hist_ref(mode, hist, now)
    mom = f_momentum(mode, spot, iv, path, day_q, closes, now)
    factors = [mom, f_structure(mode, spot, iv, path, day_q, closes), f_flow(mode, g, past),
               f_futures(mode, futs, now.date(), fut_expiry, now), f_skew(mode, info.get("rr25"), ref),
               f_ivpx(mode, iv, ref, mom["value"])]
    live = [f for f in factors if f["value"] is not None]
    wsum = sum(f["weight"] for f in live)
    for f in factors:
        f["points"] = round(f["value"] * f["weight"] * 100 / wsum, 1) if f["value"] is not None and wsum else None
    score = round(sum(f["points"] for f in live), 1) if wsum else 0.0
    warnings = []
    direction = "LONG" if score >= config.EDGE_MODERATE else "SHORT" if score <= -config.EDGE_MODERATE else "NEUTRAL"
    if direction != "NEUTRAL":
        sgn = 1 if direction == "LONG" else -1
        price_ok = any((f["value"] or 0) * sgn >= config.EDGE_PRICE_GATE for f in factors[:2])
        if not price_ok:
            warnings.append(f"Positions lean {'bullish' if sgn > 0 else 'bearish'} ({score:+.0f}) but price has not moved that way yet: no direction until it does.")
            direction = "NEUTRAL"
    strength = ("Strong" if abs(score) >= config.EDGE_STRONG else "Moderate") if direction != "NEUTRAL" else ""
    sessions = 1 if mode == "intraday" else config.INDEX_IDEA_SESSIONS
    em = expected_move(spot, iv, sessions)
    rv = realised_vol(closes, config.RV_DAYS)
    vol = vol_regime(mode, iv, ref, vix, rv, vix_days)
    gam = gamma_regime(spot, info, em)
    if wsum < 60:
        warnings.append("Few factors available yet (early in the day or no history): treat the score with care.")
    return {"symbol": symbol, "mode": mode, "ts": now.strftime("%Y-%m-%dT%H:%M:00"), "spot": spot,
            "fwd": info.get("fwd"), "fwd_src": info.get("fwd_src"), "expiry": str(expiry),
            "dte": (expiry - now.date()).days, "score": score, "direction": direction, "strength": strength,
            "factors": factors, "vol": vol, "gamma": gam, "em": em, "em_sessions": sessions,
            "rr25": info.get("rr25"), "iv_src": info.get("iv_src"), "warnings": warnings}
