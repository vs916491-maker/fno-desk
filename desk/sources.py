"""Exchange data: NSE and BSE public website feeds, Yahoo hourly candles.

These are unofficial website endpoints; they can change without notice.
Every parser is defensive and raises with the index/stock name on failure.
"""

from __future__ import annotations

import io
import time
from datetime import date, datetime

import pandas as pd
import requests

from . import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
CHAIN_COLS = ["strike", "ce_oi", "ce_coi", "ce_ltp", "ce_iv", "ce_vol",
              "pe_oi", "pe_coi", "pe_ltp", "pe_iv", "pe_vol"]


def num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def parse_date(s) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s[:11] if fmt != "%d-%B-%Y" else s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


# ====================================================================== NSE
class NSE:
    BASE = "https://www.nseindia.com"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/option-chain",
        })
        self._warm = False

    def _warmup(self):
        for path in ("/", "/option-chain"):
            try:
                self.s.get(self.BASE + path, timeout=self.timeout)
            except requests.RequestException:
                pass
        self._warm = True

    def get(self, path: str, params: dict | None = None):
        last = "unknown error"
        for attempt in range(3):
            if not self._warm:
                self._warmup()
            time.sleep(config.REQUEST_GAP)
            try:
                r = self.s.get(self.BASE + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (401, 403) or not r.text.strip():
                last = f"HTTP {r.status_code}"
                self._warm = False
                self.s.cookies.clear()
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            try:
                return r.json()
            except ValueError:
                last = "web page instead of data"
                self._warm = False
        raise ConnectionError(f"NSE {path}: {last}")

    # -------------------------------------------------------- option chains
    def expiries(self, symbol: str) -> list[date]:
        j = self.get("/api/option-chain-contract-info", {"symbol": symbol})
        out = sorted({d for d in (parse_date(e) for e in j.get("expiryDates") or []) if d})
        if not out:
            raise ValueError(f"NSE sent no expiries for {symbol}")
        return out

    def chain(self, symbol: str, expiry: date) -> tuple[pd.DataFrame, float]:
        j = self.get("/api/option-chain-v3", {"type": "Indices", "symbol": symbol,
                                              "expiry": expiry.strftime("%d-%b-%Y")})
        rec = j.get("records") or {}
        rows = rec.get("data") or (j.get("filtered") or {}).get("data") or []
        spot = num(rec.get("underlyingValue"))
        out = []
        for r in rows:
            ce, pe = r.get("CE") or {}, r.get("PE") or {}
            spot = spot or num(ce.get("underlyingValue") or pe.get("underlyingValue"))
            out.append({
                "strike": num(r.get("strikePrice")),
                "ce_oi": num(ce.get("openInterest")), "ce_coi": num(ce.get("changeinOpenInterest")),
                "ce_ltp": num(ce.get("lastPrice")), "ce_iv": num(ce.get("impliedVolatility")),
                "ce_vol": num(ce.get("totalTradedVolume")),
                "pe_oi": num(pe.get("openInterest")), "pe_coi": num(pe.get("changeinOpenInterest")),
                "pe_ltp": num(pe.get("lastPrice")), "pe_iv": num(pe.get("impliedVolatility")),
                "pe_vol": num(pe.get("totalTradedVolume")),
            })
        df = pd.DataFrame(out, columns=CHAIN_COLS)
        df = df[df.strike > 0].groupby("strike", as_index=False).sum().sort_values("strike")
        if df.empty or not spot:
            raise ValueError(f"NSE option chain for {symbol} {expiry} came back empty")
        return df.reset_index(drop=True), spot

    # -------------------------------------------------------- index futures
    def index_futures(self, symbol: str) -> list[dict]:
        """All futures contracts of an index with OI and today's change in OI.
        NSE's quote API first (has change in OI); the live futures feed as backup."""
        if not config.INDICES[symbol]["fut_key"]:
            return []
        try:
            j = self.get("/api/NextApi/apiClient/GetQuoteApi",
                         {"functionName": "getSymbolDerivativesData", "symbol": symbol})
            rows = j.get("data") if isinstance(j, dict) else j
            out = []
            for d in rows or []:
                if not str(d.get("instrumentType", "")).upper().startswith("FUT"):
                    continue
                exp = parse_date(d.get("expiryDate"))
                if exp:
                    ltp, prev = num(d.get("lastPrice")), num(d.get("prevClose"))
                    out.append({"expiry": exp, "ltp": ltp, "prev_close": prev,
                                "pchange": num(d.get("pchange")) or ((ltp / prev - 1) * 100 if prev else 0.0),
                                "oi": num(d.get("openInterest")), "coi": num(d.get("changeinOpenInterest"))})
            if out:
                return sorted(out, key=lambda x: x["expiry"])
        except (ConnectionError, ValueError):
            pass
        key = config.INDICES[symbol]["fut_key"]
        j = self.get("/api/liveEquity-derivatives", {"index": key})
        out = []
        for d in j.get("data") or []:
            if str(d.get("underlying", "")).upper() != symbol:
                continue
            exp = parse_date(d.get("expiryDate"))
            if not exp:
                continue
            ltp = num(d.get("lastPrice"))
            chg = num(d.get("change"))
            prev = num(d.get("prevClose")) or (ltp - chg)
            out.append({"expiry": exp, "ltp": ltp, "prev_close": prev,
                        "pchange": num(d.get("pChange")) or ((ltp / prev - 1) * 100 if prev else 0.0),
                        "oi": num(d.get("openInterest")),
                        "coi": num(d.get("changeinOpenInterest") or d.get("changeInOpenInterest"))})
        return sorted(out, key=lambda x: x["expiry"])

    # -------------------------------------------------------- index quotes
    def all_indices(self) -> dict[str, dict]:
        j = self.get("/api/allIndices")
        out = {}
        for d in j.get("data") or []:
            name = str(d.get("index") or d.get("indexSymbol") or "").upper()
            out[name] = {"last": num(d.get("last")), "change": num(d.get("variation")),
                         "pchange": num(d.get("percentChange")), "prev_close": num(d.get("previousClose")),
                         "open": num(d.get("open")), "high": num(d.get("high")), "low": num(d.get("low"))}
        return out

    # -------------------------------------------------------- stock futures (one stock)
    def stock_futures(self, symbol: str) -> dict | None:
        """Near-month futures price/% change and OI + today's change in OI summed
        over all futures expiries (same units, so the % change is exact)."""
        j = self.get("/api/NextApi/apiClient/GetQuoteApi",
                     {"functionName": "getSymbolDerivativesData", "symbol": symbol})
        rows = j.get("data") if isinstance(j, dict) else j
        futs = [r for r in rows or [] if str(r.get("instrumentType", "")).upper().startswith("FUT")]
        if not futs:
            return None
        oi = sum(num(r.get("openInterest")) for r in futs)
        coi = sum(num(r.get("changeinOpenInterest")) for r in futs)
        near = min(futs, key=lambda r: parse_date(r.get("expiryDate")) or date.max)
        prev_oi = oi - coi
        return {"ltp": num(near.get("lastPrice")), "pchange": num(near.get("pchange")),
                "expiry": str(parse_date(near.get("expiryDate"))), "spot": num(near.get("underlyingValue")),
                "oi_total": oi, "chg_oi_total": coi,
                "pchg_oi": (coi / prev_oi * 100) if prev_oi > 0 else 0.0}

    # -------------------------------------------------------- lot sizes / F&O list
    def fno_lots(self) -> dict[str, int]:
        r = self.s.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", timeout=self.timeout)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), dtype=str)
        df.columns = [c.strip() for c in df.columns]
        month_cols = [c for c in df.columns if c not in ("UNDERLYING", "SYMBOL")]
        out = {}
        for _, row in df.iterrows():
            sym = str(row.get("SYMBOL", "")).strip()
            if not sym or sym.upper() == "SYMBOL":
                continue
            for c in month_cols:
                v = str(row.get(c, "")).strip()
                if v.isdigit():
                    out[sym] = int(v)
                    break
        return out


# ====================================================================== BSE (SENSEX)
class BSE:
    EXPIRY_URL = "https://api.bseindia.com/BseIndiaAPI/api/ddlExpiry_IV/w"
    CHAIN_URL = "https://api.bseindia.com/BseIndiaAPI/api/DerivOptionChain_IV/w"
    FIELDS = {   # first matching name wins (case-insensitive)
        "strike": ["Strike_Price1", "Strike_Price", "StrikePrice"],
        "ce_oi": ["C_Open_Interest", "C_OI"], "ce_coi": ["C_Absolute_Change_OI", "C_Change_OI"],
        "ce_ltp": ["C_Last_Trd_Price", "C_LTP"], "ce_iv": ["C_IV"], "ce_vol": ["C_Vol_Traded"],
        "pe_oi": ["Open_Interest", "P_Open_Interest"], "pe_coi": ["Absolute_Change_OI", "P_Absolute_Change_OI"],
        "pe_ltp": ["Last_Trd_Price", "P_Last_Trd_Price"], "pe_iv": ["IV", "P_IV"], "pe_vol": ["Vol_Traded", "P_Vol_Traded"],
        "spot": ["UlaValue", "Underlying_Value"],
    }

    def __init__(self, timeout: int = 25):
        from curl_cffi import requests as creq   # BSE blocks plain python requests
        self.timeout = timeout
        self.s = creq.Session(impersonate="chrome")
        self.s.headers.update({"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})
        try:
            self.s.get("https://www.bseindia.com/", timeout=timeout)
        except Exception:  # noqa: BLE001
            pass

    def _get(self, url: str, params: dict):
        last = "unknown"
        for attempt in range(3):
            time.sleep(config.REQUEST_GAP)
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200 and r.text.strip():
                    return r.json()
                last = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = str(e)
            time.sleep(2 * (attempt + 1))
        raise ConnectionError(f"BSE {url.rsplit('/', 2)[-2]}: {last}")

    def expiries(self) -> list[date]:
        j = self._get(self.EXPIRY_URL, {"ProductType": "IO", "scrip_cd": "1"})
        found = set()
        for d in _walk(j):
            for k, v in d.items():
                if "expir" in k.lower():
                    p = parse_date(v)
                    if p:
                        found.add(p)
        if not found:
            raise ValueError("BSE sent no SENSEX expiries")
        return sorted(found)

    def chain(self, expiry: date) -> tuple[pd.DataFrame, float]:
        j = self._get(self.CHAIN_URL, {"Expiry": expiry.strftime("%d %b %Y"), "scrip_cd": "1", "strprice": "0"})
        rows = j.get("Table") if isinstance(j, dict) else j
        rows = [r for r in rows or [] if isinstance(r, dict)]
        if not rows:
            raise ValueError("BSE SENSEX chain came back empty")
        keymap = {k.lower(): k for k in rows[0]}
        cols = {f: next((keymap[c.lower()] for c in cands if c.lower() in keymap), None)
                for f, cands in self.FIELDS.items()}
        missing = [f for f in ("strike", "ce_oi", "pe_oi") if not cols[f]]
        if missing:
            raise ValueError(f"BSE fields not recognised: {missing}; seen {list(rows[0])[:30]}")
        spot, out = 0.0, []
        for r in rows:
            rec = {f: (num(r.get(c)) if c else 0.0) for f, c in cols.items()}
            spot = spot or rec.get("spot", 0.0)
            rec.pop("spot", None)
            out.append(rec)
        df = pd.DataFrame(out, columns=CHAIN_COLS)
        df = df[df.strike > 0].groupby("strike", as_index=False).sum().sort_values("strike")
        if not spot:
            raise ValueError("BSE did not send the SENSEX spot value")
        return df.reset_index(drop=True), spot


# ====================================================================== Yahoo
def yahoo_chart(symbol: str, interval: str = "60m", rng: str = "3mo") -> pd.DataFrame:
    """OHLCV candles indexed by IST start time (naive). Empty frame on failure."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
    try:
        r = requests.get(url, params={"interval": interval, "range": rng}, headers={"User-Agent": UA}, timeout=20)
        res = r.json()["chart"]["result"][0]
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(config.TZ).tz_localize(None)
    df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                       "Close": q["close"], "Volume": q["volume"]}, index=idx).dropna(subset=["Close"])
    df.attrs["prev_close"] = res.get("meta", {}).get("chartPreviousClose")
    df.attrs["price"] = res.get("meta", {}).get("regularMarketPrice")
    return df[~df.index.duplicated(keep="last")]


def yahoo_quote(symbol: str) -> dict | None:
    df = yahoo_chart(symbol, "5m", "1d")
    if df.empty:
        return None
    price = df.attrs.get("price") or float(df.Close.iloc[-1])
    prev = df.attrs.get("prev_close")
    return {"last": price, "prev_close": prev,
            "change": price - prev if prev else 0.0,
            "pchange": (price / prev - 1) * 100 if prev else 0.0}
