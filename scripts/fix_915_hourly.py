"""One-off (6 Nov 2026): recompute signal-hour OI for 9:15 signals already in signal_log.

Before the fix in desk/signals.py, a 9:15 signal's OI was measured from the previous
day's ~15:19 snapshot, which does not match NSE's end-of-day OI, so most 9:15 signals
showed a false OI drop (or no reading at all). For a 9:15 signal the right reading is
the day's futures OI and price change at the scan that logged it, which is already
stored in info.futures. This rewrites info.hourly, the signal-hour warning, the
proposed score (score_v2 and its parts) and rank_v2 within each scan. Results are not
touched. Safe to run again.

    python scripts/fix_915_hourly.py           # dry run: print the changes
    python scripts/fix_915_hourly.py --write   # save them
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desk import config, signals  # noqa: E402
from desk.store import Supabase  # noqa: E402


def main() -> int:
    write = "--write" in sys.argv
    db = Supabase(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    rows = db.select(signals.LOG_TABLE, {"select": "*"})
    rows = [r for r in rows if str(r["signal_time"])[11:16] == config.MARKET_OPEN]
    print(f"{len(rows)} signal(s) at {config.MARKET_OPEN}")
    W = config.V2_WEIGHTS
    updates = {}
    for r in rows:
        info = dict(r.get("info") or {})
        fut = info.get("futures") or {}
        oi_pct, px_pct = fut.get("pchg_oi"), fut.get("pchange")
        if oi_pct is None or px_pct is None:
            print(f"  {r['symbol']} {r['side']} {r['signal_time']}: no day OI stored, skipped")
            continue
        st = datetime.fromisoformat(str(r["signal_time"])[:16])
        prev = st - timedelta(days=3 if st.weekday() == 0 else 1)
        hourly = {"oi_pct": round(float(oi_pct), 2), "px_pct": round(float(px_pct), 2),
                  "buildup": signals.buildup(float(px_pct), float(oi_pct)),
                  "since": prev.strftime("%Y-%m-%dT15:30"), "from_prev_day": True}
        want = "Long build-up" if r["side"] == "Long" else "Short build-up"
        warns = [w for w in info.get("warnings") or [] if not w.startswith("Signal hour:")]
        if r["kind"] == "idea" and hourly["buildup"] != want:
            warns.append(f"Signal hour: {hourly['buildup'].lower()} (OI {hourly['oi_pct']:+.1f}%), not {want.lower()}")
        vals = {}
        v2 = info.get("v2")
        if v2:
            hour = (min(abs(hourly["oi_pct"]), config.V2_HOUR_OI_CAP) / config.V2_HOUR_OI_CAP
                    if hourly["buildup"] == want else 0.0)
            boost = (info.get("scoring") or {}).get("boost") or 0
            v2 = {**v2, "hour_oi": round(W["hour_oi"] * hour, 1), "hour_known": True}
            v2["score"] = round(min(100.0, v2["hour_oi"] + v2["day_oi"] + v2["shape"] + v2["size"] + boost), 1)
            info["v2"] = v2
            vals["score_v2"] = v2["score"]
        old = info.get("hourly")
        info.update({"hourly": hourly, "warnings": warns})
        vals["info"] = info
        updates[r["id"]] = (r, vals)
        was = f"{old['buildup']} {old['oi_pct']:+.2f}%" if old else "none"
        print(f"  {r['symbol']:<12}{r['side']:<6}{str(r['signal_time'])[:16]}  was {was:<26} now "
              f"{hourly['buildup']} {hourly['oi_pct']:+.2f}%  score_v2 {r.get('score_v2')} -> {vals.get('score_v2')}")

    # rank_v2 within each scan (a 10:19 scan's ideas are all 9:15 signals, so all are here)
    scans = defaultdict(list)
    for rid, (r, vals) in updates.items():
        if r["kind"] == "idea" and r.get("rank_v2") is not None and "score_v2" in vals:
            scans[r["scan_ts"]].append(rid)
    for scan, ids in scans.items():
        ids.sort(key=lambda i: (-updates[i][1]["score_v2"], updates[i][0]["rank_v2"]))
        for n, rid in enumerate(ids, 1):
            r, vals = updates[rid]
            vals["rank_v2"] = n
            if n != r["rank_v2"]:
                print(f"  rank {r['symbol']} {scan}: #{r['rank_v2']} -> #{n}")

    if not write:
        print("Dry run: nothing saved (add --write).")
        return 0
    for rid, (_, vals) in updates.items():
        db.update(signals.LOG_TABLE, {"id": f"eq.{rid}"}, vals)
    print(f"Saved {len(updates)} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
