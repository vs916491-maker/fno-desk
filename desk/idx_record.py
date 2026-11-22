"""Index Track Record and My Index Trades (22 Nov 2026).

Index Track Record (table index_ideas): every idea that passes its checks on Suggested index
trades is logged the first time it appears (one per day, mode, index, strategy and bias; not
again while the same one is still open). It is filled at the NEXT 15-minute snapshot's prices
(no look-ahead), then marked every 15 minutes with the chain's LTPs and closed by its own
rules: stop / target on P&L per unit (or on spot for the futures ideas), time exit (intraday
15:15; swing after 5 sessions or the day before expiry), or expiry. Delta-hedged ideas add a
futures hedge at the forward price whenever |net delta| > DH_BAND, and the hedge P&L counts.
Results are per 1 lot (points x lot size). Checked only at 15-minute marks, so a stop can be
filled worse than its level (the record shows the price actually seen).

My Index Trades (table index_trades): your own multi-leg index trades. Every snapshot marks
them (doc index_trade_marks: price of each leg, P&L in rupees, net Greeks, a delta-hedge
suggestion) and closes them at your stop / target in rupees or the time exit, if you set them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from . import config


def _sign(l) -> int:
    return 1 if l["action"] == "BUY" else -1


def add_sessions(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def prev_session(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def time_exit(mode: str, day: date, expiry: date) -> str:
    if mode == "intraday":
        return f"{day}T{config.INTRADAY_EXIT_TIME}"
    last = min(add_sessions(day, config.INDEX_IDEA_SESSIONS - 1), prev_session(expiry))
    return f"{max(last, day)}T15:15"


class Marker:
    """Live prices and Greeks of any leg, from this snapshot's chains."""

    def __init__(self, gchains: dict, fut_now: dict):
        self.g = gchains            # (symbol, expiry str) -> (chain with greeks, info)
        self.fut = fut_now          # symbol -> {expiry str: ltp}

    def fwd(self, sym: str, expiry: str) -> float | None:
        v = self.g.get((sym, str(expiry)))
        return v[1].get("fwd") if v else None

    def leg(self, sym: str, l: dict) -> dict | None:
        if l["type"] == "FUT":
            f = self.fut.get(sym) or {}
            px = f.get(str(l.get("expiry")))
            if px is None and f:
                px = f[sorted(f)[0]]
            if px is None:          # no futures feed (SENSEX): forward of the option expiry
                exps = sorted(e for (s, e) in self.g if s == sym)
                fw = self.fwd(sym, l.get("expiry")) or (self.fwd(sym, exps[0]) if exps else None)
                px = fw + float(l.get("basis") or 0) if fw else None
            return None if px is None else {"ltp": float(px), "delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        v = self.g.get((sym, str(l["expiry"])))
        if not v:
            return None
        g = v[0]
        r = g[g.strike == float(l["strike"])]
        if r.empty:
            return None
        r = r.iloc[0]
        k = l["type"].lower()
        px = float(r[f"{k}_ltp"] or 0)
        if px <= 0:
            return None
        ok = np.isfinite(r[f"{k}_delta"])
        return {"ltp": px, "delta": float(r[f"{k}_delta"]) if ok else None, "gamma": float(r.gamma) if ok else 0.0,
                "theta": float(r[f"{k}_theta"]) if ok else 0.0, "vega": float(r.vega) if ok else 0.0}


# ====================================================================== track record
def _value(sym, legs, hedges, mk: Marker, hedge_px: float | None):
    """P&L per unit now (legs + hedges) and net delta, or None if a leg has no price."""
    pnl, delta = 0.0, 0.0
    for l in legs:
        m = mk.leg(sym, l)
        if m is None:
            return None, None, None
        q = _sign(l) * float(l.get("qty") or 1)
        pnl += q * (m["ltp"] - float(l["entry"]))
        delta += q * (m["delta"] or 0.0)
        l["now"] = m["ltp"]
    for h in hedges or []:
        if hedge_px is None:
            return None, None, None
        pnl += float(h["qty"]) * (hedge_px - float(h["price"]))
        delta += float(h["qty"])
    return pnl, delta, hedge_px


def log_ideas(db, views: list[dict], lots: dict, ts: str, day_s: str) -> int:
    """Insert ideas that pass their checks (status pending, filled at the next snapshot)."""
    try:
        live = db.select("index_ideas", {"status": "in.(pending,open)", "select": "mode,symbol,strategy,bias"})
    except Exception:  # noqa: BLE001
        live = []
    busy = {(r["mode"], r["symbol"], r["strategy"], r["bias"]) for r in live}
    rows = []
    for v in views:
        ideas = v.get("ideas") or []
        best = next((i for i in ideas if i["ok"]), None)
        for i in ideas:
            if not i["ok"]:
                continue
            k = (v["mode"], v["symbol"], i["strategy"], i["bias"])
            if k in busy:
                continue
            busy.add(k)
            rows.append({
                "key": f"{day_s}|{v['mode']}|{v['symbol']}|{i['strategy']}|{i['bias']}",
                "day": day_s, "mode": v["mode"], "symbol": v["symbol"], "strategy": i["strategy"],
                "name": i["name"], "bias": i["bias"], "score": v["score"], "strength": v["strength"] or None,
                "logged_ts": ts, "status": "pending", "lot_size": lots.get(v["symbol"]),
                "legs": [{k2: l[k2] for k2 in ("action", "type", "strike", "expiry", "ltp", "basis", "qty") if l.get(k2) is not None}
                         for l in i["legs"]],
                "rules": {**i["rules"], "time_exit": time_exit(v["mode"], date.fromisoformat(day_s), date.fromisoformat(v["expiry"]))},
                "info": {"best": best is i, "fit": i["fit"], "group": i["group"], "vol": v["vol"]["state"],
                         "vol_trend": v["vol"]["trend"], "gamma": v["gamma"]["regime"], "spot": v["spot"],
                         "expiry": v["expiry"], "net": i["net"], "net_kind": i["net_kind"],
                         "max_loss": i["max_loss"], "max_profit": i["max_profit"],
                         "factors": {f["key"]: f["points"] for f in v["factors"]}},
                "hedges": [],
            })
    if rows:
        db.insert_new("index_ideas", rows, "key")
    return len(rows)


def update_ideas(db, mk: Marker, spots: dict, now: datetime) -> dict:
    """Fill pending ideas, mark open ones, close by their rules. Returns counts."""
    out = {"filled": 0, "void": 0, "closed": 0, "open": 0}
    rows = db.select("index_ideas", {"status": "in.(pending,open)"})
    ts = now.strftime("%Y-%m-%dT%H:%M:00")
    hm = now.strftime("%H:%M")
    for r in rows:
        sym, legs = r["symbol"], r["legs"] or []
        lot = float(r.get("lot_size") or config.LOT_SIZE_FALLBACK.get(sym, 1))
        exp0 = str(legs[0]["expiry"]) if legs else None
        hedge_px = mk.fwd(sym, exp0) if exp0 else None
        vals: dict = {}
        if r["status"] == "pending":
            if str(r["logged_ts"])[:16] >= ts[:16]:
                continue                                   # logged in this very run
            fills = [mk.leg(sym, l) for l in legs]
            if any(f is None for f in fills):
                db.update("index_ideas", {"id": f"eq.{r['id']}"}, {"status": "void", "exit_reason": "no price to fill", "exit_ts": ts})
                out["void"] += 1
                continue
            for l, f in zip(legs, fills):
                l["entry"] = f["ltp"]
            net = sum(_sign(l) * float(l.get("qty") or 1) * l["entry"] for l in legs if l["type"] != "FUT")
            vals.update({"status": "open", "entry_ts": ts, "legs": legs, "entry_net": round(net, 2),
                         "entry_spot": spots.get(sym)})
            r.update(vals)
            out["filled"] += 1
        pnl, delta, _ = _value(sym, legs, r.get("hedges"), mk, hedge_px)
        if pnl is None:
            if vals:
                db.update("index_ideas", {"id": f"eq.{r['id']}"}, vals)
            continue
        rules = r.get("rules") or {}
        hedges = r.get("hedges") or []
        if rules.get("delta_hedge") and hedge_px and delta is not None and abs(delta) > config.DH_BAND:
            hedges.append({"ts": ts, "qty": round(-delta, 3), "price": round(hedge_px, 2)})
            vals["hedges"] = hedges
        inr = pnl * lot
        mfe = max(float(r.get("mfe_inr") or 0), inr)
        mae = min(float(r.get("mae_inr") or 0), inr)
        vals.update({"last_pnl_inr": round(inr, 2), "last_ts": ts, "mfe_inr": round(mfe, 2), "mae_inr": round(mae, 2),
                     "legs": legs})
        reason = None
        sp = spots.get(sym)
        if rules.get("spot_stop") and sp:
            up = rules["spot_target"] > rules["spot_stop"]
            if (up and sp <= rules["spot_stop"]) or (not up and sp >= rules["spot_stop"]):
                reason = "stop"
            elif (up and sp >= rules["spot_target"]) or (not up and sp <= rules["spot_target"]):
                reason = "target"
        else:
            if rules.get("stop_pnl") is not None and pnl <= rules["stop_pnl"]:
                reason = "stop"
            elif rules.get("target_pnl") is not None and pnl >= rules["target_pnl"]:
                reason = "target"
        if not reason and rules.get("time_exit") and ts[:16] >= str(rules["time_exit"])[:16]:
            reason = "time"
        if not reason and exp0 and now.date() >= date.fromisoformat(exp0[:10]) and hm >= "15:15":
            reason = "expiry"
        if reason:
            risk = abs(float(rules.get("stop_pnl") or 0)) or None
            vals.update({"status": "closed", "exit_ts": ts, "exit_reason": reason, "pnl_pts": round(pnl, 2),
                         "pnl_inr": round(inr, 2), "r_mult": round(pnl / risk, 2) if risk else None, "exit_spot": sp})
            out["closed"] += 1
        else:
            out["open"] += 1
        db.update("index_ideas", {"id": f"eq.{r['id']}"}, vals)
    return out


# ====================================================================== my index trades
def mark_trades(db, mk: Marker, now: datetime) -> tuple[dict, int]:
    """Marks for every open index_trades row; closes at stop / target (rupees) or time exit."""
    trades = db.select("index_trades", {"status": "eq.open"})
    marks, closed = {}, 0
    ts = now.strftime("%Y-%m-%dT%H:%M")
    for t in trades:
        sym = t["symbol"]
        lot = float(t.get("lot_size") or config.LOT_SIZE_FALLBACK.get(sym, 1))
        legs = (t.get("legs") or []) + [{**h, "hedge": True} for h in (t.get("hedges") or [])]
        pnl, delta, gam, theta, vega, now_px, missing = 0.0, 0.0, 0.0, 0.0, 0.0, [], False
        for l in legs:
            m = mk.leg(sym, l)
            if m is None:
                missing = True
                now_px.append(None)
                continue
            q = _sign(l) * float(l.get("lots") or 1)
            pnl += q * (m["ltp"] - float(l["entry"])) * lot
            delta += q * (m["delta"] or 0.0)
            gam += q * m["gamma"] * lot
            theta += q * m["theta"] * lot
            vega += q * m["vega"] * lot
            now_px.append(round(m["ltp"], 2))
        pnl -= float(t.get("charges") or 0)
        size = max([float(l.get("lots") or 1) for l in (t.get("legs") or [])] or [1])
        band = config.DH_BAND * size
        hedge = None
        if abs(delta) > band:
            n = int(round(-delta))
            hedge = {"lots": abs(n), "action": "BUY" if n > 0 else "SELL",
                     "note": (f"Net delta {delta:+.2f} lots: {'buy' if n > 0 else 'sell'} {abs(n)} futures lot{'s' if abs(n) > 1 else ''} to hedge"
                              if n else f"Net delta {delta:+.2f} lots: under one futures lot; shift or add an option leg to trim it")}
        legs0 = t.get("legs") or []
        fm = mk.leg(sym, {"type": "FUT", "expiry": legs0[0].get("expiry") if legs0 else None})
        marks[str(t["id"])] = {"t": ts, "px": now_px, "fut_px": round(fm["ltp"], 2) if fm else None, "pnl_inr": None if missing else round(pnl, 2),
                               "delta_lots": round(delta, 3), "gamma_inr": round(gam, 4), "theta_inr": round(theta, 1),
                               "vega_inr": round(vega, 1), "hedge": hedge, "missing": missing}
        if missing:
            continue
        reason = None
        if t.get("stop_inr") and pnl <= -abs(float(t["stop_inr"])):
            reason = "stop hit (auto)"
        elif t.get("target_inr") and pnl >= abs(float(t["target_inr"])):
            reason = "target hit (auto)"
        elif t.get("time_exit") and ts >= str(t["time_exit"])[:16]:
            reason = "time exit (auto)"
        if reason:
            db.update("index_trades", {"id": f"eq.{t['id']}"},
                      {"status": "closed", "exit_time": ts, "exit_reason": reason, "pnl_inr": round(pnl, 2),
                       "exit_px": now_px})
            closed += 1
    return marks, closed


def needed_expiries(db) -> dict[str, set]:
    """Expiries that open ideas / trades still need priced (fetched even if not a standard pick)."""
    need: dict[str, set] = {}
    for table, status in (("index_ideas", "in.(pending,open)"), ("index_trades", "eq.open")):
        try:
            rows = db.select(table, {"status": status, "select": "symbol,legs,hedges" if table == "index_trades" else "symbol,legs"})
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            for l in r.get("legs") or []:
                if l.get("type") in ("CE", "PE") and l.get("expiry"):
                    need.setdefault(r["symbol"], set()).add(str(l["expiry"])[:10])
    return need


def greeks_rows(ts: str, gchains: dict, kinds: dict, vix: float | None) -> list[dict]:
    rows = []
    for (sym, exp), (g, info) in gchains.items():
        rows.append({"ts": ts, "symbol": sym, "expiry": exp, "kind": kinds.get((sym, exp)), "spot": info.get("spot"),
                     "fwd": info.get("fwd"), "atm_iv": info.get("atm_iv"), "rr25": info.get("rr25"),
                     "call_wall": info.get("call_wall"), "put_wall": info.get("put_wall"), "pin": info.get("pin"),
                     "writer_net": info.get("writer_net"), "vix": vix})
    return rows
