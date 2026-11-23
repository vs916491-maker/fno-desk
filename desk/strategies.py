"""Strategy picker for Suggested index trades (22 Nov 2026).

Takes the index view (desk/edge.py) and the chain with Greeks (desk/greeks.py) and builds
the structures that fit the market. Strikes are picked by delta, not by fixed distance.

    Direction   Volatility        Main fits
    Strong      cheap / normal    Option buying, Futures + protective option
    Moderate    any               Debit spread; Credit spread when IV is rich
    Any dir.    rich              Credit spread, Futures + covered option
    None        rich / normal     Iron condor (range), Short strangle with wings, delta-hedged
    Any         cheap / expanding Long straddle, delta-hedged

Every idea carries its legs (with Greeks), net premium, position Greeks per unit, maximum
profit / loss and breakevens at expiry, the checks it passes or fails, and its exit rules
(stop / target as P&L per unit, time exit, delta hedging). The Index Track Record and
My Index Trades use the same rules. Numbers: ST_*, DH_* in desk/config.py.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config, greeks

GROUP = {"long_option": "Option buying", "debit_spread": "Option spread", "credit_spread": "Option selling",
         "fut_protect": "Futures with hedge", "fut_cover": "Futures with hedge", "iron_condor": "Option selling",
         "strangle_dh": "Option selling, delta-hedged", "straddle_dh": "Option buying, delta-hedged"}


def _sign(leg) -> int:
    return 1 if leg["action"] == "BUY" else -1


def _leg_from_row(r: pd.Series, kind: str, action: str, expiry: str) -> dict:
    k = kind.lower()
    return {"action": action, "type": kind, "strike": float(r.strike), "expiry": expiry,
            "ltp": float(r[f"{k}_ltp"]), "iv": float(r.iv) * 100 if math.isfinite(r.iv) else None,
            "delta": float(r[f"{k}_delta"]), "gamma": float(r.gamma), "theta": float(r[f"{k}_theta"]),
            "vega": float(r.vega)}


def opt_leg(g, kind, target, action, expiry):
    r = greeks.strike_for_delta(g, kind, target)
    return None if r is None else _leg_from_row(r, kind, action, expiry)


def leg_at(g, kind, strike, action, expiry):
    r = g[g.strike == strike]
    if r.empty or not float(r.iloc[0][f"{kind.lower()}_ltp"]) > 0:
        return None
    return _leg_from_row(r.iloc[0], kind, action, expiry)


def fut_legs(action: str, fut: dict | None, g: pd.DataFrame, fwd: float, expiry: str) -> list[dict] | None:
    """Index futures leg; SENSEX (no futures feed) uses a synthetic future: ATM call and put."""
    if fut and fut.get("ltp"):
        return [{"action": action, "type": "FUT", "strike": None, "expiry": fut.get("expiry") or expiry,
                 "ltp": float(fut["ltp"]), "delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "iv": None,
                 "basis": float(fut["ltp"]) - fwd}]
    atm = float(g.strike.values[int(np.argmin(np.abs(g.strike.values - fwd)))])
    other = "SELL" if action == "BUY" else "BUY"
    c, p = leg_at(g, "CE", atm, action, expiry), leg_at(g, "PE", atm, other, expiry)
    if not c or not p:
        return None
    c["synthetic"] = p["synthetic"] = True
    return [c, p]


# ---------------------------------------------------------------------- position maths
def pos_greeks(legs: list[dict]) -> dict:
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        q = _sign(l) * l.get("qty", 1)
        for k in out:
            out[k] += q * float(l.get(k) or 0)
    return {k: round(v, 5) for k, v in out.items()}


def net_premium(legs) -> float:
    """Positive = you pay (debit), negative = you receive (credit). Futures excluded."""
    return float(sum(_sign(l) * l.get("qty", 1) * l["ltp"] for l in legs if l["type"] != "FUT"))


def payoff(legs, S: np.ndarray) -> np.ndarray:
    out = np.zeros_like(S, dtype=float)
    for l in legs:
        q = _sign(l) * l.get("qty", 1)
        if l["type"] == "FUT":
            out += q * (S - l["ltp"])
        elif l["type"] == "CE":
            out += q * (np.maximum(S - l["strike"], 0) - l["ltp"])
        else:
            out += q * (np.maximum(l["strike"] - S, 0) - l["ltp"])
    return out


def risk_profile(legs, spot, em) -> dict:
    ks = [l["strike"] for l in legs if l.get("strike")] + [spot]
    span = max(em or spot * 0.03, spot * 0.01) * 4
    S = np.linspace(min(ks) - span, max(ks) + span, 801)
    p = payoff(legs, S)
    lo_slope, hi_slope = p[1] - p[0], p[-1] - p[-2]
    max_loss = None if (lo_slope > 1e-9 or hi_slope < -1e-9) else float(-p.min())
    max_profit = None if (lo_slope < -1e-9 or hi_slope > 1e-9) else float(p.max())
    be = []
    for i in range(len(S) - 1):
        if p[i] == 0 or (p[i] < 0) != (p[i + 1] < 0):
            x = S[i] if p[i] == 0 else S[i] - p[i] * (S[i + 1] - S[i]) / (p[i + 1] - p[i])
            if not be or abs(x - be[-1]) > 1:
                be.append(round(float(x), 1))
    return {"max_loss": max_loss if max_loss is None or max_loss > 0 else 0.0,
            "max_profit": max_profit, "breakeven": be[:2]}


def revalue(legs, F_new: float, T: float) -> float:
    """P&L per unit if the forward moved to F_new now (same IV, same time)."""
    pnl = 0.0
    for l in legs:
        q = _sign(l) * l.get("qty", 1)
        if l["type"] == "FUT":
            now = F_new + float(l.get("basis") or 0)
        else:
            now = greeks.price(F_new, l["strike"], T, (l.get("iv") or 15) / 100, l["type"])
        pnl += q * (now - l["ltp"])
    return pnl


def _check(text, ok):
    return {"text": text, "ok": bool(ok)}


# ---------------------------------------------------------------------- the picker
def build_ideas(view: dict, g: pd.DataFrame, info: dict, fut: dict | None, levels: dict, now) -> list[dict]:
    mode, bias, strength = view["mode"], view["direction"], view["strength"]
    vol, gam, em, spot = view["vol"], view["gamma"], view["em"], view["spot"]
    fwd, T, exp = info.get("fwd") or spot, info.get("T"), view["expiry"]
    if not em or g is None or g.empty or not g.iv.notna().any():
        return []
    V, VT, G = vol["state"], vol["trend"], gam["regime"]
    side = 1 if bias == "LONG" else -1 if bias == "SHORT" else 0
    dte = view["dte"]
    late = mode == "intraday" and now.strftime("%H:%M") >= "14:00"
    ideas = []

    def dte_check():
        if mode == "swing":
            return _check(f"{dte} days to expiry (needs {config.ST_SWING_MIN_DTE}+ for a 5-session swing)",
                          dte >= config.ST_SWING_MIN_DTE)
        return _check("After 2 pm: little time left for an intraday move" if late else "Time left in the session", not late)

    def add(key, name, legs, checks, fit, why, rules):
        if not legs or any(l is None for l in legs):
            return
        net = net_premium(legs)
        prof = risk_profile(legs, spot, em)
        ideas.append({"strategy": key, "group": GROUP[key], "name": name, "bias": bias, "legs": legs,
                      "net": round(abs(net), 2), "net_kind": "debit" if net >= 0 else "credit",
                      "greeks": pos_greeks(legs), **prof, "checks": checks,
                      "ok": all(c["ok"] for c in checks), "fit": fit, "why": why, "rules": rules})

    stop_em = config.ST_STOP_EM[mode]
    # ------------------------------------------------ directional
    if side:
        kind, okind = ("CE", "PE") if side > 0 else ("PE", "CE")
        word = "call" if side > 0 else "put"
        # obstacle = the OI wall in the trade's way (max call OI above for longs, max put OI below for shorts).
        # Gamma walls are not used here: gamma x OI peaks at the strikes next to spot, so one sits
        # before almost every target (23 Nov 2026: that failed nearly every directional idea).
        wall = (levels or {}).get("resistance") if side > 0 else (levels or {}).get("support")
        tgt_spot = spot + side * config.ST_TARGET_R * stop_em * em
        blocked = bool(wall and ((side > 0 and spot < wall < tgt_spot) or (side < 0 and tgt_spot < wall < spot)))
        wall_chk = _check(f"{'Call' if side > 0 else 'Put'} OI wall {wall:,.0f} sits before the target {tgt_spot:,.0f}" if blocked
                          else f"No OI wall before the target {tgt_spot:,.0f}", not blocked)
        # 1. option buying
        L = opt_leg(g, kind, config.ST_BUY_DELTA, "BUY", exp)
        if L:
            stop = -config.ST_BUY_STOP[mode] * L["ltp"]
            fit = {("Strong", "cheap"): 95, ("Strong", "normal"): 85, ("Moderate", "cheap"): 75,
                   ("Moderate", "normal"): 60}.get((strength, V), 30)
            add("long_option", f"Buy {L['strike']:,.0f} {kind}", [L],
                [_check("IV is not rich" if V != "rich" else "IV is rich: premium is expensive, a spread suits better", V != "rich"),
                 _check("IV is not falling" if VT != "contracting" else "IV is falling: premium melts even if price moves", VT != "contracting"),
                 wall_chk, dte_check()], fit,
                f"{strength} {'bullish' if side > 0 else 'bearish'} view; delta {L['delta']:+.2f} option. "
                f"Stop at {config.ST_BUY_STOP[mode] * 100:.0f}% of the premium, target {config.ST_TARGET_R}x that.",
                {"stop_pnl": stop, "target_pnl": -stop * config.ST_TARGET_R})
        # 2. debit spread
        B = opt_leg(g, kind, config.ST_BUY_DELTA, "BUY", exp)
        S_ = opt_leg(g, kind, config.ST_DEBIT_SHORT_DELTA, "SELL", exp)
        if B and S_ and S_["strike"] != B["strike"] and (S_["strike"] - B["strike"]) * side > 0:
            debit = B["ltp"] - S_["ltp"]
            width = abs(S_["strike"] - B["strike"])
            if debit > 0:
                stop = -config.ST_DEBIT_STOP * debit
                tgt = min(-stop * config.ST_TARGET_R, 0.9 * (width - debit))
                fit = {("Moderate", "normal"): 80, ("Moderate", "rich"): 80, ("Strong", "rich"): 85,
                       ("Strong", "normal"): 70}.get((strength, V), 55)
                add("debit_spread", f"{'Bull call' if side > 0 else 'Bear put'} spread {B['strike']:,.0f}/{S_['strike']:,.0f}",
                    [B, S_], [_check(f"Reward {width - debit:,.0f} vs debit {debit:,.0f}", width - debit >= debit),
                              wall_chk, dte_check()], fit,
                    f"Directional with the short leg paying for part of the IV. Stop at {config.ST_DEBIT_STOP * 100:.0f}% of the debit.",
                    {"stop_pnl": stop, "target_pnl": tgt})
        # 3. credit spread (sell the other side)
        Sh = opt_leg(g, okind, config.ST_CREDIT_SHORT_DELTA, "SELL", exp)
        Wg = opt_leg(g, okind, config.ST_CREDIT_WING_DELTA, "BUY", exp)
        if Sh and Wg and (Sh["strike"] - Wg["strike"]) * side > 0:
            credit = Sh["ltp"] - Wg["ltp"]
            width = abs(Sh["strike"] - Wg["strike"])
            if credit > 0:
                wall2 = gam.get("put_wall") if side > 0 else gam.get("call_wall")
                behind = bool(wall2 and ((side > 0 and Sh["strike"] <= wall2) or (side < 0 and Sh["strike"] >= wall2)))
                fit = {("Moderate", "rich"): 85, ("Strong", "rich"): 75}.get((strength, V), 65 if V == "normal" else 35)
                add("credit_spread", f"{'Bull put' if side > 0 else 'Bear call'} spread {Sh['strike']:,.0f}/{Wg['strike']:,.0f}",
                    [Sh, Wg], [_check("IV is not cheap" if V != "cheap" else "IV is cheap: thin premium for the risk", V != "cheap"),
                               _check("Volatility is not expanding" if VT != "expanding" else "Volatility is expanding: sellers wait", VT != "expanding"),
                               _check(f"Credit {credit:,.1f} is {credit / width * 100:.0f}% of the width (needs {config.ST_MIN_CREDIT_WIDTH * 100:.0f}%+)",
                                      credit / width >= config.ST_MIN_CREDIT_WIDTH),
                               _check(f"Short strike {'behind' if behind else 'in front of'} the {'put' if side > 0 else 'call'} gamma wall", behind),
                               dte_check()], fit,
                    f"Defined risk; short delta {abs(Sh['delta']):.2f}, hedge delta {abs(Wg['delta']):.2f}. Wins if price holds or moves your way.",
                    {"stop_pnl": -min(config.ST_CREDIT_SL * credit, 0.9 * (width - credit)), "target_pnl": config.ST_CREDIT_TP * credit})
        # 4. futures + protective option ;  5. futures + covered option
        F_legs = fut_legs("BUY" if side > 0 else "SELL", fut, g, fwd, exp)
        sstop, stgt = spot - side * stop_em * em, spot + side * config.ST_TARGET_R * stop_em * em
        spot_rules = lambda legs: {"spot_stop": round(sstop, 1), "spot_target": round(stgt, 1),  # noqa: E731
                                   "stop_pnl": revalue(legs, fwd + (sstop - spot), T),
                                   "target_pnl": revalue(legs, fwd + (stgt - spot), T)}
        if F_legs:
            P = opt_leg(g, okind, config.ST_HEDGE_PUT_DELTA, "BUY", exp)
            if P:
                legs = F_legs + [P]
                # the hedge is sold back on exit, so its real cost is the time decay over the hold
                hold_days = 1 if mode == "intraday" else 7
                carry = abs(P["theta"]) * hold_days
                cost_ok = carry <= config.ST_HEDGE_CARRY_MAX * em
                fit = {("Strong", "cheap"): 90, ("Strong", "normal"): 80}.get((strength, V), 70 if G.startswith("breakout") else 55)
                add("fut_protect", f"{'Long' if side > 0 else 'Short'} futures + buy {P['strike']:,.0f} {okind}", legs,
                    [_check(f"Hedge decay {carry:,.0f} over the hold = {carry / em * 100:.0f}% of the expected move (max {config.ST_HEDGE_CARRY_MAX * 100:.0f}%)", cost_ok),
                     wall_chk, dte_check()], fit,
                    f"Futures for the full move; the {'put' if side > 0 else 'call'} caps the loss if the view is wrong."
                    + (" SENSEX has no futures feed: the future is a synthetic (ATM call and put)." if F_legs[0]["type"] != "FUT" else ""),
                    spot_rules(legs))
            C = opt_leg(g, kind, config.ST_COVER_DELTA, "SELL", exp)
            if C:
                legs = F_legs + [C]
                fit = {("Moderate", "rich"): 75, ("Strong", "rich"): 65}.get((strength, V), 40)
                add("fut_cover", f"{'Long' if side > 0 else 'Short'} futures + sell {C['strike']:,.0f} {kind}", legs,
                    [_check("IV is rich: the sold option pays well" if V == "rich" else "IV is not rich: little to collect", V == "rich"),
                     _check("Volatility is not expanding" if VT != "expanding" else "Volatility is expanding", VT != "expanding"),
                     dte_check()], fit,
                    f"Futures with a sold {word} to collect rich premium; gains capped near {C['strike']:,.0f}. Stop on spot.",
                    spot_rules(legs))
    # ------------------------------------------------ no direction
    else:
        Sc, Sp = opt_leg(g, "CE", config.ST_CONDOR_SHORT_DELTA, "SELL", exp), opt_leg(g, "PE", config.ST_CONDOR_SHORT_DELTA, "SELL", exp)
        Wc, Wp = opt_leg(g, "CE", config.ST_CONDOR_WING_DELTA, "BUY", exp), opt_leg(g, "PE", config.ST_CONDOR_WING_DELTA, "BUY", exp)
        if all([Sc, Sp, Wc, Wp]) and Wc["strike"] > Sc["strike"] and Wp["strike"] < Sp["strike"]:
            credit = Sc["ltp"] + Sp["ltp"] - Wc["ltp"] - Wp["ltp"]
            width = max(Wc["strike"] - Sc["strike"], Sp["strike"] - Wp["strike"])
            if credit > 0:
                fit = {("rich", "range"): 90, ("normal", "range"): 75, ("rich", "open"): 70}.get((V, G), 50)
                add("iron_condor", f"Iron condor {Wp['strike']:,.0f}/{Sp['strike']:,.0f} – {Sc['strike']:,.0f}/{Wc['strike']:,.0f}",
                    [Sp, Wp, Sc, Wc],
                    [_check("IV is not cheap" if V != "cheap" else "IV is cheap: thin premium", V != "cheap"),
                     _check("Volatility is not expanding" if VT != "expanding" else "Volatility is expanding", VT != "expanding"),
                     _check("No gamma breakout" if not G.startswith("breakout") else "Spot is beyond a gamma wall: moves can run", not G.startswith("breakout")),
                     _check(f"Credit {credit:,.1f} is {credit / width * 100:.0f}% of the wider wing", credit / width >= config.ST_MIN_CREDIT_WIDTH * 0.75),
                     dte_check()], fit,
                    f"Range view: short delta {config.ST_CONDOR_SHORT_DELTA} both sides, wings at {config.ST_CONDOR_WING_DELTA}.",
                    {"stop_pnl": -min(config.ST_CREDIT_SL * credit, 0.9 * (width - credit)), "target_pnl": config.ST_CREDIT_TP * credit})
        Sc, Sp = opt_leg(g, "CE", config.ST_STRANGLE_DELTA, "SELL", exp), opt_leg(g, "PE", config.ST_STRANGLE_DELTA, "SELL", exp)
        Wc, Wp = opt_leg(g, "CE", config.ST_STRANGLE_WING_DELTA, "BUY", exp), opt_leg(g, "PE", config.ST_STRANGLE_WING_DELTA, "BUY", exp)
        if all([Sc, Sp, Wc, Wp]) and Wc["strike"] > Sc["strike"] and Wp["strike"] < Sp["strike"]:
            credit = Sc["ltp"] + Sp["ltp"] - Wc["ltp"] - Wp["ltp"]
            width = max(Wc["strike"] - Sc["strike"], Sp["strike"] - Wp["strike"])
            if credit > 0:
                add("strangle_dh", f"Short strangle {Sp['strike']:,.0f} PE / {Sc['strike']:,.0f} CE + wings, delta-hedged",
                    [Sp, Wp, Sc, Wc],
                    [_check("IV is rich" if V == "rich" else "IV is not rich: not worth the short gamma", V == "rich"),
                     _check("Volatility is not expanding" if VT != "expanding" else "Volatility is expanding", VT != "expanding"),
                     _check("No gamma breakout" if not G.startswith("breakout") else "Spot is beyond a gamma wall", not G.startswith("breakout")),
                     dte_check()], 80 if V == "rich" else 40,
                    f"Collect rich premium; when the net delta passes ±{config.DH_BAND} per lot, buy or sell futures to bring it back to zero. Wings cap the loss.",
                    {"stop_pnl": -min(config.ST_CREDIT_SL * credit, 0.9 * (width - credit)), "target_pnl": config.ST_CREDIT_TP * credit,
                     "delta_hedge": True})
    # ------------------------------------------------ long volatility (any direction)
    if V == "cheap" or VT == "expanding" or G.startswith("breakout"):
        atm = float(g.strike.values[int(np.argmin(np.abs(g.strike.values - fwd)))])
        C, P = leg_at(g, "CE", atm, "BUY", exp), leg_at(g, "PE", atm, "BUY", exp)
        if C and P:
            debit = C["ltp"] + P["ltp"]
            theta = abs(C["theta"] + P["theta"])
            fit = 85 if (V == "cheap" and VT == "expanding") else 70 if V == "cheap" else 60
            add("straddle_dh", f"Long straddle {atm:,.0f}, delta-hedged", [C, P],
                [_check("IV is not rich" if V != "rich" else "IV is rich: straddle is expensive", V != "rich"),
                 _check(f"Theta {theta:,.1f} a day = {theta / debit * 100:.1f}% of the cost", theta / debit <= (0.08 if mode == "swing" else 0.15)),
                 dte_check()], fit,
                f"Long gamma: profits from a big move either way. When the net delta passes ±{config.DH_BAND} per lot, sell/buy futures to lock the gain.",
                {"stop_pnl": -config.ST_STRADDLE_SL * debit, "target_pnl": config.ST_STRADDLE_TP * debit, "delta_hedge": True})
    for i in ideas:
        r = i["rules"]
        for k in ("stop_pnl", "target_pnl"):
            if r.get(k) is not None:
                r[k] = round(float(r[k]), 2)
        i["exit"] = exit_text(mode, i)
    ideas.sort(key=lambda x: (not x["ok"], -x["fit"]))
    return ideas


def exit_text(mode: str, idea: dict) -> str:
    r = idea["rules"]
    parts = []
    if r.get("spot_stop"):
        parts.append(f"Stop if spot reaches {r['spot_stop']:,.0f}, target {r['spot_target']:,.0f}")
    else:
        parts.append(f"Stop at a loss of {abs(r['stop_pnl']):,.1f} pts, target a gain of {r['target_pnl']:,.1f} pts per unit")
    if r.get("delta_hedge"):
        parts.append(f"hedge with futures when |net delta| > {config.DH_BAND} per lot")
    parts.append(f"square off by {config.INTRADAY_EXIT_TIME}" if mode == "intraday"
                 else f"time exit after {config.INDEX_IDEA_SESSIONS} sessions or the day before expiry")
    return "; ".join(parts) + "."
