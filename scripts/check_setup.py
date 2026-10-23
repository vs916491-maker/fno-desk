"""Checks the Supabase setup from GitHub Actions and reports via an annotation."""
import os
import requests

url = os.environ.get("SUPABASE_URL", "").rstrip("/")
key = os.environ.get("SUPABASE_SERVICE_KEY", "")
pub = "sb_publishable_5_59_LRgNx4q3QjFE73cLw_7ixcvAk1"
lines = [f"SUPABASE_URL secret: {'set' if url else 'MISSING'} ({url[:40]})",
         f"SUPABASE_SERVICE_KEY secret: {'set, ' + key[:10] + '...' if key else 'MISSING'}"]
if url and key:
    h = {"apikey": key}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    for t in ("docs", "trades", "chain_snap", "fut_snap", "pcr_hist", "swing_history"):
        r = requests.get(f"{url}/rest/v1/{t}", params={"select": "*", "limit": "1"},
                         headers={**h, "Prefer": "count=exact"}, timeout=30)
        lines.append(f"table {t}: HTTP {r.status_code}, rows {r.headers.get('content-range', '?')} "
                     + ("" if r.status_code == 200 else r.text[:160]))
base = url or "https://ggybblynosipnqbzedsx.supabase.co"
for t in ("trades", "docs"):
    r = requests.get(f"{base}/rest/v1/{t}", params={"select": "*", "limit": "5"}, headers={"apikey": pub}, timeout=30)
    lines.append(f"public key reading {t} (200 + [] = table exists and is locked): HTTP {r.status_code} {r.text[:120]}")
r = requests.get(f"{base}/auth/v1/settings", headers={"apikey": pub}, timeout=30)
if True:
    try:
        j = r.json()
        lines.append(f"auth: email enabled {j.get('external', {}).get('email')}, signup disabled {j.get('disable_signup')}")
    except Exception:  # noqa: BLE001
        lines.append(f"auth settings: HTTP {r.status_code}")
msg = "\n".join(lines)
print(msg)
print("::notice title=Setup check::" + msg.replace("%", "%25").replace("\n", "%0A"))
