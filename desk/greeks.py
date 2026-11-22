"""Option Greeks from the free NSE / BSE option chain (22 Nov 2026).

Pricing model: Black-76 on the forward price of each expiry.
    forward F   from put-call parity on the strikes nearest spot: F = K + (C - P) / DF
                (no dividend or carry guess needed; works for SENSEX, which has no futures feed).
                Falls back to the futures price of that expiry, then to spot.
    time T      calendar time to 15:30 IST on expiry day, in years (floor 15 minutes).
    IV          solved from the LTP of the out-of-the-money option at each strike (calls at
                and above F, puts below): the liquid side. One IV per strike is then used for
                both the call and the put, so call and put Greeks agree (put-call parity).
                Strikes with no trade/OI or an LTP below intrinsic are filled by interpolation.

Units: delta per 1 index point; gamma per point; theta in points per calendar day;
vega in points per 1 volatility point (1%).

Chain-wide readings:
    atm_iv      IV at the forward (interpolated), in %
    rr25        25-delta risk reversal = IV(25-delta put) - IV(25-delta call), vol points;
                usually positive; rising = traders paying up for downside protection
    call_wall   strike at/above F with the largest call gamma x OI (where call writers'
                hedging is heaviest); put_wall the mirror below F; pin = largest total
                gamma x OI near spot
    writer_flow delta-weighted change in OI: added OI is read as written (index options in
                India are dominated by writers). Writers short calls hold -delta, short puts
                +delta. Result -1..+1: + = writers adding bullish exposure (puts written /
                calls covered), - = bearish.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import config

SQ2 = math.sqrt(2.0)
SQ2PI = math.sqrt(2.0 * math.pi)
YEAR_SEC = 365.0 * 86400.0


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQ2))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQ2PI


def year_frac(expiry: date, now: datetime) -> float:
    end = datetime(expiry.year, expiry.month, expiry.day, 15, 30)
    sec = (end - now).total_seconds()
    return max(sec, config.GREEKS_MIN_T_MIN * 60.0) / YEAR_SEC


def price(F: float, K: float, T: float, sig: float, kind: str, r: float | None = None) -> float:
    """Black-76 price. kind 'CE' or 'PE'. sig as a fraction (0.12 = 12%)."""
    r = config.RISK_FREE if r is None else r
    df = math.exp(-r * T)
    if T <= 0 or sig <= 0:
        return df * max(0.0, (F - K) if kind == "CE" else (K - F))
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if kind == "CE":
        return df * (F * ncdf(d1) - K * ncdf(d2))
    return df * (K * ncdf(-d2) - F * ncdf(-d1))


def greeks(F: float, K: float, T: float, sig: float, kind: str, r: float | None = None) -> dict:
    r = config.RISK_FREE if r is None else r
    df = math.exp(-r * T)
    if T <= 0 or sig <= 0:
        itm = (F > K) if kind == "CE" else (F < K)
        return {"delta": (1.0 if itm else 0.0) * (1 if kind == "CE" else -1), "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    sq = math.sqrt(T)
    v = sig * sq
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    pdf = npdf(d1)
    delta = df * ncdf(d1) if kind == "CE" else -df * ncdf(-d1)
    gamma = df * pdf / (F * v)
    vega = df * F * pdf * sq / 100.0
    theta_year = -df * F * pdf * sig / (2.0 * sq) + r * price(F, K, T, sig, kind, r)
    return {"delta": delta, "gamma": gamma, "theta": theta_year / 365.0, "vega": vega}


def implied_vol(px: float, F: float, K: float, T: float, kind: str, r: float | None = None) -> float | None:
    """Bisection on Black-76; None when the price is below intrinsic or out of range."""
    r = config.RISK_FREE if r is None else r
    if not px or px <= 0 or T <= 0:
        return None
    df = math.exp(-r * T)
    intrinsic = df * max(0.0, (F - K) if kind == "CE" else (K - F))
    if px <= intrinsic + 1e-6:
        return None
    lo, hi = config.IV_MIN, config.IV_MAX
    if price(F, K, T, hi, kind, r) < px:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if price(F, K, T, mid, kind, r) > px:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)


def forward(df: pd.DataFrame, spot: float, T: float, fut_price: float | None = None) -> tuple[float, str]:
    """Put-call parity forward from the strikes nearest spot (median of up to 3)."""
    disc = math.exp(-config.RISK_FREE * T)
    c = df.assign(d=(df.strike - spot).abs()).sort_values("d").head(6)
    vals = []
    for _, r in c.iterrows():
        if r.ce_ltp and r.pe_ltp and r.ce_ltp > 0 and r.pe_ltp > 0:
            vals.append(float(r.strike) + (float(r.ce_ltp) - float(r.pe_ltp)) / disc)
        if len(vals) >= 3:
            break
    if vals:
        F = float(np.median(vals))
        if abs(F / spot - 1) < config.FWD_MAX_GAP:
            return F, "put-call parity"
    if fut_price and abs(fut_price / spot - 1) < config.FWD_MAX_GAP:
        return float(fut_price), "futures price"
    return float(spot), "spot (no forward)"


def _interp(x: np.ndarray, y: np.ndarray, at: float) -> float | None:
    ok = np.isfinite(y)
    if ok.sum() == 0:
        return None
    xs, ys = x[ok], y[ok]
    order = np.argsort(xs)
    return float(np.interp(at, xs[order], ys[order]))


def chain_greeks(chain: pd.DataFrame, spot: float, expiry: date, now: datetime,
                 fut_price: float | None = None) -> tuple[pd.DataFrame, dict]:
    """Adds iv (fraction), ce_delta, pe_delta, gamma, ce_theta, pe_theta, vega to a copy
    of the chain and returns chain-wide readings."""
    df = chain.sort_values("strike").reset_index(drop=True).copy()
    T = year_frac(expiry, now)
    F, fsrc = forward(df, spot, T, fut_price)
    K = df.strike.values.astype(float)
    iv = np.full(len(df), np.nan)
    for i, r in df.iterrows():
        kind = "CE" if r.strike >= F else "PE"
        px = float(r.ce_ltp if kind == "CE" else r.pe_ltp)
        liquid = (float(r.ce_oi if kind == "CE" else r.pe_oi) > 0) or (float(r.ce_vol if kind == "CE" else r.pe_vol) > 0)
        if px > 0 and liquid:
            v = implied_vol(px, F, float(r.strike), T, kind)
            if v is not None:
                iv[i] = v
    src = "solved from LTP"
    if np.isfinite(iv).sum() < 3:          # too few prices: use the exchange's IV columns
        ex = np.where(K >= F, df.ce_iv.values, df.pe_iv.values).astype(float) / 100.0
        iv = np.where(ex > 0, ex, np.nan)
        src = "exchange IV"
    # drop wild points (stale LTPs): more than IV_OUTLIER x the median of the 5 nearest strikes
    if np.isfinite(iv).sum() >= 5:
        med = pd.Series(iv).rolling(5, center=True, min_periods=3).median().values
        bad = np.isfinite(iv) & np.isfinite(med) & ((iv > med * config.IV_OUTLIER) | (iv < med / config.IV_OUTLIER))
        iv[bad] = np.nan
    if np.isfinite(iv).sum() == 0:
        return df.assign(iv=np.nan, ce_delta=np.nan, pe_delta=np.nan, gamma=np.nan,
                         ce_theta=np.nan, pe_theta=np.nan, vega=np.nan), \
            {"fwd": F, "fwd_src": fsrc, "T": T, "atm_iv": None, "rr25": None, "iv_src": "none"}
    lm = np.log(K / F)
    ok = np.isfinite(iv)
    iv = np.interp(lm, lm[ok], iv[ok])     # fill gaps; flat beyond the last good strike
    cols = {k: np.zeros(len(df)) for k in ("ce_delta", "pe_delta", "gamma", "ce_theta", "pe_theta", "vega")}
    for i in range(len(df)):
        gc = greeks(F, K[i], T, iv[i], "CE")
        gp = greeks(F, K[i], T, iv[i], "PE")
        cols["ce_delta"][i], cols["pe_delta"][i] = gc["delta"], gp["delta"]
        cols["gamma"][i], cols["vega"][i] = gc["gamma"], gc["vega"]
        cols["ce_theta"][i], cols["pe_theta"][i] = gc["theta"], gp["theta"]
    df["iv"] = iv
    for k, v in cols.items():
        df[k] = v
    atm = _interp(lm, iv, 0.0)
    # 25-delta risk reversal: IV where the put delta is -0.25 and the call delta +0.25
    put_side = df[df.strike <= F]
    call_side = df[df.strike >= F]
    p25 = _interp(put_side.pe_delta.values, put_side.iv.values, -0.25) if len(put_side) >= 2 else None
    c25 = _interp(call_side.ce_delta.values[::-1], call_side.iv.values[::-1], 0.25) if len(call_side) >= 2 else None
    rr = (p25 - c25) * 100 if p25 is not None and c25 is not None else None
    gx_c = df.gamma * df.ce_oi
    gx_p = df.gamma * df.pe_oi
    up, dn = df[df.strike >= F], df[df.strike <= F]
    call_wall = float(up.loc[gx_c[up.index].idxmax(), "strike"]) if len(up) and gx_c[up.index].max() > 0 else None
    put_wall = float(dn.loc[gx_p[dn.index].idxmax(), "strike"]) if len(dn) and gx_p[dn.index].max() > 0 else None
    tot = gx_c + gx_p
    pin = float(df.loc[tot.idxmax(), "strike"]) if tot.max() > 0 else None
    return df, {"fwd": F, "fwd_src": fsrc, "T": T, "atm_iv": atm * 100 if atm else None,
                "rr25": rr, "iv_src": src, "call_wall": call_wall, "put_wall": put_wall, "pin": pin}


def writer_flow(g: pd.DataFrame, past: pd.DataFrame | None) -> tuple[float, dict]:
    """Delta-weighted change in OI, read as written. past=None uses the day's change in OI."""
    if past is not None and not past.empty:
        m = g.merge(past[["strike", "ce_oi", "pe_oi"]], on="strike", how="left", suffixes=("", "_p")).fillna(0)
        ce_d, pe_d = (m.ce_oi - m.ce_oi_p).values, (m.pe_oi - m.pe_oi_p).values
        m = m.set_index("strike")
    else:
        ce_d, pe_d = g.ce_coi.values, g.pe_coi.values
    cd, pd_ = g.ce_delta.values, g.pe_delta.values
    good = np.isfinite(cd) & np.isfinite(pd_)
    if not good.any():
        return 0.0, {"calls": 0.0, "puts": 0.0}
    calls = float(-(ce_d[good] * cd[good]).sum())          # written calls: writers lose delta
    puts = float(-(pe_d[good] * pd_[good]).sum())          # written puts (delta < 0): writers gain delta
    gross = float((np.abs(ce_d[good] * cd[good]) + np.abs(pe_d[good] * pd_[good])).sum())
    return (calls + puts) / gross if gross else 0.0, {"calls": calls, "puts": puts}


def strike_for_delta(g: pd.DataFrame, kind: str, target: float) -> pd.Series | None:
    """Row whose |delta| is nearest target, among strikes with a live price."""
    col = "ce_delta" if kind == "CE" else "pe_delta"
    px = "ce_ltp" if kind == "CE" else "pe_ltp"
    c = g[(g[px] > 0) & np.isfinite(g[col])]
    if c.empty:
        return None
    return c.loc[(c[col].abs() - target).abs().idxmin()]
