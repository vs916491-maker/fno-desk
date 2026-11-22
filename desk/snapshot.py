"""Index snapshot job - runs every 15 minutes in market hours (GitHub Actions).

1. Fetches option chains (nearest + swing monthly; NIFTY weekly), index futures
   and index quotes; stores them.
2. Computes Greeks for every chain (desk/greeks.py), the index views and strategy ideas for
   Suggested index trades, swing and intraday (desk/edge.py, desk/strategies.py; 22 Nov 2026,
   replaces the old 5-factor score), the intraday trend scale (every index), warnings, option
   chain summaries and hourly PCR / futures OI history.
3. Publishes three documents the website reads: index_dashboard,
   swing_signals, option_chains. At/after 15:15 it saves the day's official
   swing signal.
4. Index Track Record: fills, marks and closes logged ideas, logs new ones (desk/idx_record.py).
5. My Index Trades: marks open trades (P&L, Greeks, hedge suggestion), closes at stop / target /
   time exit; older single-leg index futures trades close at their stop, target or time exit.

Run:  python -m desk.snapshot            (skips outside market hours)
      python -m desk.snapshot --force    (run anyway)
"""

from __future__ import annotations

import argparse
import os
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, edge, engine, greeks, idx_record, journal, store, strategies
from .sources import BSE, NSE, yahoo_quote

IST = ZoneInfo(config.TZ)


def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None, second=0, microsecond=0)


def in_market(t: datetime) -> bool:
    if t.weekday() >= 5:
        return False
    hm = t.strftime("%H:%M")
    return config.MARKET_OPEN <= hm <= "15:40"


def chain_rows(ts: str, symbol: str, expiry: date, kind: str, spot: float, df: pd.DataFrame) -> list[dict]:
    rows = df.to_dict("records")
    for r in rows:
        r.update({"ts": ts, "symbol": symbol, "expiry": str(expiry), "kind": kind, "spot": spot})
    return rows


def frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df.ts)
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    t = now_ist()
    if not args.force and not in_market(t):
        print(f"{t:%a %H:%M} IST: market closed, nothing to do.")
        return 0
    ts = t.strftime("%Y-%m-%dT%H:%M:00")
    today = t.date()
    db = store.connect()
    if not args.force and recent_run(db, "index_dashboard", t, minutes=7):
        print("A snapshot was taken in the last 7 minutes (the other scheduler got there first).")
        return 0
    nse, problems = NSE(), []
    try:
        bse = BSE()
    except Exception as exc:  # noqa: BLE001
        bse, problems = None, problems + [f"BSE session: {exc}"]

    # ------------------------------------------------------------ fetch
    try:
        need = idx_record.needed_expiries(db)        # expiries open ideas / trades still need
    except Exception:  # noqa: BLE001
        need = {}
    chains: dict[tuple[str, str], dict] = {}     # (symbol, kind) -> {expiry, spot, df}
    nearest: dict[str, date] = {}
    fut_rows, chain_store, pcr_rows = [], [], []
    for sym, meta in config.INDICES.items():
        try:
            exps = bse.expiries() if meta["exchange"] == "BSE" else nse.expiries(sym)
            exps = [e for e in exps if e >= today]
            nearest[sym] = exps[0]
            wanted = {"monthly": engine.pick_monthly(exps, today), "nearest": exps[0]}
            if meta["weekly"]:
                w1 = engine.pick_weekly(exps, today)
                wanted["weekly"] = w1
                if w1 and w1 == engine.next_weekday(today):            # expiry eve: add the next weekly
                    later = [e for e in exps if e > w1]
                    if later:
                        wanted["weekly_next"] = later[0]
            have = set(wanted.values())
            for e in sorted(need.get(sym, ())):
                d = date.fromisoformat(e)
                if d in exps and d not in have:
                    wanted[f"extra{len(have)}"] = d
                    have.add(d)
            fetched: dict[date, tuple] = {}
            for kind, exp in wanted.items():
                if not exp:
                    continue
                if exp not in fetched:
                    fetched[exp] = (bse.chain(exp) if meta["exchange"] == "BSE" else nse.chain(sym, exp))
                df, spot = fetched[exp]
                chains[(sym, kind)] = {"expiry": exp, "spot": spot, "df": df}
            for exp, (df, spot) in fetched.items():
                kinds = [k for k, e in wanted.items() if e == exp]
                chain_store += chain_rows(ts, sym, exp, "+".join(kinds), spot, df)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{sym} option chain: {type(exc).__name__}: {exc}"[:240])
        try:
            for f in nse.index_futures(sym):
                fut_rows.append({"ts": ts, "symbol": sym, **f, "expiry": str(f["expiry"])})
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{sym} futures: {type(exc).__name__}: {exc}"[:240])

    # PCR history: monthly PCR for every index, weekly for NIFTY / SENSEX
    for (sym, kind), c in chains.items():
        if kind not in ("monthly", "weekly"):
            continue
        df = c["df"]
        ce, pe = float(df.ce_oi.sum()), float(df.pe_oi.sum())
        eve = False
        if kind == "weekly" and (sym, "weekly_next") in chains:
            nx = chains[(sym, "weekly_next")]["df"]
            ce, pe, eve = ce + float(nx.ce_oi.sum()), pe + float(nx.pe_oi.sum()), True
        pcr_rows.append({"ts": ts, "symbol": sym, "kind": kind, "expiry": str(c["expiry"]),
                         "pcr": pe / ce if ce else None, "ce_oi": ce, "pe_oi": pe, "spot": c["spot"],
                         "combined": eve})

    try:
        quotes = nse.all_indices()
    except Exception as exc:  # noqa: BLE001
        quotes = {}
        problems.append(f"index quotes: {exc}"[:200])
    sensex_q = yahoo_quote("^BSESN")

    # ------------------------------------------------------------ store raw
    for table, rows in (("chain_snap", chain_store), ("fut_snap", fut_rows), ("pcr_hist", pcr_rows)):
        if rows:
            try:
                db.insert(table, rows)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"save {table}: {exc}"[:240])

    # ------------------------------------------------------------ history needed for the rules
    day_s = str(today)
    since = str(today - timedelta(days=config.HISTORY_DAYS + 5))
    futs_all = frame(db.select("fut_snap", {"ts": f"gte.{since}", "order": "ts"}))
    pcr_all = frame(db.select("pcr_hist", {"ts": f"gte.{since}", "order": "ts"}))

    def today_snaps(sym: str, exp: date) -> pd.DataFrame:
        rows = db.select("chain_snap", {"symbol": f"eq.{sym}", "expiry": f"eq.{exp}", "ts": f"gte.{day_s}",
                                        "order": "ts"})
        return frame(rows)

    # ------------------------------------------------------------ Greeks for every fetched chain
    fut_now: dict = {}
    for r in fut_rows:
        fut_now.setdefault(r["symbol"], {})[r["expiry"]] = r["ltp"]
    gchains: dict = {}                                     # (symbol, expiry str) -> (chain with greeks, info)
    gkinds: dict = {}
    for (sym, kind), c in chains.items():
        key = (sym, str(c["expiry"]))
        gkinds[key] = "+".join(x for x in (gkinds.get(key), kind) if x)
        if key in gchains:
            continue
        try:
            g, info = greeks.chain_greeks(c["df"], c["spot"], c["expiry"], t, (fut_now.get(sym) or {}).get(str(c["expiry"])))
            info["spot"] = c["spot"]
            gchains[key] = (g, info)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{sym} {c['expiry']} greeks: {type(exc).__name__}: {exc}"[:200])
    vix_q = quotes.get("INDIA VIX")
    vix_last = (vix_q or {}).get("last")
    try:
        if gchains:
            db.insert("greeks_hist", idx_record.greeks_rows(ts, gchains, gkinds, vix_last))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"save greeks_hist (run supabase/013_index_greeks.sql once): {exc}"[:240])
    try:
        ghist = frame(db.select("greeks_hist", {"ts": f"gte.{idx_record.prev_session(idx_record.prev_session(today))}",
                                                "order": "ts"}))
    except Exception:  # noqa: BLE001
        ghist = pd.DataFrame()
    vix_days = None
    try:                                                   # daily India VIX close, for the VIX rank
        rows = db.select("docs", {"key": "eq.vix_daily", "select": "data"})
        vd = dict((rows[0]["data"] if rows else {}) or {})
        if vix_last:
            vd[day_s] = vix_last
        vd = dict(sorted(vd.items())[-260:])
        db.put_doc("vix_daily", vd)
        prior = [v for k, v in vd.items() if k < day_s and v]
        vix_days = pd.Series(prior + ([vix_last] if vix_last else []), dtype=float)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"vix history: {exc}"[:160])

    # ------------------------------------------------------------ compute
    cards, signals, warnings, charts, option_chains, trends = [], [], [], {}, {}, {}
    views: dict[str, dict] = {"swing": {}, "intraday": {}}
    for sym, meta in config.INDICES.items():
        futs = futs_all[futs_all.symbol == sym] if not futs_all.empty else pd.DataFrame()
        mon = chains.get((sym, "monthly"))
        snaps_m = today_snaps(sym, mon["expiry"]) if mon else pd.DataFrame()

        main_kind = "weekly" if meta["weekly"] else "monthly"
        main = chains.get((sym, main_kind)) or mon
        snaps_main = (today_snaps(sym, main["expiry"]) if main and main is not mon else snaps_m)
        q = (sensex_q or {}) if sym == "SENSEX" else quotes.get(meta["quote"] or "", {})
        spot = (main or {}).get("spot") or q.get("last")
        lv = engine.chain_levels(main["df"], main["spot"], meta["strike_step"]) if main else {}
        fd = engine.futures_day(futs, today, mon["expiry"] if mon else None) if not futs.empty else None

        # closes before today (last spot of each session, monthly PCR history)
        p = pcr_all[pcr_all.symbol == sym] if not pcr_all.empty else pd.DataFrame()
        closes = None
        if not p.empty:
            pm = p[p.kind == "monthly"].copy()
            pm["d"] = pd.to_datetime(pm.ts).dt.date
            pm = pm[pm.d < today].sort_values("ts")
            closes = pm.groupby("d").spot.last().reset_index(drop=True) if not pm.empty else None
        fut_map = fut_now.get(sym) or {}
        for mode, c, snaps in (("swing", mon, snaps_m), ("intraday", main, snaps_main)):
            if mode == "intraday" and sym not in config.INTRADAY_INDICES:
                continue
            if not c or snaps is None or snaps.empty:
                continue
            key = (sym, str(c["expiry"]))
            if key not in gchains:
                continue
            try:
                g, info = gchains[key]
                path = snaps.groupby("ts", as_index=False).spot.first().sort_values("ts")
                past = None
                cut = pd.Timestamp(t) - pd.Timedelta(minutes=config.FLOW_LOOKBACK_MIN)
                earlier = [x for x in sorted(snaps.ts.unique()) if pd.Timestamp(x) <= cut + pd.Timedelta(minutes=2)]
                if earlier:
                    past = snaps[snaps.ts == earlier[-1]]
                hist = ghist[(ghist.symbol == sym) & (pd.to_datetime(ghist.expiry).dt.date == c["expiry"])] \
                    if not ghist.empty else None
                day_q = {"open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "prev_close": q.get("prev_close")}
                fut_exp = str(mon["expiry"]) if (mode == "swing" and mon) else None
                f_ltp = fut_map.get(fut_exp) if fut_exp else (fut_map[sorted(fut_map)[0]] if fut_map else None)
                fut = {"ltp": f_ltp, "expiry": fut_exp or (sorted(fut_map)[0] if fut_map else None)} if f_ltp else None
                v = edge.build_view(mode, sym, g, info, c["expiry"], t, float(c["spot"]), past, path, day_q, closes,
                                    hist, futs if not futs.empty else None, mon["expiry"] if mon else c["expiry"],
                                    vix_q, vix_days)
                lvc = engine.chain_levels(c["df"], c["spot"], meta["strike_step"])
                if fd:
                    lvc.update({k: fd[k] for k in ("fut_expiry", "fut_ltp", "fut_pct", "state")})
                v["levels"] = lvc
                v["ideas"] = strategies.build_ideas(v, g, info, fut, lvc, t)
                v["best"] = next((i["strategy"] for i in v["ideas"] if i["ok"]), None)
                views[mode][sym] = v
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{sym} {mode} view: {type(exc).__name__}: {exc}"[:200])
        sw = views["swing"].get(sym)
        sig = {"symbol": sym, "direction": "NO DATA", "strength": "", "score": None, "spot": spot, "trades": [],
               "levels": {}, "expiry": str(mon["expiry"]) if mon else None}
        if sw:
            best = next((i for i in sw["ideas"] if i["ok"]), None)
            sig.update({"direction": {"LONG": "LONG", "SHORT": "SHORT"}.get(sw["direction"], "NO TRADE"),
                        "strength": sw["strength"], "score": sw["score"], "spot": sw["spot"], "levels": sw["levels"],
                        "best": best["name"] if best else None, "vol": sw["vol"]["state"], "gamma": sw["gamma"]["regime"]})
        signals.append(sig)
        cards.append({"symbol": sym, "spot": spot, "change": q.get("change"), "pchange": q.get("pchange"),
                      "pcr": lv.get("pcr"), "pcr_kind": main_kind, "expiry": str(main["expiry"]) if main else None,
                      "support": lv.get("support"), "resistance": lv.get("resistance"),
                      "max_pain": lv.get("max_pain"), "atm_iv": lv.get("atm_iv"),
                      "fut": fd, "signal": sig.get("direction"), "signal_strength": sig.get("strength"),
                      "signal_score": sig.get("score")})
        # intraday trend scale on the index's main chain (weekly if it has one, else monthly)
        try:
            tr = engine.trend_scale(snaps_main, futs if not futs.empty else None,
                                    meta["strike_step"], main_kind)
            if tr:
                trends[sym] = tr
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{sym} trend scale: {exc}"[:200])
        for w in (engine.squeeze_warning(snaps_main, sym), engine.expiry_warning(sym, nearest.get(sym), today)):
            if w:
                warnings.append({"symbol": sym, "text": w,
                                 "kind": "squeeze" if "risk" in w else "expiry"})

        # hourly charts (last 30 days)
        series = {}
        for kind in ("monthly", "weekly"):
            pk = p[p.kind == kind] if not p.empty else pd.DataFrame()
            if not pk.empty:
                h = engine.hourly_last(pk, ["pcr"])
                series[kind] = [{"ts": str(r.hour), "pcr": r.pcr, "expiry": r.expiry,
                                 "combined": bool(r.get("combined", False))} for _, r in h.iterrows()]
        charts[sym] = {"pcr": series, "futures_oi": engine.futures_hourly(futs)}

        # option chains for the Option chain tab
        seen = set()
        for kind in ("nearest", "weekly", "monthly"):
            c = chains.get((sym, kind))
            if not c or c["expiry"] in seen:
                continue
            seen.add(c["expiry"])
            df = c["df"]
            lvl = engine.chain_levels(df, c["spot"], meta["strike_step"])
            option_chains.setdefault(sym, []).append({
                "expiry": str(c["expiry"]), "kind": kind, "spot": c["spot"], "ts": ts,
                "dte": (c["expiry"] - today).days, **lvl,
                "rows": df[["strike", "ce_oi", "ce_coi", "ce_ltp", "ce_iv", "ce_vol",
                            "pe_oi", "pe_coi", "pe_ltp", "pe_iv", "pe_vol"]].round(2).values.tolist(),
            })

    trend = trends.get("NIFTY")   # kept as its own key for older pages

    vix = vix_q
    lots = lot_sizes(nse)
    dash = {"ts": ts, "cards": cards, "vix": vix, "trend": trend, "trends": trends, "warnings": warnings,
            "charts": charts, "problems": problems}
    db.put_doc("index_dashboard", dash)
    db.put_doc("swing_signals", {"ts": ts, "engine": "greeks-v1", "signals": signals, "views": views,
                                 "lot_sizes": lots})
    db.put_doc("option_chains", {"ts": ts, "chains": option_chains,
                                 "columns": ["strike", "ce_oi", "ce_coi", "ce_ltp", "ce_iv", "ce_vol",
                                             "pe_oi", "pe_coi", "pe_ltp", "pe_iv", "pe_vol"]})

    # ------------------------------------------------------------ Index Track Record + My Index Trades
    mk = idx_record.Marker(gchains, fut_now)
    spots = {sym: float(c["spot"]) for (sym, kind), c in chains.items() if kind in ("monthly", "weekly", "nearest")}
    rec = {}
    try:
        rec = idx_record.update_ideas(db, mk, spots, t)
        rec["logged"] = idx_record.log_ideas(db, [v for m in views.values() for v in m.values()], lots, ts, day_s)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"index track record (run supabase/013_index_greeks.sql once): {type(exc).__name__}: {exc}"[:240])
    itr_closed = 0
    try:
        marks, itr_closed = idx_record.mark_trades(db, mk, t)
        db.put_doc("index_trade_marks", {"ts": t.strftime("%Y-%m-%dT%H:%M"), "marks": marks})
    except Exception as exc:  # noqa: BLE001
        problems.append(f"my index trades (run supabase/013_index_greeks.sql once): {type(exc).__name__}: {exc}"[:240])

    # log swing setups the moment they form (and when they drop back to no trade)
    try:
        events = log_setups(db, signals, ts, day_s)
    except Exception as exc:  # noqa: BLE001
        events = 0
        problems.append(f"setup log: {exc}"[:200])

    # the day's official swing signal at/after 15:15
    if t.strftime("%H:%M") >= config.SIGNAL_SAVE_TIME:
        try:
            have = db.select("swing_history", {"day": f"eq.{day_s}", "select": "symbol"})
            if not have:
                db.upsert("swing_history", [{"day": day_s, "symbol": s["symbol"], "ts": ts,
                                             "direction": s.get("direction"), "strength": s.get("strength"),
                                             "score": s.get("score"), "spot": s.get("spot"), "signal": s}
                                            for s in signals], "day,symbol")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"save swing history: {exc}"[:200])

    # auto-close open index futures trades (older single-leg form, table trades)
    try:
        tprices: dict = {}
        closed = journal.check_index_trades(db, fut_now, {c["symbol"]: c["spot"] for c in cards}, t, tprices)
        db.put_doc("trade_prices_index", {"ts": t.strftime("%Y-%m-%dT%H:%M"), "prices": tprices})
    except Exception as exc:  # noqa: BLE001
        closed = 0
        problems.append(f"journal: {exc}"[:200])

    # retention
    try:
        db.delete("chain_snap", {"ts": f"lt.{today - timedelta(days=config.CHAIN_RETENTION_DAYS)}"})
        old = str(today - timedelta(days=60))
        db.delete("fut_snap", {"ts": f"lt.{old}"})
        db.delete("pcr_hist", {"ts": f"lt.{old}"})
        db.delete("greeks_hist", {"ts": f"lt.{today - timedelta(days=config.GREEKS_HIST_DAYS)}"})
    except Exception as exc:  # noqa: BLE001
        problems.append(f"cleanup: {exc}"[:200])

    summary = (f"{ts}: chains {len(chains)}, chain rows {len(chain_store)}, futures {len(fut_rows)}, "
               f"signals " + ", ".join(f"{s['symbol']} {s.get('direction')} {s.get('score')}" for s in signals)
               + "; trend " + (", ".join(f"{k} {v['zone']} {v['score']}" for k, v in trends.items()) or "-") + "; "
               f"warnings {len(warnings)}; setups logged {events}; trades closed {closed}; index record {rec}; "
               f"my index trades closed {itr_closed}; problems {len(problems)}\n"
               + "\n".join(f"{c['symbol']}: spot {c['spot']} ({c.get('pchange')}%), PCR {c['pcr']} {c['pcr_kind']} "
                           f"{c['expiry']}, S {c['support']} R {c['resistance']} MP {c['max_pain']} IV {c['atm_iv']}, "
                           f"fut {(c['fut'] or {}).get('state')} {(c['fut'] or {}).get('fut_ltp')}"
                           for c in cards)
               + "".join(f"\n{m} {sym}: {v['direction']} {v['strength']} {v['score']:+.0f}; vol {v['vol']['state']}/"
                         f"{v['vol']['trend']}; gamma {v['gamma']['regime']}; IV {v['vol']['atm_iv'] or 0:.1f} RR {v.get('rr25') or 0:+.2f}; "
                         f"ideas {sum(1 for i in v['ideas'] if i['ok'])}/{len(v['ideas'])} best {v.get('best')}; "
                         + "; ".join(f"{f['key']}={f['points']}" for f in v["factors"])
                         for m, vs in views.items() for sym, v in vs.items())
               + (f"\nTrend: " + "; ".join(f"{f['factor']}={f['reading']}({f['score']})" for f in trend["factors"])
                  if trend else ""))
    print(summary)
    for p in problems:
        print("PROBLEM:", p)
    if os.environ.get("GITHUB_ACTIONS"):
        msg = summary + ("\n" + "\n".join(problems) if problems else "")
        print("::notice title=Index snapshot::" + msg.replace("%", "%25").replace("\n", "%0A"))
    return 0


