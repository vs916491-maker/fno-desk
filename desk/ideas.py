"""Suggested index trades: Futures, Option buying and Option selling ideas (14 Nov 2026).

One call per index and mode:
    swing     monthly chain, up to 5 sessions, direction = the 5-factor swing score
    intraday  weekly chain (NIFTY, SENSEX), square off by 15:15, direction = the trend scale

Inputs: the chain (OI walls, IV, option prices), futures OI build-up, India VIX.
Display only: nothing here is logged or journaled. Every number is in desk/config.py.

Option buying   long ATM call (bullish) or put (bearish); stop = a % of the premium,
                target = ATM premium + delta x the index move to the volatility target.
Option selling  defined-risk spreads only: bull put spread (bullish), bear call spread
                (bearish), iron condor (no direction). Short strike at the OI wall or one
                expected move from spot, whichever is farther; hedge a few strikes beyond.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config, engine

BULL_STATES = ("Long build-up", "Short covering")
BEAR_STATES = ("Short build-up", "Long unwinding")


def _nearest(strikes: np.ndarray, x: float) -> float:
    return float(strikes[int(np.argmin(np.abs(strikes - x)))])


def _ltp(chain: pd.DataFrame, strike: float, kind: str) -> float | None:
    r = chain[chain.strike == strike]
    if r.empty:
        return None
    v = float(r.iloc[0][f"{kind}_ltp"] or 0)
    return v if v > 0 else None


def vol_view(vix: dict | None, atm_iv: float | None) -> dict:
    v = (vix or {}).get("last")
    chg = (vix or {}).get("pchange")
    if v is None:
        state, note = "unknown", "India VIX not available."
    elif v >= config.VIX_HIGH:
        state, note = "high", "Options are rich: favours selling premium; buying is expensive."
    elif v <= config.VIX_LOW:
        state, note = "low", "Options are cheap: favours buying; selling premium is thin."
    else:
        state, note = "normal", "Option prices are in the normal range."
    rising = bool(chg is not None and chg >= config.VIX_RISE_PCT)
    if rising:
        note += " VIX is rising today."
    return {"vix": v, "vix_pct": chg, "atm_iv": atm_iv, "state": state, "rising": rising, "note": note}


def _check(text: str, ok: bool) -> dict:
    return {"text": text, "ok": bool(ok)}


def _futures_check(bias: str, state: str | None) -> dict | None:
    if bias == "NEUTRAL" or not state:
        return None
    if bias == "LONG":
        return _check(f"Futures confirm ({state})" if state in BULL_STATES else f"Futures do not confirm ({state})",
                      state in BULL_STATES)
    return _check(f"Futures confirm ({state})" if state in BEAR_STATES else f"Futures do not confirm ({state})",
                  state in BEAR_STATES)


def _dte_check(mode: str, dte: int, selling: bool) -> dict | None:
    if mode == "swing":
        if dte < config.MONTHLY_MIN_DTE:
            return _check(f"Only {dte} days to expiry (a 5-session swing needs {config.MONTHLY_MIN_DTE}+)", False)
        return None
    if dte <= 0:
        return _check("Expiry day: prices swing fast" + (" (high risk for sellers)" if selling else " and time decay is steep"),
                      not selling)
    return None


# ---------------------------------------------------------------------- option buying
def buying_ideas(mode: str, bias: str, spot: float, chain: pd.DataFrame, lv: dict, em: float,
                 vol: dict, dte: int, fut_state: str | None) -> list[dict]:
    if bias == "NEUTRAL" or not em:
        return []
    side = 1 if bias == "LONG" else -1
    kind = "ce" if side > 0 else "pe"
    atm = _nearest(chain.strike.values, spot)
    prem = _ltp(chain, atm, kind)
    if not prem:
        return []
    stop_em = config.INTRADAY_STOP_EM if mode == "intraday" else config.SWING_STOP_EM
    target_r = config.INTRADAY_TARGET_R if mode == "intraday" else config.SWING_TARGET_R
    stop_d = stop_em * em
    tgt_d = target_r * stop_d
    tgt_spot = spot + side * tgt_d
    stop_prem = prem * (1 - config.BUY_STOP_PCT[mode] / 100)
    tgt_prem = prem + config.BUY_DELTA * tgt_d
    wall = lv.get("resistance") if side > 0 else lv.get("support")
    blocked = bool(wall and ((side > 0 and spot < wall < tgt_spot) or (side < 0 and tgt_spot < wall < spot)))
    checks = []
    fc = _futures_check(bias, fut_state)
    if fc:
        checks.append(fc)
    checks.append(_check(f"VIX {vol['vix']:.1f}: " + ("premium is expensive" if vol["state"] == "high" else "premium is reasonable"),
                         vol["state"] != "high") if vol["vix"] else _check("VIX not available", True))
    checks.append(_check(f"{'Call' if side > 0 else 'Put'} wall at {wall:,.0f} sits before the target" if blocked
                         else "No big OI wall before the target", not blocked))
    dc = _dte_check(mode, dte, selling=False)
    if dc:
        checks.append(dc)
    risk, gain = prem - stop_prem, tgt_prem - prem
    return [{
        "name": f"Buy {atm:,.0f} {'CE' if side > 0 else 'PE'}", "kind": "buy",
        "legs": [{"action": "BUY", "type": kind.upper(), "strike": atm, "ltp": prem}],
        "net": prem, "net_kind": "debit", "stop": stop_prem, "target": tgt_prem,
        "max_loss": prem, "max_profit": None, "rr": gain / risk if risk else None,
        "breakeven": [atm + side * prem], "target_spot": tgt_spot,
        "ok": all(c["ok"] for c in checks), "checks": checks,
        "why": (f"{'Bullish' if side > 0 else 'Bearish'} bias; ATM option. Stop at {config.BUY_STOP_PCT[mode]:.0f}% of the premium; "
                f"target premium assumes the index reaches about {tgt_spot:,.0f} (delta {config.BUY_DELTA})."),
        "exit": (f"Square off by {config.INTRADAY_EXIT_TIME}." if mode == "intraday"
                 else "Exit at the stop or target, or after 5 sessions; do not hold into expiry week."),
    }]


# ---------------------------------------------------------------------- option selling
def _short_strike(chain: pd.DataFrame, spot: float, wall: float | None, em: float, side: int) -> tuple[float, str]:
    """side +1 = call (above spot), -1 = put (below). Farther of the OI wall and one expected move."""
    em_k = _nearest(chain.strike.values, spot + side * config.SELL_EM_MULT * em)
    if wall is None:
        return em_k, "expected-move strike (no OI wall)"
    if side > 0:
        return (wall, "call OI wall") if wall >= em_k else (em_k, "expected-move strike (wall is closer)")
    return (wall, "put OI wall") if wall <= em_k else (em_k, "expected-move strike (wall is closer)")


def _spread(chain: pd.DataFrame, spot: float, lv: dict, em: float, mode: str, side: int):
    """One credit spread: side +1 bear call (short above spot), -1 bull put (short below)."""
    step = lv["step"]
    width = step * config.SELL_WIDTH_STEPS[mode]
    kind = "ce" if side > 0 else "pe"
    short_k, src = _short_strike(chain, spot, lv.get("resistance") if side > 0 else lv.get("support"), em, side)
    long_k = short_k + side * width
    s_p, l_p = _ltp(chain, short_k, kind), _ltp(chain, long_k, kind)
    if not s_p or not l_p or s_p <= l_p:
        return None
    return {"short": short_k, "long": long_k, "kind": kind, "s_ltp": s_p, "l_ltp": l_p,
            "credit": s_p - l_p, "width": abs(long_k - short_k), "src": src}


def selling_ideas(mode: str, bias: str, spot: float, chain: pd.DataFrame, lv: dict, em: float,
                  vol: dict, dte: int, fut_state: str | None) -> list[dict]:
    if not em:
        return []
    parts = []
    if bias == "LONG":
        name, sides = "Bull put spread", [-1]
    elif bias == "SHORT":
        name, sides = "Bear call spread", [1]
    else:
        name, sides = "Iron condor", [-1, 1]
    for sd in sides:
        sp = _spread(chain, spot, lv, em, mode, sd)
        if not sp:
            return []
        parts.append(sp)
    credit = sum(p["credit"] for p in parts)
    width = max(p["width"] for p in parts)
    max_loss = width - credit
    if max_loss <= 0:
        return []
    legs = []
    for p in parts:
        t = p["kind"].upper()
        legs += [{"action": "SELL", "type": t, "strike": p["short"], "ltp": p["s_ltp"]},
                 {"action": "BUY", "type": t, "strike": p["long"], "ltp": p["l_ltp"]}]
    be = []
    for p in parts:
        be.append(p["short"] + credit if p["kind"] == "ce" else p["short"] - credit)
    checks = []
    fc = _futures_check(bias, fut_state)
    if fc:
        checks.append(fc)
    if vol["vix"]:
        if vol["state"] == "low":
            checks.append(_check(f"VIX {vol['vix']:.1f} is low: premium is thin", False))
        else:
            checks.append(_check(f"VIX {vol['vix']:.1f}: " + ("rich premium" if vol["state"] == "high" else "premium is fair"), True))
        checks.append(_check("VIX is rising today: sellers wait for it to settle" if vol["rising"] else "VIX is not spiking",
                             not vol["rising"]))
    else:
        checks.append(_check("VIX not available", True))
    checks.append(_check(f"Credit {credit:,.1f} is {credit / width * 100:.0f}% of the {width:,.0f}-point width "
                         f"(needs {config.SELL_MIN_CREDIT * 100:.0f}%+)", credit / width >= config.SELL_MIN_CREDIT))
    if bias == "NEUTRAL":
        pcr = lv.get("pcr")
        in_range = pcr is not None and config.PCR_NEUTRAL_LOW <= pcr <= config.PCR_NEUTRAL_HIGH
        checks.append(_check(f"PCR {pcr:.2f} is in the range-bound zone" if in_range else
                             f"PCR {pcr:.2f} is outside the range-bound zone" if pcr is not None else "PCR not available",
                             bool(in_range)))
    dc = _dte_check(mode, dte, selling=True)
    if dc:
        checks.append(dc)
    sources = "; ".join(f"short {p['short']:,.0f} {p['kind'].upper()} at the {p['src']}" for p in parts)
    return [{
        "name": name, "kind": "sell", "legs": legs,
        "net": credit, "net_kind": "credit",
        "stop": min(credit * config.SELL_STOP_MULT, width), "target": credit * (1 - config.SELL_PROFIT_EXIT),
        "max_loss": max_loss, "max_profit": credit, "rr": credit / max_loss if max_loss else None,
        "breakeven": be, "width": width,
        "ok": all(c["ok"] for c in checks), "checks": checks,
        "why": f"Defined risk: {sources}; hedge {width:,.0f} points away.",
        "exit": (f"Take profit when it costs {credit * (1 - config.SELL_PROFIT_EXIT):,.1f} to close (50% of the credit); "
                 f"cut the loss at {min(credit * config.SELL_STOP_MULT, width):,.1f}. "
                 + (f"Square off by {config.INTRADAY_EXIT_TIME}." if mode == "intraday"
                    else "Close if spot closes beyond the short strike, and before expiry week.")),
    }]


# ---------------------------------------------------------------------- one index, one mode
def build(mode: str, symbol: str, snaps: pd.DataFrame, futs: pd.DataFrame | None, expiry, today,
          vix: dict | None, score: float | None, fut_expiry_ref, step_fallback: float,
          fut_trades: list | None = None) -> dict | None:
    if snaps is None or snaps.empty or score is None:
        return None
    latest = engine.split_snaps(snaps)[0]
    spot = float(latest.spot.iloc[0])
    lv = engine.chain_levels(latest, spot, step_fallback)
    fut = engine.futures_day(futs, today, fut_expiry_ref) if futs is not None and not futs.empty else None
    if fut:
        lv.update({k: fut[k] for k in ("fut_expiry", "fut_ltp", "fut_pct", "state")})
    fut_state = fut["state"] if fut else None
    thr = config.MONTHLY_MIN_SCORE if mode == "swing" else config.INTRADAY_MIN_SCORE
    bias = "LONG" if score >= thr else "SHORT" if score <= -thr else "NEUTRAL"
    days = config.SWING_DAYS if mode == "swing" else config.INTRADAY_DAYS
    iv = lv.get("atm_iv")
    em = spot * iv / 100 * math.sqrt(days / 365) if iv else None
    vol = vol_view(vix, iv)
    dte = (expiry - today).days
    if fut_trades is None:
        fut_trades = engine.swing_trades({"direction": bias, "spot": spot, "levels": lv}, days=days,
                                         stop_em=config.INTRADAY_STOP_EM, target_r=config.INTRADAY_TARGET_R)
    notes = []
    if bias == "NEUTRAL":
        notes.append("No clear direction: no futures or option-buying idea; a range-bound credit idea is shown instead.")
    if not iv:
        notes.append("ATM IV missing: option ideas skipped.")
    return {
        "symbol": symbol, "mode": mode, "ts": str(latest.ts.iloc[0]), "spot": spot, "bias": bias, "score": score,
        "threshold": thr, "expiry": str(expiry), "dte": dte, "expected_move": em, "vol": vol,
        "levels": {k: lv.get(k) for k in ("support", "resistance", "pcr", "max_pain", "atm_iv", "state",
                                           "fut_ltp", "fut_pct", "step")},
        "futures": fut_trades, "buying": buying_ideas(mode, bias, spot, latest, lv, em, vol, dte, fut_state),
        "selling": selling_ideas(mode, bias, spot, latest, lv, em, vol, dte, fut_state), "notes": notes,
    }
