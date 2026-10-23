"""Storage: Supabase (PostgREST) when SUPABASE_URL / SUPABASE_SERVICE_KEY are set,
otherwise a local in-memory store that writes JSON to ./out (dry runs, tests)."""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from pathlib import Path

import requests


def _jsonable(v):
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if hasattr(v, "item"):
        return _jsonable(v.item())
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


class Supabase:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        # Legacy service_role keys are JWTs and also go in the Authorization header;
        # the newer "sb_secret_..." keys must be sent in the apikey header only.
        self.h = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):
            self.h["Authorization"] = f"Bearer {key}"

    def _req(self, method, table, params=None, body=None, prefer=None):
        h = dict(self.h)
        if prefer:
            h["Prefer"] = prefer
        r = requests.request(method, f"{self.base}/{table}", params=params, headers=h,
                             data=json.dumps(_jsonable(body)) if body is not None else None, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {method} {table}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.text.strip() else None

    def insert(self, table: str, rows: list[dict]):
        for i in range(0, len(rows), 1000):
            self._req("POST", table, body=rows[i:i + 1000], prefer="return=minimal")

    def upsert(self, table: str, rows: list[dict], on_conflict: str):
        for i in range(0, len(rows), 1000):
            self._req("POST", table, params={"on_conflict": on_conflict}, body=rows[i:i + 1000],
                      prefer="resolution=merge-duplicates,return=minimal")

    def select(self, table: str, params: dict) -> list[dict]:
        out, start = [], 0
        while True:
            h = dict(self.h)
            h["Range"] = f"{start}-{start + 999}"
            r = requests.get(f"{self.base}/{table}", params=params, headers=h, timeout=60)
            if r.status_code >= 300:
                raise RuntimeError(f"Supabase GET {table}: HTTP {r.status_code} {r.text[:300]}")
            page = r.json()
            out.extend(page)
            if len(page) < 1000:
                return out
            start += 1000

    def update(self, table: str, params: dict, values: dict):
        self._req("PATCH", table, params=params, body=values, prefer="return=minimal")

    def delete(self, table: str, params: dict):
        self._req("DELETE", table, params=params, prefer="return=minimal")

    def put_doc(self, key: str, data):
        self.upsert("docs", [{"key": key, "data": data, "updated_at": datetime.utcnow().isoformat() + "Z"}], "key")


class Local:
    """Dry-run store: keeps rows in memory, writes docs to ./out/<key>.json."""

    def __init__(self, out_dir: str = "out"):
        self.tables: dict[str, list[dict]] = {}
        self.out = Path(out_dir)
        self.out.mkdir(exist_ok=True)

    def insert(self, table, rows):
        self.tables.setdefault(table, []).extend(_jsonable(rows))

    def upsert(self, table, rows, on_conflict):
        keys = on_conflict.split(",")
        cur = self.tables.setdefault(table, [])
        for r in _jsonable(rows):
            cur[:] = [x for x in cur if any(x.get(k) != r.get(k) for k in keys)]
            cur.append(r)

    def select(self, table, params):
        rows = list(self.tables.get(table, []))
        for col, cond in params.items():
            if col in ("select", "order", "limit"):
                continue
            op, _, val = cond.partition(".")
            def ok(x, op=op, val=val, col=col):  # noqa: E306
                v = x.get(col)
                if v is None:
                    return op == "is" and val == "null"
                if op == "eq":
                    return str(v) == val
                if op == "gte":
                    return str(v) >= val
                if op == "lt":
                    return str(v) < val
                if op == "in":
                    return str(v) in val.strip("()").split(",")
                if op == "is":
                    return False
                return True
            rows = [x for x in rows if ok(x)]
        return rows

    def update(self, table, params, values):
        for x in self.select(table, params):
            x.update(_jsonable(values))

    def delete(self, table, params):
        drop = {id(x) for x in self.select(table, params)}
        self.tables[table] = [x for x in self.tables.get(table, []) if id(x) not in drop]

    def put_doc(self, key, data):
        (self.out / f"{key}.json").write_text(json.dumps(_jsonable(data), indent=1), encoding="utf-8")


def connect():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return Supabase(url, key)
    print("No Supabase secrets set: dry run, results go to ./out")
    return Local()