def recent_run(db, key: str, now: datetime, minutes: int) -> bool:
    """True if the published document is younger than `minutes` (two schedulers,
    GitHub's and Supabase's, may both start a run; the second one stops here)."""
    try:
        rows = db.select("docs", {"key": f"eq.{key}", "select": "data->>ts"})
    except Exception:  # noqa: BLE001
        return False
    if not rows:
        return False
    ts = next(iter(rows[0].values()), None)
    try:
        last = datetime.fromisoformat(str(ts)[:16])
    except (TypeError, ValueError):
        return False
    return timedelta(0) <= now - last < timedelta(minutes=minutes)


def log_setups(db, signals: list[dict], ts: str, day_s: str) -> int:
    """Insert a swing_events row when a Long/Short setup forms or flips, and an
    ENDED row when it drops back to no trade, so the site shows when each formed."""
    rows = db.select("swing_events", {"day": f"eq.{day_s}", "order": "ts"})
    last = {}
    for r in rows:
        last[r["symbol"]] = r["direction"]
    new = []
    for sig in signals:
        d, prev = sig.get("direction"), last.get(sig["symbol"])
        if d in ("LONG", "SHORT") and prev != d:
            new.append({"ts": ts, "day": day_s, "symbol": sig["symbol"], "direction": d,
                        "strength": sig.get("strength"), "score": sig.get("score"), "spot": sig.get("spot"),
                        "signal": {"trades": sig.get("trades"), "levels": sig.get("levels"),
                                   "expiry": sig.get("expiry")}})
        elif d == "NO TRADE" and prev in ("LONG", "SHORT"):
            new.append({"ts": ts, "day": day_s, "symbol": sig["symbol"], "direction": "ENDED",
                        "strength": None, "score": sig.get("score"), "spot": sig.get("spot"), "signal": None})
    if new:
        db.insert("swing_events", new)
    return len(new)


_LOTS: dict | None = None


def lot_sizes(nse: NSE) -> dict:
    global _LOTS
    if _LOTS is None:
        lots = dict(config.LOT_SIZE_FALLBACK)
        try:
            got = nse.fno_lots()
            for k in lots:
                if k in got:
                    lots[k] = got[k]
        except Exception:  # noqa: BLE001
            pass
        _LOTS = lots
    return _LOTS


def run() -> int:
    try:
        return main()
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=Index snapshot crashed::" + tb[-3000:].replace("%", "%25").replace("\n", "%0A"))
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
