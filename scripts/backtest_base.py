"""Temporary: price-only test, 50 EMA cross signals vs base (consolidation) breakouts.
Same entry (next open), 1:2 target, exits (stop, target, close back across the 50 EMA,
5 sessions), 0.1% costs. No OI filter (past intraday OI is not available)."""
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from desk import screener, signals
from desk.sources import NSE, yahoo_chart

COST = 0.10


def outcome(df, e, j, d, lv):
    r = signals._walk(df, e, j, d, lv, True)
    if not r:
        return None
    reason, px, t = r
    entry = lv["entry"]; risk = abs(entry - lv["stop"])
    return {"reason": reason, "R": (px - entry) * d / risk, "net": (px / entry - 1) * 100 * d - COST,
            "risk_pct": risk / entry * 100}


def scan(sym):
    df = yahoo_chart(f"{sym}.NS", "60m", "6mo")
    if len(df) < 150:
        return []
    e = screener.ema(df.Close, 50)
    O, H, L, C, E = (df[c].to_numpy(float) for c in ("Open", "High", "Low", "Close")) + (e.to_numpy(float),) if False else \
        (df.Open.to_numpy(float), df.High.to_numpy(float), df.Low.to_numpy(float), df.Close.to_numpy(float), e.to_numpy(float))
    rng = H - L
    out, side, nb, last_bo = [], 0, 0, -1
    for j in range(60, len(df) - 1):
        s_prev = 1 if C[j - 1] > E[j - 1] else -1
        if s_prev != side:
            side, nb, last_bo = s_prev, 0, j - 2
        sig = screener.signal_at(df, e, j)
        if sig:
            lv = screener.levels(sig, float(O[j + 1]))
            res = outcome(df, e, j, sig["dir"], lv) if lv else None
            if res:
                out.append({"type": "cross", "side": sig["dir"], "sym": sym, "t": df.index[j], **res})
        d = side
        if (E[j - 1] - E[j - 8]) * d <= 0:
            continue
        r_ = rng[j]
        if r_ <= 0:
            continue
        body, pos = abs(C[j] - O[j]) / r_, (C[j] - L[j]) / r_
        if d > 0 and not (C[j] > O[j] and body >= 0.5 and pos >= 2 / 3):
            continue
        if d < 0 and not (C[j] < O[j] and body >= 0.5 and pos <= 1 / 3):
            continue
        avg = rng[j - 20:j].mean()
        best = None
        for k in range(4, 15):
            a = j - k
            if a <= last_bo:
                break
            if d > 0 and not (C[a:j] > E[a:j]).all():
                break
            if d < 0 and not (C[a:j] < E[a:j]).all():
                break
            bh, bl = H[a:j].max(), L[a:j].min()
            if bh - bl <= 1.5 * avg:
                best = (k, bh, bl)
        if not best:
            continue
        k, bh, bl = best
        if (d > 0 and C[j] <= bh) or (d < 0 and C[j] >= bl):
            continue
        entry = float(O[j + 1])
        stop = bl * 0.999 if d > 0 else bh * 1.001
        if (d > 0 and stop >= entry) or (d < 0 and stop <= entry):
            continue
        nb += 1; last_bo = j
        risk = abs(entry - stop)
        res = outcome(df, e, j, d, {"entry": entry, "stop": stop, "target": entry + d * 2 * risk})
        sig2 = {"dir": d, "candle_ext": L[j] if d > 0 else H[j], "swing": L[j - 10:j].min() if d > 0 else H[j - 10:j].max()}
        lv2 = screener.levels(sig2, entry)
        res2 = outcome(df, e, j, d, lv2) if lv2 else None
        if res:
            out.append({"type": "base", "side": d, "n": nb, "base_len": k, "sym": sym, "t": df.index[j], **res,
                        "alt_R": res2["R"] if res2 else np.nan, "alt_net": res2["net"] if res2 else np.nan,
                        "alt_risk": res2["risk_pct"] if res2 else np.nan})
    return out


def stats(g, rcol="R", ncol="net"):
    g = g.dropna(subset=[rcol])
    if not len(g):
        return "n=0"
    win = (g[ncol] > 0).mean() * 100
    pos, neg = g.loc[g[ncol] > 0, ncol].sum(), -g.loc[g[ncol] <= 0, ncol].sum()
    pf = pos / neg if neg else float("inf")
    reach = g.reason.value_counts(normalize=True).mul(100).round(0).to_dict() if "reason" in g else {}
    return (f"n={len(g):5d}  win {win:4.1f}%  avgR {g[rcol].mean():+.2f}  avg net {g[ncol].mean():+.2f}%  "
            f"PF {pf:.2f}  risk {g.get('risk_pct', pd.Series([np.nan])).mean():.2f}%  exits {reach}")


syms = sorted(s for s in NSE().fno_lots() if s not in screener.INDEX_SYMBOLS)
with ThreadPoolExecutor(max_workers=8) as ex:
    rows = [r for rs in ex.map(scan, syms) for r in rs]
df = pd.DataFrame(rows)
days = df.t.dt.date.nunique()
print(f"\nSTOCKS {len(syms)}  TRADING DAYS {days}  PERIOD {df.t.min():%d %b %Y} to {df.t.max():%d %b %Y}")
cr, bs = df[df.type == "cross"], df[df.type == "base"]
print(f"PER DAY  cross {len(cr)/days:.1f}  base(all) {len(bs)/days:.1f}  base(1st+2nd) {len(bs[bs.n <= 2])/days:.1f}")
print("CROSS all        ", stats(cr))
print("CROSS long       ", stats(cr[cr.side > 0]))
print("CROSS short      ", stats(cr[cr.side < 0]))
print("BASE all         ", stats(bs))
print("BASE 1st         ", stats(bs[bs.n == 1]))
print("BASE 2nd         ", stats(bs[bs.n == 2]))
print("BASE 1st+2nd     ", stats(bs[bs.n <= 2]))
print("BASE 3rd+        ", stats(bs[bs.n >= 3]))
print("BASE 1-2 long    ", stats(bs[(bs.n <= 2) & (bs.side > 0)]))
print("BASE 1-2 short   ", stats(bs[(bs.n <= 2) & (bs.side < 0)]))
b12 = bs[bs.n <= 2]
print("BASE 1-2 CURRENT-STOP rule ", stats(b12.assign(risk_pct=b12.alt_risk), "alt_R", "alt_net"))
print("BASE 1-2 base 4-6 candles  ", stats(b12[b12.base_len <= 6]))
print("BASE 1-2 base 7-14 candles ", stats(b12[b12.base_len >= 7]))
m = df.assign(month=df.t.dt.to_period("M"))
for mo, g in m.groupby("month"):
    print(f"MONTH {mo}  cross {stats(g[g.type=='cross'])[:60]} | base1-2 {stats(g[(g.type=='base') & (g.n<=2)])[:60]}")
