"""Index snapshot job - runs every 15 minutes in market hours (GitHub Actions).

1. Fetches option chains (nearest + swing monthly; NIFTY weekly), index futures
   and index quotes; stores them.
2. Computes the swing signals, NIFTY intraday trend scale, warnings, option
   chain summaries and hourly PCR / futures OI history.
3. Publishes three documents the website reads: index_dashboard,
   swing_signals, option_chains. At/after 15:15 it saves the day's official
   swing signal.
4. Auto-closes open index futures trades at their stop, target or time exit.

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

from . import config, engine, journal, store
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

    # ------------------------------------------------------------ compute
    cards, signals, warnings, charts, option_chains = [], [], [], {}, {}
    for sym, meta in config.INDICES.items():
        futs = futs_all[futs_all.symbol == sym] if not futs_all.empty else pd.DataFrame()
        mon = chains.get((sym, "monthly"))
        snaps_m = today_snaps(sym, mon["expiry"]) if mon else pd.DataFrame()
        sig = engine.swing_signal(sym, snaps_m, futs, mon["expiry"], today) if mon else \
            {"symbol": sym, "direction": "NO DATA", "warnings": ["No monthly chain"], "factors": [], "trades": []}
        signals.append(sig)

        main_kind = "weekly" if meta["weekly"] else "monthly"
        main = chains.get((sym, main_kind)) or mon
        snaps_main = (today_snaps(sym, main["expiry"]) if main and main is not mon else snaps_m)
        q = (sensex_q or {}) if sym == "SENSEX" else quotes.get(meta["quote"] or "", {})
        spot = (main or {}).get("spot") or q.get("last")
        lv = engine.chain_levels(main["df"], main["spot"], meta["strike_step"]) if main else {}
        fd = engine.futures_day(futs, today, mon["expiry"] if mon else None) if not futs.empty else None
        cards.append({"symbol": sym, "spot": spot, "change": q.get("change"), "pchange": q.get("pchange"),
                      "pcr": lv.get("pcr"), "pcr_kind": main_kind, "expiry": str(main["expiry"]) if main else None,
                      "support": lv.get("support"), "resistance": lv.get("resistance"),
                      "max_pain": lv.get("max_pain"), "atm_iv": lv.get("atm_iv"),
                      "fut": fd, "signal": sig.get("direction"), "signal_strength": sig.get("strength"),
                      "signal_score": sig.get("score")})
        for w in (engine.squeeze_warning(snaps_main, sym), engine.expiry_warning(sym, nearest.get(sym), today)):
            if w:
                warnings.append({"symbol": sym, "text": w,
                                 "kind": "squeeze" if "risk" in w else "expiry"})

        # hourly charts (last 30 days)
        p = pcr_all[pcr_all.symbol == sym] if not pcr_all.empty else pd.DataFrame()
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

    nifty_w = chains.get(("NIFTY", "weekly"))
    trend = None
    if nifty_w:
        futs_n = futs_all[futs_all.symbol == "NIFTY"] if not futs_all.empty else None
        trend = engine.trend_scale(today_snaps("NIFTY", nifty_w["expiry"]), futs_n)

    vix = quotes.get("INDIA VIX")
    dash = {"ts": ts, "cards": cards, "vix": vix, "trend": trend, "warnings": warnings,
            "charts": charts, "problems": problems}
    db.put_doc("index_dashboard", dash)
    db.put_doc("swing_signals", {"ts": ts, "signals": signals,
                                 "lot_sizes": lot_sizes(nse)})
    db.put_doc("option_chains", {"ts": ts, "chains": option_chains,
                                 "columns": ["strike", "ce_oi", "ce_coi", "ce_ltp", "ce_iv", "ce_vol",
                                             "pe_oi", "pe_coi", "pe_ltp", "pe_iv", "pe_vol"]})

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

    # auto-close open index trades
    fut_now = {}
    for r in fut_rows:
        fut_now.setdefault(r["symbol"], {})[r["expiry"]] = r["ltp"]
    spots = {c["symbol"]: c["spot"] for c in cards}
    try:
        closed = journal.check_index_trades(db, fut_now, spots, t)
    except Exception as exc:  # noqa: BLE001
        closed = 0
        problems.append(f"journal: {exc}"[:200])

    # retention
    try:
        db.delete("chain_snap", {"ts": f"lt.{today - timedelta(days=config.CHAIN_RETENTION_DAYS)}"})
        old = str(today - timedelta(days=60))
        db.delete("fut_snap", {"ts": f"lt.{old}"})
        db.delete("pcr_hist", {"ts": f"lt.{old}"})
    except Exception as exc:  # noqa: BLE001
        problems.append(f"cleanup: {exc}"[:200])

    summary = (f"{ts}: chains {len(chains)}, chain rows {len(chain_store)}, futures {len(fut_rows)}, "
               f"signals " + ", ".join(f"{s['symbol']} {s.get('direction')} {s.get('score')}" for s in signals)
               + f"; trend {trend['zone'] if trend else '-'} {trend['score'] if trend else ''}; "
               f"warnings {len(warnings)}; setups logged {events}; trades closed {closed}; problems {len(problems)}\n"
               + "\n".join(f"{c['symbol']}: spot {c['spot']} ({c.get('pchange')}%), PCR {c['pcr']} {c['pcr_kind']} "
                           f"{c['expiry']}, S {c['support']} R {c['resistance']} MP {c['max_pain']} IV {c['atm_iv']}, "
                           f"fut {(c['fut'] or {}).get('state')} {(c['fut'] or {}).get('fut_ltp')}"
                           for c in cards)
               + ("\n" + "\n".join(f"{s['symbol']} factors: " + "; ".join(f"{f['factor']}={f['reading']}({f['score']})"
                                                                         for f in s.get('factors', []))
                                for s in signals))
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
