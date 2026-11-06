/* F&O Desk - static site on GitHub Pages, data in Supabase.
   Tabs (hash routes): #/stocks  #/index  #/chain  #/swing  #/watch  #/trades  #/record  #/readme
   Without Supabase settings in config.js it runs in preview mode on ./sample. */
"use strict";

const CFG = window.DESK_CONFIG || {};
const LIVE = Boolean(CFG.supabaseUrl && CFG.supabaseAnonKey && window.supabase);
const sb = LIVE ? window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey, {
  auth: { flowType: "pkce", detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
}) : null;

const state = { idx: "NIFTY", ocSym: "NIFTY", ocExp: null, ocAll: false, tradeView: "all", session: null };
const SYMS = ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];
let refreshTimer = null;

// ------------------------------------------------------------------ helpers
function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) node.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return node;
}
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const isNum = (v) => typeof v === "number" && isFinite(v);
const fmt = (v, d = 2) => (isNum(v) ? v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) : "–");
const fmt0 = (v) => fmt(v, 0);
const pct = (v, d = 2, signed = true) => (isNum(v) ? `${signed && v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–");
const sign = (v) => (isNum(v) ? (v > 0 ? "pos" : v < 0 ? "neg" : "") : "muted");
const inr = (v) => (isNum(v) ? `${v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "–");
function compact(v) {
  if (!isNum(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e7) return `${(v / 1e7).toFixed(1)}Cr`;
  if (a >= 1e5) return `${(v / 1e5).toFixed(1)}L`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return fmt(v, Number.isInteger(v) || a >= 10 ? 0 : 2);
}
function when(ts) {
  if (!ts) return "–";
  const d = new Date(String(ts).replace(" ", "T"));
  if (isNaN(d)) return ts;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}
function dayLabel(ts) {
  const d = new Date(String(ts).replace(" ", "T"));
  return isNaN(d) ? "" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function sideTag(side) {
  const k = side === "Long" || side === "LONG" ? "long" : side === "Short" || side === "SHORT" ? "short" : "none";
  const label = { long: "Long", short: "Short", none: side === "NO TRADE" ? "No trade" : (side || "–") }[k];
  return h("span", { class: `side ${k}` }, h("i"), label);
}
function stat(k, v, d, cls) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, k), h("div", { class: `v ${cls || ""}` }, v), d ? h("div", { class: "d" }, d) : null);
}
function meterBar(v, max = 100) {
  const w = isNum(v) ? Math.max(0, Math.min(100, (v / max) * 100)) : 0;
  return h("span", { class: "meter" }, h("span", { class: "bar" }, h("b", { style: `width:${w}%` })), h("em", null, isNum(v) ? Math.round(v) : "–"));
}
function render(node, ...kids) { node.replaceChildren(...kids.flat().filter((k) => k != null && k !== false)); }
function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* off */ } }

// ------------------------------------------------------------------ data
const sampleTrades = [];
let sampleLoaded = false;
async function doc(key) {
  if (LIVE) {
    const { data, error } = await sb.from("docs").select("data,updated_at").eq("key", key).maybeSingle();
    if (error) throw new Error(error.message);
    return data ? data.data : null;
  }
  const r = await fetch(`sample/${key}.json`, { cache: "no-cache" });
  return r.ok ? r.json() : null;
}
async function loadTrades() {
  if (LIVE) {
    const { data, error } = await sb.from("trades").select("*").order("entry_time", { ascending: false });
    if (error) throw new Error(error.message);
    return data;
  }
  if (!sampleLoaded) {
    const r = await fetch("sample/trades.json", { cache: "no-cache" });
    if (r.ok) sampleTrades.push(...(await r.json()));
    sampleLoaded = true;
  }
  return sampleTrades.slice().sort((a, b) => String(b.entry_time).localeCompare(String(a.entry_time)));
}
async function addTrade(t) {
  if (LIVE) {
    const { error } = await sb.from("trades").insert(t);
    if (error) throw new Error(error.message);
    return;
  }
  sampleTrades.push({ ...t, id: Date.now() });
}
async function updateTrade(id, vals, mustChange = false) {
  if (LIVE) {
    const { data, error } = await sb.from("trades").update(vals).eq("id", id).select("id");
    if (error) throw new Error(error.message);
    // the database refuses changes to a closed trade once its fix window is over
    if (mustChange && !(data && data.length)) throw new Error("this trade is now locked (the 7:40 pm check has passed). Reload the page.");
    return;
  }
  Object.assign(sampleTrades.find((x) => x.id === id) || {}, vals);
}
async function deleteTrade(id) {
  if (LIVE) {
    const { error } = await sb.from("trades").delete().eq("id", id);
    if (error) throw new Error(error.message);
    return;
  }
  const i = sampleTrades.findIndex((x) => x.id === id);
  if (i >= 0) sampleTrades.splice(i, 1);
}
// ------------------------------------------------------------------ watchlist data
const sampleWatch = [];
async function loadWatch() {
  if (!LIVE) return sampleWatch.slice();
  const { data, error } = await sb.from("watchlist").select("*").order("added_at", { ascending: false });
  if (error) throw new Error(/watchlist/i.test(error.message) && /exist|schema/i.test(error.message)
    ? "the watchlist table is not set up yet (run supabase/007_watchlist.sql)" : error.message);
  const today = istDate();
  return data.filter((w) => String(w.expires_on) >= today);
}
async function addWatch(row) {
  if (!LIVE) { sampleWatch.unshift({ ...row, id: Date.now(), added_at: new Date().toISOString() }); return; }
  const { error } = await sb.from("watchlist").insert(row);
  if (error) throw new Error(error.message);
}
async function deleteWatch(id) {
  if (!LIVE) { const i = sampleWatch.findIndex((w) => w.id === id); if (i >= 0) sampleWatch.splice(i, 1); return; }
  const { error } = await sb.from("watchlist").delete().eq("id", id);
  if (error) throw new Error(error.message);
}
/* today's date in India, YYYY-MM-DD */
function istDate(d = new Date()) {
  return new Date(d.getTime() + 330 * 60000).toISOString().slice(0, 10);   // UTC + 5:30
}
/* the n-th market day (Mon-Fri) after `from` (YYYY-MM-DD). NSE holidays are not counted. */
function marketDaysAfter(from, n) {
  const d = new Date(`${from}T12:00:00Z`);
  let left = n;
  while (left > 0) { d.setUTCDate(d.getUTCDate() + 1); const wd = d.getUTCDay(); if (wd !== 0 && wd !== 6) left -= 1; }
  return d.toISOString().slice(0, 10);
}
const WATCH_DAYS = 3;

async function swingEvents() {
  if (!LIVE) return [];
  const since = new Date(Date.now() - 8 * 86400000).toISOString().slice(0, 10);
  const { data, error } = await sb.from("swing_events").select("ts,day,symbol,direction,strength,score,spot,signal")
    .gte("day", since).order("ts", { ascending: false }).limit(60);
  return error ? [] : data;
}
async function requestScan(kind) {
  if (!LIVE) return { status: "preview" };
  const { data, error } = await sb.from("scan_requests").insert({ kind }).select("status,created_at").single();
  if (error) throw new Error(error.message);
  return data;
}
async function swingHistory() {
  if (!LIVE) return [];
  const { data, error } = await sb.from("swing_history").select("day,symbol,direction,strength,score,spot")
    .order("day", { ascending: false }).limit(75);
  return error ? [] : data;
}

// ------------------------------------------------------------------ charts
function niceTicks(min, max, count = 4) {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) { min -= 1; max += 1; }
  const step0 = (max - min) / count, mag = Math.pow(10, Math.floor(Math.log10(step0))), n = step0 / mag;
  const step = (n >= 5 ? 10 : n >= 2 ? 5 : n >= 1 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function dayTicks(xs, maxTicks) {
  const idx = [];
  for (let i = 1; i < xs.length; i++) if (String(xs[i]).slice(0, 10) !== String(xs[i - 1]).slice(0, 10)) idx.push(i);
  const every = Math.max(1, Math.ceil(idx.length / maxTicks));
  return idx.filter((_, k) => k % every === 0);
}
function onResize(node, fn) {
  let last = 0;
  new ResizeObserver(() => { const w = Math.round(node.clientWidth); if (w && w !== last) { last = w; fn(w); } }).observe(node);
}
/* cfg: { xs, series:[{name, values, color}], bars, height, fmt, refs:[{y,label}], tipRows(i), domain } */
function timeChart(cfg) {
  const plot = h("div", { class: "plot" });
  const tip = h("div", { class: "tip", role: "status" });
  plot.append(tip);
  const f = cfg.fmt || ((v) => fmt(v, 2));
  function draw(W) {
    plot.querySelector("svg")?.remove();
    const H = cfg.height || 180, m = { l: 48, r: 10, t: 10, b: 22 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b, n = cfg.xs.length;
    if (!n) { plot.prepend(h("p", { class: "empty" }, "No data yet.")); return; }
    let lo = Infinity, hi = -Infinity;
    for (const ser of cfg.series) for (const v of ser.values) if (isNum(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    for (const r of cfg.refs || []) { lo = Math.min(lo, r.y); hi = Math.max(hi, r.y); }
    if (cfg.bars) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = (hi - lo) * 0.08 || 1;
    if (!cfg.bars) { lo -= pad; hi += pad; } else { hi += pad * 0.5; lo -= lo < 0 ? pad * 0.5 : 0; }
    const x = (i) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": cfg.label || "" });
    for (const t of niceTicks(lo, hi, 4)) {
      svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: css("--grid") }));
      svg.append(s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end", class: "axis-text" }, (cfg.tickFmt || compact)(t)));
    }
    if (lo < 0 && hi > 0) svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), stroke: css("--axis") }));
    for (const r of cfg.refs || []) {
      svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(r.y), y2: y(r.y), stroke: css("--muted"), "stroke-width": 1, opacity: 0.6 }));
      svg.append(s("text", { x: W - m.r - 2, y: y(r.y) - 4, "text-anchor": "end", class: "axis-text" }, r.label));
    }
    for (const i of dayTicks(cfg.xs, Math.max(3, Math.floor(iw / 70)))) {
      svg.append(s("text", { x: x(i), y: H - 6, "text-anchor": "middle", class: "axis-text" }, dayLabel(cfg.xs[i])));
    }
    if (cfg.bars) {
      const ser = cfg.series[0], bw = Math.max(1, Math.min(14, iw / n - 1));
      ser.values.forEach((v, i) => {
        if (!isNum(v)) return;
        svg.append(s("rect", { x: x(i) - bw / 2, y: Math.min(y(0), y(v)), width: bw, height: Math.max(1, Math.abs(y(v) - y(0))),
          fill: v >= 0 ? css("--up") : css("--down"), opacity: ser.marks && ser.marks[i] ? 0.45 : 1 }));
      });
    } else {
      for (const ser of cfg.series) {
        let d = "", pen = false;
        ser.values.forEach((v, i) => { if (!isNum(v)) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
        svg.append(s("path", { d, fill: "none", stroke: ser.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
        ser.values.forEach((v, i) => {   // isolated points (e.g. the first snapshot) get a dot so they stay visible
          if (isNum(v) && !isNum(ser.values[i - 1]) && !isNum(ser.values[i + 1])) svg.append(s("circle", { cx: x(i), cy: y(v), r: 3.5, fill: ser.color }));
        });
        (ser.marks || []).forEach((mk, i) => { if (mk && isNum(ser.values[i])) svg.append(s("rect", { x: x(i) - 3, y: y(ser.values[i]) - 3, width: 6, height: 6, fill: ser.color, transform: `rotate(45 ${x(i)} ${y(ser.values[i])})` })); });
      }
    }
    const cross = s("line", { y1: m.t, y2: m.t + ih, stroke: css("--axis"), visibility: "hidden" });
    const dots = cfg.bars ? [] : cfg.series.map((ser) => s("circle", { r: 4, fill: ser.color, stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }));
    const hit = s("rect", { x: m.l, y: 0, width: iw, height: H, fill: "transparent", tabindex: 0 });
    svg.append(cross, ...dots, hit);
    let cur = n - 1;
    function show(i) {
      i = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      cfg.series.forEach((ser, k) => {
        if (!dots[k]) return;
        const v = ser.values[i];
        if (isNum(v)) { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); dots[k].setAttribute("visibility", "visible"); }
        else dots[k].setAttribute("visibility", "hidden");
      });
      const rows = cfg.tipRows ? cfg.tipRows(i) : cfg.series.map((ser) => [ser.name, f(ser.values[i]), ser.color]);
      tip.replaceChildren(h("div", { class: "t-date" }, when(cfg.xs[i])), ...rows.map(([nm, val, col]) =>
        h("div", { class: "t-row" }, h("span", null, col ? h("i", { class: "key", style: `background:${col}` }) : null, nm), h("b", null, val))));
      tip.style.display = "block";
      const tw = tip.offsetWidth;
      tip.style.left = `${x(i) + 12 + tw > W ? x(i) - tw - 12 : x(i) + 12}px`;
      tip.style.top = `${m.t}px`;
    }
    const hide = () => { cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); tip.style.display = "none"; };
    hit.addEventListener("pointermove", (e) => { const r = svg.getBoundingClientRect(); cur = Math.round((((e.clientX - r.left) / r.width) * W - m.l) / iw * (n - 1)); show(cur); });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(cur));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { cur = Math.max(0, cur - 1); show(cur); e.preventDefault(); }
      if (e.key === "ArrowRight") { cur = Math.min(n - 1, cur + 1); show(cur); e.preventDefault(); }
    });
    plot.prepend(svg);
  }
  onResize(plot, draw);
  return plot;
}
const legend = (items) => h("div", { class: "legend" }, items.map(([n, c]) => h("span", null, h("i", { class: "line", style: `background:${c}` }), n)));
const chartCard = (title, note, chart, leg) => h("div", { class: "chart" }, h("h3", null, title), h("p", null, note), chart, leg || null);


// ------------------------------------------------------------------ chart links (TradingView)
const TV_INDEX = { NIFTY: "NSE:NIFTY", BANKNIFTY: "NSE:BANKNIFTY", FINNIFTY: "NSE:CNXFINANCE", MIDCPNIFTY: "NSE:NIFTY_MID_SELECT", SENSEX: "BSE:SENSEX" };
const TV_FUT = { NIFTY: "NSE:NIFTY1!", BANKNIFTY: "NSE:BANKNIFTY1!", FINNIFTY: "NSE:FINNIFTY1!", MIDCPNIFTY: "NSE:MIDCPNIFTY1!", SENSEX: "BSE:SENSEX1!" };
function tvSymbol(sym, kind) {
  if (kind === "fut") return TV_FUT[sym] || TV_INDEX[sym];
  if (kind === "index") return TV_INDEX[sym];
  return `NSE:${String(sym).toUpperCase().replace(/[&-]/g, "_")}`;
}
/* Small candlestick icon that opens the symbol on TradingView in a new tab.
   kind: "stock" (default), "index" (spot) or "fut" (continuous front-month futures). */
function chartLink(sym, kind = "stock", interval = "60") {
  const tv = tvSymbol(sym, kind);
  if (!tv) return null;
  const a = h("a", { class: "chart-link", href: `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tv)}&interval=${interval}`,
    target: "_blank", rel: "noopener", title: `Open ${tv} chart on TradingView`, "aria-label": `Open ${sym} chart on TradingView`,
    onclick: (e) => e.stopPropagation() });
  a.append(s("svg", { viewBox: "0 0 16 16", width: 15, height: 15, "aria-hidden": "true" },
    s("line", { x1: 4, y1: 2, x2: 4, y2: 14, stroke: "currentColor", "stroke-width": 1.4 }),
    s("rect", { x: 2.2, y: 5, width: 3.6, height: 6, rx: 0.6, fill: "currentColor" }),
    s("line", { x1: 11, y1: 1.5, x2: 11, y2: 12.5, stroke: "currentColor", "stroke-width": 1.4 }),
    s("rect", { x: 9.2, y: 3.5, width: 3.6, height: 6, rx: 0.6, fill: "none", stroke: "currentColor", "stroke-width": 1.4 })));
  return a;
}

/* A trade closed by hand can be fixed (edited or re-opened) until the next weekday 19:40 IST;
   trades closed by the jobs, and older ones, stay locked. Same rule in the database
   (supabase/011_fix_closed_trades.sql, trade_fix_until). */
function fixUntil(t) {
  if (t.status !== "closed" || !t.closed_at) return null;
  const IST = 5.5 * 3600e3, c = new Date(Date.parse(t.closed_at) + IST);   // IST clock in UTC fields
  for (let i = 0; i < 5; i++) {
    const d = new Date(Date.UTC(c.getUTCFullYear(), c.getUTCMonth(), c.getUTCDate() + i, 19, 40));
    if (d.getUTCDay() >= 1 && d.getUTCDay() <= 5 && d > c) return new Date(d.getTime() - IST);
  }
  return null;
}
const canFix = (t) => { const u = fixUntil(t); return !!u && Date.now() < u.getTime(); };
const fixLabel = (t) => {
  const u = fixUntil(t), sameDay = u && u.toDateString() === new Date().toDateString();
  return u ? `until ${sameDay ? "" : `${u.toLocaleDateString("en-IN", { weekday: "short" })} `}7:40 pm` : "";
};
/* Net % and ₹ for a trade closed at `exit` (same as the Close dialog). */
function exitVals(tr, exit) {
  const dir = tr.side === "Long" ? 1 : -1, vals = {};
  vals.net_pct_after_cost = +(((exit / tr.entry) - 1) * 100 * dir - (tr.kind === "index" ? 0 : 0.1)).toFixed(3);
  const q = tradeQty(tr);
  vals.pnl_inr = q ? +((exit - tr.entry) * dir * q - (tr.charges || 0)).toFixed(2) : null;
  return vals;
}
async function reopenTrade(t, onSaved) {
  if (!confirm(`Reopen ${t.symbol}? The exit (${fmt(t.exit)}, ${t.exit_reason || "closed"}) is removed and the trade goes back to Open.`)) return;
  try {
    await updateTrade(t.id, { status: "open", exit: null, exit_time: null, exit_reason: null, net_pct_after_cost: null, pnl_inr: null }, true);
    onSaved && onSaved();
  } catch (ex) { alert(`Could not reopen: ${ex.message}`); }
}

// ------------------------------------------------------------------ trade dialog
function tradeDialog(prefill, onSaved) {
  if (prefill && prefill.id && prefill.status === "closed" && !canFix(prefill)) return;   // closed trades lock after the 7:40 pm check
  const isClosed = !!(prefill && prefill.id && prefill.status === "closed");
  const dlg = document.getElementById("dlg");
  const t = { kind: "stock", side: "Long", source: "manual", ...prefill };
  const field = (label, name, attrs = {}, wide = false) =>
    h("label", { class: wide ? "wide" : null }, label, h("input", { name, value: t[name] ?? "", ...attrs }));
  const isIndex = t.kind === "index";
  const nowLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const err = h("p", { class: "err", role: "alert" });
  const form = h("form", { method: "dialog" },
    h("h2", null, prefill.id ? "Edit trade" : prefill.symbol ? `I took this trade: ${prefill.symbol}` : "Add a trade"),
    h("p", { class: "note" }, `${isIndex ? "Index futures" : "Stock futures"}. P&L ₹ = (sell − buy) × lots × lot size − charges: for a long, sell is the exit and buy the entry; for a short, sell is the entry and buy the exit.${isIndex ? "" : " P&L % is after 0.1% costs."}`),
    h("div", { class: "form-grid" },
      h("label", null, "Type", h("select", { name: "kind" },
        ["stock", "index"].map((k) => h("option", { value: k, selected: t.kind === k || null }, k === "stock" ? "Stock" : "Index futures")))),
      field("Symbol", "symbol", { required: true, autocapitalize: "characters" }),
      h("label", null, "Side", h("select", { name: "side" }, ["Long", "Short"].map((k) => h("option", { selected: t.side === k || null }, k)))),
      field("Entry time", "entry_time", { type: "datetime-local", value: (t.entry_time || nowLocal).slice(0, 16), required: true }),
      field("Entry", "entry", { type: "number", step: "any", required: true }),
      field("Stop", "stop", { type: "number", step: "any" }),
      field("Target", "target", { type: "number", step: "any" }),
      field("Lots", "lots", { type: "number", step: "1", min: "1", value: t.lots ?? 1 }),
      field("Lot size", "lot_size", { type: "number", step: "1", placeholder: isIndex ? "" : "filled from NSE if empty" }),
      isIndex ? field("Futures expiry", "expiry", { type: "date" }) : null,
      field("Charges ₹ (optional)", "charges", { type: "number", step: "any" }),
      isIndex ? field("Method", "method") : null,
      h("label", { class: "wide" }, "Notes", h("textarea", { name: "notes" }, t.notes || "")),
      ...(isClosed ? [
        field("Exit price", "exit", { type: "number", step: "any", required: true }),
        field("Exit time", "exit_time", { type: "datetime-local", value: String(t.exit_time || "").slice(0, 16), required: true }),
        field("Reason", "exit_reason", {}, true)] : [])),
    isClosed ? h("p", { class: "note" }, `This trade is closed. You can fix it ${fixLabel(t)}; after that it is locked.`) : null,
    err,
    h("div", { class: "btn-row" },
      h("button", { class: "btn primary", value: "save", type: "submit" }, "Save trade"),
      h("button", { class: "btn", value: "cancel", type: "button", onclick: () => dlg.close() }, "Cancel")));
  form.querySelector("select[name=kind]").addEventListener("change", (e) => tradeDialog({ ...prefill, ...readForm(form), kind: e.target.value }, onSaved));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = readForm(form);
    const row = {
      kind: v.kind, symbol: v.symbol.trim().toUpperCase(), side: v.side, entry_time: v.entry_time,
      entry: +v.entry, stop: v.stop ? +v.stop : null, target: v.target ? +v.target : null, notes: v.notes || null,
      source: t.source || "manual",
    };
    Object.assign(row, { lots: +v.lots || 1, lot_size: +v.lot_size || null, charges: v.charges ? +v.charges : 0 });
    if (v.kind === "index") Object.assign(row, { expiry: v.expiry || null, method: v.method || null, instrument: "Futures" });
    if (isClosed) {
      Object.assign(row, { exit: +v.exit, exit_time: v.exit_time, exit_reason: v.exit_reason || null });
      Object.assign(row, exitVals({ ...t, ...row }, row.exit));
    }
    try {
      if (prefill.id) await updateTrade(prefill.id, row, isClosed); else await addTrade({ ...row, status: "open" });
      dlg.close();
      onSaved && onSaved();
    } catch (ex) { err.textContent = `Could not save: ${ex.message}`; }
  });
  dlg.replaceChildren(form);
  if (!dlg.open) dlg.showModal();
}
function readForm(form) { return Object.fromEntries(new FormData(form).entries()); }

/* "Move to watchlist": confirm Long/Short (and a note), keep for 3 market days. */
function watchDialog(item) {
  const dlg = document.getElementById("dlg");
  const until = marketDaysAfter(istDate(), WATCH_DAYS);
  const err = h("p", { class: "err", role: "alert" });
  const sideBtn = (sd) => h("label", { class: `side-pick ${sd.toLowerCase()}` },
    h("input", { type: "radio", name: "side", value: sd, checked: item.side === sd || null }), sd);
  const form = h("form", { method: "dialog" },
    h("h2", null, `Move ${item.symbol} to watchlist`),
    h("p", { class: "note" }, `${item.kind === "index" ? "Index futures" : "Stock"} · ${item.method || item.source || ""}. It stays on the watchlist until ${new Date(`${until}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })} (${WATCH_DAYS} market days), then it is removed.`),
    h("div", { class: "form-grid" },
      h("div", { class: "wide" }, h("span", { class: "note" }, "Watch for a"), h("div", { class: "side-row" }, sideBtn("Long"), sideBtn("Short"))),
      h("label", { class: "wide" }, "Note (optional)", h("textarea", { name: "notes" }, item.notes || ""))),
    err,
    h("div", { class: "btn-row" },
      h("button", { class: "btn primary", type: "submit" }, "Add to watchlist"),
      h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Cancel")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = readForm(form);
    if (!v.side) { err.textContent = "Choose Long or Short."; return; }
    const row = { kind: item.kind, symbol: item.symbol, side: v.side, expires_on: until,
      entry: isNum(item.entry) ? item.entry : null, stop: isNum(item.stop) ? item.stop : null, target: isNum(item.target) ? item.target : null,
      lot_size: item.lot_size || null, expiry: item.expiry || null, method: item.method || null, source: item.source || null,
      notes: v.notes || null, signal_time: item.signal_time || null };
    try { await addWatch(row); dlg.close(); location.hash = "#/watch"; } catch (ex) { err.textContent = `Could not save: ${ex.message}`; }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
}

function closeDialog(tr, onSaved) {
  const dlg = document.getElementById("dlg");
  const nowLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const err = h("p", { class: "err", role: "alert" });
  const form = h("form", { method: "dialog" },
    h("h2", null, `Close ${tr.symbol} ${tr.side}`),
    h("div", { class: "form-grid" },
      h("label", null, "Exit price", h("input", { name: "exit", type: "number", step: "any", required: true })),
      h("label", null, "Exit time", h("input", { name: "exit_time", type: "datetime-local", value: nowLocal, required: true })),
      h("label", { class: "wide" }, "Reason", h("input", { name: "exit_reason", value: "closed by hand" }))),
    err,
    h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "submit" }, "Close trade"),
      h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Cancel")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = readForm(form), exit = +v.exit;
    const vals = { exit, exit_time: v.exit_time, exit_reason: v.exit_reason, status: "closed", ...exitVals(tr, exit) };
    if (vals.pnl_inr === null) delete vals.pnl_inr;
    try { await updateTrade(tr.id, vals); dlg.close(); onSaved && onSaved(); } catch (ex) { err.textContent = ex.message; }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
}

// ------------------------------------------------------------------ tab 1: stock screener
/* Two views (6 Nov 2026): Price Action (chart only) and Price+OI (chart + futures OI).
   The old 50 EMA cross rules still run in the background; they are only in Track record. */
const SCR_TABS = [["pa", "Price Action"], ["po", "Price+OI"]];
const REJ_LABEL = { strength: "Wick strength", tight: "First touch", length: "Stop room", ema: "Trend strength", margin: "Shakeout depth" };
const PART_LABEL = { strength: "Candle strength", size: "Candle size", volume: "Volume", tight: "Base tightness", length: "Base length",
  ema: "Near 50 EMA", margin: "Breakout margin", hour_oi: "Signal-hour OI", day_oi: "Day OI", sector: "Sector" };
function oiText(c, label) {
  if (!c) return null;
  if (c.ok) return `${label}: OI ${pct(c.oi_pct, 2)} = ${c.mult}x usual (${pct(c.usual, 2, false)})`;
  return `${label}: ${c.why}`;
}
async function viewStocks(app) {
  const d = await doc("stock_screener");
  const tab = state.scrTab || "pa";
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Screener view" },
    SCR_TABS.map(([k, l]) => h("button", { type: "button", "aria-pressed": String(tab === k), onclick: () => { state.scrTab = k; route(); } }, l)));
  const head = (sub) => h("div", { class: "page-head" }, h("div", { class: "head-left" }, h("h1", null, "F&O stock screener"), seg), sub ? h("p", null, sub) : null);
  if (!d) return render(app, head(null), h("p", { class: "empty" }, "No scan yet. The first scan runs at about 10:20 on the next market day."));
  const view = (d[tab] || {});
  const ideas = view.ideas || [];
  const isPO = tab === "po";
  const W = isPO ? { strength: 10, size: 8, volume: 7, tight: 12, length: 8, ema: 10, margin: 10, hour_oi: 15, day_oi: 10, sector: 10 }
    : { strength: 14, size: 11, volume: 10, tight: 16, length: 11, ema: 14, margin: 14, sector: 10 };
  const early = d.early ? h("div", { class: "banner expiry" }, h("b", null, "Early scan. "),
    `No hourly candle has closed yet today (the first one closes at 10:15). These setups come from the previous session's candles, up to ${new Date(d.early.last_candle).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}. New setups for today start with the 10:19 scan.`) : null;
  const source = isPO ? "Price+OI" : "Price Action";
  const label = (x) => `${source}: ${x.setup} ${x.signal_time.slice(11, 16)}${x.confirm === "next candle" ? ", OI next candle" : ""}`;
  const watch = (x) => watchDialog({ kind: "stock", symbol: x.symbol, side: x.side, entry: x.levels.entry, stop: x.levels.stop,
    target: x.levels.target, lots: 1, lot_size: x.lot_size, source: "screener", signal_time: x.signal_time, method: label(x) });
  const took = (x) => tradeDialog({ kind: "stock", symbol: x.symbol, side: x.side, entry: x.levels.entry, stop: x.levels.stop,
    target: x.levels.target, lot_size: x.lot_size, source, notes: label(x) }, () => { location.hash = "#/trades"; });
  const futText = (x) => x.futures ? `Futures today: ${x.futures.buildup}, OI ${pct(x.futures.pchg_oi, 1)}, price ${pct(x.futures.pchange)}` : "Futures: no quote";
  const top = ideas.filter((x) => x.top_rank).sort((a, b) => a.top_rank - b.top_rank);

  const topCards = () => top.map((x) => h("div", { class: "idea top" },
    h("h3", null, h("span", null, h("span", { class: "rank" }, `#${x.top_rank}`), " ", x.symbol, " ", chartLink(x.symbol)),
      h("small", null, `score ${Math.round(x.scoring.score)}`)),
    h("div", { class: "btn-row" }, sideTag(x.side), h("span", { class: "meta" }, `${x.setup} · signal ${x.signal_time.slice(11, 16)}, ${x.entry_status}`),
      x.lot_size ? h("span", { class: "flag fno" }, `lot ${x.lot_size}`) : null,
      x.also ? h("span", { class: "flag", title: "The same setup also qualifies on the other tab" }, isPO ? "also Price Action" : "also Price+OI") : null,
      x.confirm === "next candle" ? h("span", { class: "flag", title: "Futures OI surged one candle after the breakout; entry moved one candle later" }, "OI next candle") : null),
    levelsBox(x.levels),
    h("div", { class: "meta" }, x.base ? `Base: ${x.base.n} candles, range ${pct(x.base.range_pct, 1, false)} (${(x.base.range_pct / x.base.adr_pct).toFixed(1)}x daily range). ` : "",
      `Breakout candle ${pct(x.candle_pct, 1, false)}; stop ${pct(x.levels.risk_pct, 1, false)} away.`),
    h("div", { class: "meta" }, futText(x)),
    h("div", { class: "meta" }, oiText(x.oi_breakout, "Breakout candle"), x.oi_next ? ` · ${oiText(x.oi_next, "next candle")}` : ""),
    x.rej_detail ? h("div", { class: "meta" }, `Rejection: wick ${x.rej_detail.wick_vs_adr ?? "–"}× the daily range, flushed ${x.rej_detail.depth_vs_adr ?? "–"}× the daily range past the EMA; ${x.rej_detail.earlier_touches} earlier EMA touch${x.rej_detail.earlier_touches === 1 ? "" : "es"} in ~3 sessions; stop ${x.rej_detail.stop_vs_adr}× the daily range.`) : null,
    h("div", { class: "parts" }, Object.keys(W).map((k) => part((x.kind === "rejection" && REJ_LABEL[k]) || PART_LABEL[k], (x.scoring[k] || 0) / W[k] * 100, `${Math.round(x.scoring[k] || 0)}/${W[k]}`))),
    x.sector ? h("div", { class: "meta" }, `${x.sector} sector is ${x.sector_quadrant || "leading"} on the Sector Strength RRG`) : null,
    warnList(x.warnings),
    h("div", { class: "btn-row" }, h("button", { class: "btn primary small", type: "button", onclick: () => took(x) }, "I took this trade"),
      h("button", { class: "btn small", type: "button", onclick: () => watch(x) }, "Move to watchlist"))));

  // every run of the day (Run 1, Run 2 ...) for this tab
  const dayDoc = await doc("stock_screener_day").catch(() => null);
  let runs = dayDoc && dayDoc.date === String(d.ts).slice(0, 10) && (dayDoc.runs || []).length ? dayDoc.runs.slice() : [];
  if (!runs.some((r) => r.ts === d.ts)) runs.push({ ts: d.ts, early: Boolean(d.early), [tab]: ideas });
  runs = runs.filter((r) => r.pa || r.po).sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  const seen = new Set(), firstRun = {};
  runs.forEach((r, i) => {
    r.list = (r[tab] || []).map((x) => ({ ...x }));
    r.list.forEach((x) => {
      const k = `${x.symbol}|${x.side}|${x.signal_time}`;
      x.repeat = seen.has(k) ? firstRun[k] : null;
      if (!seen.has(k)) { seen.add(k); firstRun[k] = i + 1; }
    });
    r.list.sort((a, b) => (a.top_rank || 9) - (b.top_rank || 9) || (b.scoring?.score || 0) - (a.scoring?.score || 0));
  });
  const ideaTable = (list) => h("table", null,
    h("thead", null, h("tr", null, ["Stock", "Side", "Setup", "Signal", "Entry", "Stop", "Target", "Risk", isPO ? "OI" : "Futures today", "Warnings", "Score", ""].map((c, i) =>
      h("th", { class: i < 3 ? "l" : null }, c)))),
    h("tbody", null, list.map((x) => h("tr", { style: "cursor:default" },
      h("td", { class: "l name" }, x.symbol, x.top_rank ? h("span", { class: "flag fno" }, `Top ${x.top_rank}`) : null,
        x.repeat ? h("span", { class: "flag", title: `First listed in Run ${x.repeat}` }, `also Run ${x.repeat}`) : null,
        x.also ? h("span", { class: "flag", title: "Also qualifies on the other tab" }, isPO ? "also PA" : "also P+OI") : null, chartLink(x.symbol)),
      h("td", { class: "l" }, sideTag(x.side)),
      h("td", { class: "l" }, x.setup),
      h("td", null, x.signal_time.slice(11, 16)),
      h("td", null, fmt(x.levels.entry)), h("td", { title: x.levels.stop_from }, fmt(x.levels.stop)), h("td", null, fmt(x.levels.target)),
      h("td", null, pct(x.levels.risk_pct, 1, false)),
      isPO ? h("td", { title: [oiText(x.oi_breakout, "Breakout candle"), oiText(x.oi_next, "Next candle"), futText(x)].filter(Boolean).join("\n") },
        `${x.confirm === "next candle" ? (x.oi_next?.mult ?? "–") : (x.oi_breakout?.mult ?? "–")}x${x.confirm === "next candle" ? " (next)" : ""}`)
        : h("td", { title: futText(x) }, x.futures ? `${x.futures.buildup.replace(" build-up", "")} ${pct(x.futures.pchg_oi, 1)}` : "–"),
      h("td", null, x.warnings && x.warnings.length ? h("span", { class: "warn-count", title: x.warnings.join("\n") }, x.warnings.length) : "–"),
      h("td", null, Math.round(x.scoring?.score || 0)),
      h("td", null, h("div", { class: "btn-row nowrap" }, h("button", { class: "btn small", type: "button", onclick: () => took(x) }, "I took this trade"),
        h("button", { class: "btn small", type: "button", onclick: () => watch(x) }, "Watchlist")))))));

  const smallTable = (rows, cols) => h("table", null,
    h("thead", null, h("tr", null, cols.map(([c], i) => h("th", { class: "l" }, c)))),
    h("tbody", null, rows.map((x) => h("tr", { style: "cursor:default" }, cols.map(([, f], i) => h("td", { class: i === 0 ? "l name" : "l" }, f(x)))))));
  const stockCell = (x) => [x.symbol, chartLink(x.symbol)];
  const waiting = isPO ? (view.waiting || []) : [];
  const notListed = isPO ? (view.rejected || []) : (view.others || []);

  const intro = isPO
    ? "Price Action setups that futures OI confirms: the build-up in the trade's direction must be at least 1.5× the stock's usual hourly OI change in the breakout candle, or in the next candle (then entry moves one candle later). A rising or falling 50 EMA also needs the day's futures build-up. Your trades close only at the stop or by hand; the target is shown. Every idea is logged in Track record."
    : "Chart only. A solid hourly candle breaks out of a base (7–30 candles, range at most 1.5× the stock's daily range). Rising or flat 50 EMA: 1st or 2nd base. Falling 50 EMA: the first breakout is ignored until price holds above it. Shorts mirror this (no shorts on a rising EMA). Stop at the breakout candle (if it is 2%+ of price) or the base; skipped above 5%. Futures OI is shown but not scored. Your trades close only at the stop or by hand; the target is shown.";
  const scoreNote = isPO ? "Candle 25 (strength 10, size 8, volume 7) + base 20 + near 50 EMA 10 + breakout margin 10 + signal-hour OI 15 + day OI 10 + sector 10"
    : "Candle 35 (strength 14, size 11, volume 10) + base 27 + near 50 EMA 14 + breakout margin 14 + sector 10";
  render(app,
    head(`Last scan ${when(d.ts)}, ${d.scanned} F&O stocks`),
    scanBar(d.ts),
    early,
    h("p", { class: "intro" }, intro),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Top 5"), h("p", null, scoreNote)),
      top.length ? h("div", { class: "ideas" }, topCards()) : h("p", { class: "empty" }, "No setups in this scan.")),
    isPO ? h("section", null, h("div", { class: "section-head" }, h("h2", null, `Waiting for OI (${waiting.length})`),
      h("p", null, "Chart setup done; futures OI has not surged yet. Checked again after the next candle")),
      waiting.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, smallTable(waiting, [
        ["Stock", stockCell], ["Side", (x) => sideTag(x.side)], ["Setup", (x) => x.setup], ["Signal", (x) => x.signal_time.slice(11, 16)],
        ["Base high / low", (x) => (x.base ? `${fmt(x.base.hi)} / ${fmt(x.base.lo)}` : "–")], ["Why waiting", (x) => x.reason.replace("Waiting for OI: ", "")]]))) : h("p", { class: "empty" }, "None.")) : null,
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `All trade ideas today (${seen.size})`),
      h("p", null, `${runs.length} run${runs.length === 1 ? "" : "s"}, newest first. Kept for the day; a new day starts fresh.`)),
      runs.slice().reverse().map((r, i) => {
        const n = runs.length - i, list = r.list;
        const tops = list.filter((x) => x.top_rank).sort((a, b) => a.top_rank - b.top_rank).map((x) => x.symbol);
        const fresh = list.filter((x) => !x.repeat).length;
        return h("details", { class: "run", open: i === 0 || null },
          h("summary", null, h("b", null, `Run ${n} · ${String(r.ts).slice(11, 16)}`), r.early ? h("span", { class: "flag" }, "early") : null,
            h("span", { class: "muted" }, ` ${list.length} idea${list.length === 1 ? "" : "s"}${fresh !== list.length ? ` (${fresh} new)` : ""}${tops.length ? ` · Top 5: ${tops.join(", ")}` : ""}`)),
          list.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, ideaTable(list))) : h("p", { class: "empty" }, "No ideas in this run."));
      })),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `${isPO ? "Rejected by futures OI" : "Breakouts that did not qualify"} (${notListed.length})`),
      h("p", null, isPO ? "Good chart, but OI never confirmed or the day's build-up was against the trade" : "Late base, falling-EMA first breakout, stop too far, already stopped …")),
      notListed.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, smallTable(notListed, [
        ["Stock", stockCell], ["Side", (x) => sideTag(x.side)], ["Signal", (x) => x.signal_time.slice(11, 16)], ["Why", (x) => x.reason]]))) : h("p", { class: "empty" }, "None.")),
    d.problems && d.problems.length ? h("p", { class: "note" }, `Data notes: ${d.problems.slice(0, 3).join("; ")}`) : null);
}
let scanPoll = null;
function scanBar(lastTs) {
  const msg = h("span", { class: "note", role: "status" },
    "Scans automatically about 4 minutes after each hourly candle closes: 10:19, 11:19 … 15:19 and 15:34. A manual scan before 10:15 shows the previous session's signals.");
  const btn = h("button", { class: "btn primary", type: "button" }, "Run scanner now");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    msg.textContent = "Starting the scan…";
    try {
      const r = await requestScan("screener");
      if (r.status === "preview") { msg.textContent = "Preview mode: scans run only on the live desk."; btn.disabled = false; return; }
      if (r.status === "skipped") { msg.textContent = "A scan was started less than 3 minutes ago; its results will appear here shortly."; }
      else if (r.status !== "sent") { msg.textContent = "The scan could not be started: the GitHub token is missing in Supabase."; btn.disabled = false; return; }
      else msg.textContent = "Scan started. Results usually appear in 3–5 minutes; this page updates by itself.";
      clearInterval(scanPoll);
      const t0 = Date.now();
      scanPoll = setInterval(async () => {
        const d = await doc("stock_screener").catch(() => null);
        if (d && d.ts !== lastTs) { clearInterval(scanPoll); route(); }
        else if (Date.now() - t0 > 10 * 60000) { clearInterval(scanPoll); msg.textContent = "No new results after 10 minutes. Check the Actions tab on GitHub."; btn.disabled = false; }
      }, 30000);
    } catch (e) { msg.textContent = `Could not start the scan: ${e.message}`; btn.disabled = false; }
  });
  return h("div", { class: "filters" }, btn, msg);
}
/* Futures OI and price over the signal hour (since just after the signal candle opened). */
function hourText(hr) {
  if (!hr) return "Signal hour: no OI snapshot yet (the scan saves one each hour)";
  return `Signal hour: ${hr.buildup}, OI ${pct(hr.oi_pct, 1)}, price ${pct(hr.px_pct)}${hr.from_prev_day ? " (since yesterday's close)" : ` since ${hr.since.slice(11, 16)}`}`;
}
/* Proposed score (testing only; the Top 5 still uses the live score). */
function proposedTitle(x) {
  const v = x.v2;
  return `Proposed score (testing): signal-hour OI ${v.hour_oi}${v.hour_known ? "" : " (day OI used: no snapshot yet)"} + day OI ${v.day_oi} + candle shape ${v.shape} + size ${v.size} + sector ${x.scoring.boost}`;
}
function proposedLine(x) {
  if (!x.v2) return null;
  return h("div", { class: "meta proposed", title: proposedTitle(x) },
    `Proposed (testing): ${Math.round(x.v2.score)}, rank #${x.rank_v2} · hour OI ${Math.round(x.v2.hour_oi)} · day OI ${Math.round(x.v2.day_oi)} · shape ${Math.round(x.v2.shape)} · size ${Math.round(x.v2.size)} · sector ${x.scoring.boost}`);
}
function warnList(w) {
  return w && w.length ? h("ul", { class: "warns", "aria-label": "Warnings" }, w.map((t) => h("li", null, t))) : null;
}
function levelsBox(lv) {
  return h("div", { class: "lv" },
    h("div", null, h("span", null, "Entry"), h("b", null, fmt(lv.entry))),
    h("div", null, h("span", null, `Stop (${lv.stop_from || "stop"})`), h("b", null, fmt(lv.stop))),
    h("div", null, h("span", null, "Target 1:2"), h("b", null, fmt(lv.target))));
}
function part(label, v, txt) {
  return h("div", null, h("span", null, label), h("span", { class: "bar" }, h("b", { style: `width:${Math.max(0, Math.min(100, v || 0))}%` })), h("em", null, txt));
}
function pageHead(title, sub) {
  return h("div", { class: "page-head" }, h("h1", null, title), sub ? h("p", null, sub) : null);
}

// ------------------------------------------------------------------ tab 2: index analysis
async function viewIndex(app) {
  const d = await doc("index_dashboard");
  if (!d) return render(app, pageHead("F&O index analysis", null), h("p", { class: "empty" }, "No snapshot yet. Snapshots run every 15 minutes in market hours."));
  const cards = d.cards || [];
  const cur = cards.find((c) => c.symbol === state.idx) || cards[0];
  const pick = (sym) => { state.idx = sym; store("desk-idx", sym); route(); };

  const cardEls = cards.map((c) => h("button", { class: "icard", type: "button", "aria-pressed": String(c.symbol === state.idx), onclick: () => pick(c.symbol) },
    h("div", { class: "k" }, h("span", null, c.symbol), h("span", { class: sign(c.pchange) }, pct(c.pchange))),
    h("div", { class: "v" }, fmt(c.spot)),
    h("div", { class: "x" }, `PCR ${isNum(c.pcr) ? c.pcr.toFixed(2) : "–"} (${c.pcr_kind})`, h("br"),
      c.fut ? `${c.fut.state}` : "No futures feed", h("br"),
      `Swing: ${c.signal === "LONG" ? "Long" : c.signal === "SHORT" ? "Short" : "No trade"} ${isNum(c.signal_score) ? `(${c.signal_score >= 0 ? "+" : ""}${c.signal_score})` : ""}`)));
  if (d.vix) cardEls.push(h("div", { class: "icard", style: "cursor:default" },
    h("div", { class: "k" }, h("span", null, "India VIX"), h("span", { class: sign(-d.vix.pchange) }, pct(d.vix.pchange))),
    h("div", { class: "v" }, fmt(d.vix.last)),
    h("div", { class: "x" }, "Implied volatility of NIFTY options; rising VIX = more fear")));

  const banners = (d.warnings || []).map((w) => h("div", { class: `banner ${w.kind}` }, h("b", null, w.kind === "squeeze" ? "Squeeze risk. " : "Expiry. "), w.text));

  // NIFTY trend scale
  let trendPanel = null;
  if (d.trend) {
    const t = d.trend, posPct = ((Math.max(-5, Math.min(5, t.score)) + 5) / 10) * 100;
    trendPanel = h("div", { class: "panel" },
      h("h2", null, "NIFTY intraday trend scale"),
      h("p", { class: "sub" }, `Weekly chain plus futures, as of ${when(t.ts)}. Five factors from −1 to +1; zones at ±1 (mild), ±2 (moderate), ±3.5 (strong). A trend score, not a probability.`),
      h("div", { class: "zone" }, `${t.zone} (${t.score >= 0 ? "+" : ""}${t.score} of ±5)`),
      h("div", { class: "scale" }, h("div", { class: "track" }, Array.from({ length: 7 }, () => h("i"))),
        h("div", { class: "marker", style: `left:${posPct}%` }),
        h("div", { class: "ends" }, h("span", null, "Strong bearish"), h("span", null, "Neutral"), h("span", null, "Strong bullish"))),
      factorTable(t.factors));
  }

  // charts for the selected index
  const ch = (d.charts || {})[cur.symbol] || {};
  const pcr = ch.pcr || {};
  const mon = pcr.monthly || [], wk = pcr.weekly || [];
  const keys = [...new Set([...mon.map((p) => p.ts), ...wk.map((p) => p.ts)])].sort();
  const mMap = Object.fromEntries(mon.map((p) => [p.ts, p.pcr])), wMap = Object.fromEntries(wk.map((p) => [p.ts, p.pcr]));
  const wComb = Object.fromEntries(wk.map((p) => [p.ts, p.combined]));
  const pcrSeries = [{ name: "Monthly PCR", values: keys.map((k) => mMap[k] ?? null), color: css("--s2") }];
  if (wk.length) pcrSeries.push({ name: "Weekly PCR", values: keys.map((k) => wMap[k] ?? null), color: css("--s1"), marks: keys.map((k) => wComb[k]) });
  const fo = ch.futures_oi || [];
  const lv = cur;
  const charts = h("div", { class: "charts" },
    chartCard(`${cur.symbol} PCR, hourly`, `Last snapshot in each market hour, last 30 days. Lines at 0.8 (bearish below) and 1.2 (bullish above).${wk.length ? " Diamonds: weekly PCR includes the next weekly on expiry eve." : ""}`,
      timeChart({ xs: keys, series: pcrSeries, refs: [{ y: 0.8, label: "0.8" }, { y: 1.2, label: "1.2" }], fmt: (v) => (isNum(v) ? v.toFixed(2) : "–"), tickFmt: (v) => v.toFixed(1) }),
      legend(pcrSeries.map((x) => [x.name, x.color]))),
    fo.length ? chartCard(`${cur.symbol} futures OI, hourly`, "Current + next month combined", timeChart({ xs: fo.map((p) => p.ts),
      series: [{ name: "Futures OI", values: fo.map((p) => p.oi), color: css("--s1") }],
      tipRows: (i) => [["Futures OI", compact(fo[i].oi), css("--s1")], ["Near-month price", fmt(fo[i].near_ltp)]] })) :
      chartCard(`${cur.symbol} futures OI`, "", h("p", { class: "empty" }, cur.symbol === "SENSEX" ? "No public BSE futures feed for SENSEX." : "No futures history yet.")),
    fo.length ? chartCard("Hourly change in futures OI", "Like-for-like on the same contracts, so an expiring contract is not read as OI being cut (faded bars span an expiry roll).",
      timeChart({ xs: fo.map((p) => p.ts), bars: true, series: [{ name: "OI change", values: fo.map((p) => p.change), marks: fo.map((p) => p.rolled) }],
        tipRows: (i) => [["OI change", isNum(fo[i].change) ? `${fo[i].change > 0 ? "+" : ""}${compact(fo[i].change)}` : "–"], ...(fo[i].rolled ? [["", "Expiry roll"]] : [])] })) : null);

  render(app, 
    pageHead("F&O index analysis", `Snapshot ${when(d.ts)}`),
    banners.length ? h("div", null, banners) : null,
    h("div", { class: "cards" }, cardEls),
    h("div", { class: "grid-main" },
      h("div", { class: "panel" }, h("h2", null, `${cur.symbol}: levels and history`),
        h("div", { class: "stats" },
          stat("Support (max put OI)", fmt0(lv.support)), stat("Resistance (max call OI)", fmt0(lv.resistance)),
          stat("Max pain", fmt0(lv.max_pain)), stat("ATM IV", isNum(lv.atm_iv) ? `${lv.atm_iv.toFixed(1)}%` : "–"),
          stat("Futures", lv.fut ? lv.fut.state : "–", lv.fut ? `${pct(lv.fut.fut_pct)}, OI ${lv.fut.coi_total > 0 ? "+" : ""}${compact(lv.fut.coi_total)}` : null, "txt")),
        h("p", { class: "note" }, `${lv.pcr_kind === "weekly" ? "Weekly" : "Monthly"} chain, expiry ${lv.expiry || "–"}.`),
        charts),
      trendPanel || h("div")),
    (d.problems || []).length ? h("p", { class: "note" }, `Data notes: ${d.problems.slice(0, 3).join("; ")}`) : null);
}
function factorTable(factors) {
  return h("table", { class: "factors" },
    h("thead", null, h("tr", null, h("th", { class: "l" }, "Factor"), h("th", { class: "l" }, "Reading"), h("th", null, "Score"), h("th", { class: "l" }, "Read"))),
    h("tbody", null, (factors || []).map((f) => h("tr", null, h("td", { class: "l" }, f.factor), h("td", { class: "l" }, f.reading),
      h("td", { class: `score ${sign(f.score)}` }, `${f.score > 0 ? "+" : ""}${f.score}`), h("td", { class: "l muted" }, f.note)))));
}

// ------------------------------------------------------------------ tab 3: option chain
async function viewChain(app) {
  const d = await doc("option_chains");
  if (!d) return render(app, pageHead("Option chain", null), h("p", { class: "empty" }, "No snapshot yet."));
  const list = d.chains[state.ocSym] || [];
  let c = list.find((x) => x.expiry === state.ocExp) || list[0];
  const cols = d.columns;
  const ix = Object.fromEntries(cols.map((k, i) => [k, i]));
  const symSel = h("select", { onchange: (e) => { state.ocSym = e.target.value; state.ocExp = null; route(); } },
    SYMS.map((k) => h("option", { selected: k === state.ocSym || null }, k)));
  const expSel = h("select", { onchange: (e) => { state.ocExp = e.target.value; route(); } },
    list.map((x) => h("option", { value: x.expiry, selected: x === c || null }, `${dayLabel(x.expiry)} (${x.kind}, ${x.dte}d)`)));
  if (!c) return render(app, pageHead("Option chain", null), h("div", { class: "filters" }, symSel), h("p", { class: "empty" }, "No chain for this index yet."));
  const rows = c.rows;
  const atmI = rows.reduce((b, r, i) => (Math.abs(r[0] - c.spot) < Math.abs(rows[b][0] - c.spot) ? i : b), 0);
  const shown = state.ocAll ? rows : rows.slice(Math.max(0, atmI - 12), atmI + 13);
  const maxOI = Math.max(...shown.map((r) => Math.max(r[ix.ce_oi], r[ix.pe_oi])), 1);
  const cell = (r, k, side) => {
    const v = r[ix[k]];
    if (k.endsWith("_oi") && !k.endsWith("coi")) {
      return h("td", { class: `cell ${side} ${(side === "ce" && r[0] === c.resistance) || (side === "pe" && r[0] === c.support) ? "wall" : ""}` },
        h("span", { class: "b", style: `width:${(v / maxOI) * 100}%` }), h("span", null, compact(v)));
    }
    if (k.endsWith("coi")) return h("td", { class: `${side} ${sign(v)}` }, v ? `${v > 0 ? "+" : ""}${compact(v)}` : "–");
    if (k.endsWith("iv")) return h("td", { class: side }, v ? v.toFixed(1) : "–");
    return h("td", { class: side }, v ? fmt(v) : "–");
  };
  const table = h("table", { class: "oc" },
    h("thead", null,
      h("tr", null, h("th", { colspan: 4 }, "Calls"), h("th", null, ""), h("th", { colspan: 4 }, "Puts")),
      h("tr", null, ["OI", "Chg OI", "LTP", "IV", "Strike", "IV", "LTP", "Chg OI", "OI"].map((x) => h("th", null, x)))),
    h("tbody", null, shown.map((r) => {
      const k = r[0], isAtm = k === rows[atmI][0];
      return h("tr", { class: `${isAtm ? "atm" : ""} ${k < c.spot ? "itm-ce" : "itm-pe"}` },
        cell(r, "ce_oi", "ce"), cell(r, "ce_coi", "ce"), cell(r, "ce_ltp", "ce"), cell(r, "ce_iv", "ce"),
        h("td", { class: "k" }, fmt0(k)),
        cell(r, "pe_iv", "pe"), cell(r, "pe_ltp", "pe"), cell(r, "pe_coi", "pe"), cell(r, "pe_oi", "pe"));
    })));
  const ceT = rows.reduce((a, r) => a + r[ix.ce_oi], 0), peT = rows.reduce((a, r) => a + r[ix.pe_oi], 0);
  const ceC = rows.reduce((a, r) => a + r[ix.ce_coi], 0), peC = rows.reduce((a, r) => a + r[ix.pe_coi], 0);
  render(app, 
    pageHead("Option chain", `Snapshot ${when(c.ts)}`),
    h("div", { class: "filters" }, h("span", { class: "filter-label" }, "Index"), symSel, h("span", { class: "filter-label" }, "Expiry"), expSel,
      h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: state.ocAll || null, onchange: (e) => { state.ocAll = e.target.checked; route(); } }), "All strikes")),
    h("div", { class: "stats", style: "margin-top:12px" },
      stat("Spot", fmt(c.spot), `ATM ${fmt0(rows[atmI][0])}`),
      stat("PCR (total OI)", isNum(c.pcr) ? c.pcr.toFixed(2) : "–", `Change-in-OI PCR ${ceC > 0 ? (peC / ceC).toFixed(2) : "–"}`),
      stat("Support / resistance", `${fmt0(c.support)} / ${fmt0(c.resistance)}`, "Max put OI below / max call OI above"),
      stat("Max pain", fmt0(c.max_pain), `${c.dte} days to expiry`),
      stat("ATM IV", isNum(c.atm_iv) ? `${c.atm_iv.toFixed(1)}%` : "–", `Calls ${compact(ceT)} / puts ${compact(peT)} OI`)),
    h("div", { class: "panel" }, h("p", { class: "sub" }, "Shaded bars show OI relative to the largest on screen; outlined cells are the support and resistance walls; the thick line marks the ATM strike."),
      h("div", { class: "table-scroll" }, table)));
}

// ------------------------------------------------------------------ tab 4: suggested index trades
async function viewSwing(app) {
  const [d, hist, events] = await Promise.all([doc("swing_signals"), swingHistory(), swingEvents()]);
  if (!d) return render(app, pageHead("Suggested index trades", null), h("p", { class: "empty" }, "No snapshot yet."));
  const lots = d.lot_sizes || {};
  const watch = (sig, t) => watchDialog({ kind: "index", symbol: sig.symbol, side: sig.direction === "LONG" ? "Long" : "Short",
    entry: +t.entry.toFixed(2), stop: +t.stop.toFixed(2), target: +t.target.toFixed(2), lot_size: lots[sig.symbol],
    expiry: sig.levels.fut_expiry || sig.expiry, method: `Swing: ${t.method}`, source: "swing signal", signal_time: sig.ts });
  const took = (sig, t) => tradeDialog({ kind: "index", symbol: sig.symbol, side: sig.direction === "LONG" ? "Long" : "Short",
    entry: +t.entry.toFixed(2), stop: +t.stop.toFixed(2), target: +t.target.toFixed(2), lots: 1, lot_size: lots[sig.symbol],
    expiry: sig.levels.fut_expiry || sig.expiry, method: `Swing: ${t.method}`, source: "swing signal",
    notes: `${sig.strength} ${sig.direction} ${sig.score >= 0 ? "+" : ""}${sig.score}; ${sig.levels.state || ""}` }, () => { location.hash = "#/trades"; });
  const cards = (d.signals || []).map((sig) => {
    const lv = sig.levels || {};
    const trades = sig.trades || [];
    return h("div", { class: "panel", style: "margin-bottom:14px" },
      h("div", { class: "section-head", style: "margin:0 0 8px" },
        h("h2", null, sig.symbol, " ", chartLink(sig.symbol, "fut", "60"), " ", sideTag(sig.direction), sig.strength ? h("span", { class: "muted", style: "font-weight:400;font-size:14px" }, ` ${sig.strength}`) : null),
        h("p", null, isNum(sig.score) ? `Score ${sig.score >= 0 ? "+" : ""}${sig.score} of ±5 (needs ±${sig.threshold}); monthly expiry ${sig.expiry} (${sig.dte}d)` : "")),
      h("div", { class: "stats" },
        stat("Spot", fmt(sig.spot)), stat("Support / resistance", `${fmt0(lv.support)} / ${fmt0(lv.resistance)}`),
        stat("PCR", isNum(lv.pcr) ? lv.pcr.toFixed(2) : "–", `Max pain ${fmt0(lv.max_pain)}`),
        stat("Futures", lv.state || "No data", lv.fut_ltp ? `${fmt(lv.fut_ltp)} (${pct(lv.fut_pct)})` : null, "txt"),
        stat("ATM IV", isNum(lv.atm_iv) ? `${lv.atm_iv.toFixed(1)}%` : "–")),
      lv.interpretation ? h("p", { class: "intro" }, lv.interpretation) : null,
      (sig.warnings || []).map((w) => h("div", { class: "banner" }, w)),
      trades.length ? h("div", { class: "table-scroll" }, h("table", null,
        h("thead", null, h("tr", null, ["Futures trade", "Entry", "Stop", "Target", "R/R", "Lot", "Check", ""].map((c, i) => h("th", { class: i === 0 || i === 6 ? "l" : null }, c)))),
        h("tbody", null, trades.map((t) => h("tr", { style: "cursor:default" },
          h("td", { class: "l name" }, t.method, h("small", null, t.note)),
          h("td", null, fmt(t.entry)), h("td", null, fmt(t.stop)), h("td", null, fmt(t.target)),
          h("td", null, isNum(t.rr) ? t.rr.toFixed(2) : "–"), h("td", null, lots[sig.symbol] || "–"),
          h("td", { class: `l ${t.ok ? "pos" : "neg"}` }, t.ok ? "Passes" : "Fails"),
          h("td", null, h("div", { class: "btn-row nowrap" }, h("button", { class: "btn small", type: "button", onclick: () => took(sig, t) }, "I took this trade"),
            h("button", { class: "btn small", type: "button", onclick: () => watch(sig, t) }, "Watchlist")))))))) : null,
      h("details", null, h("summary", { class: "note", style: "cursor:pointer;margin-top:10px" }, "What makes up the score"), factorTable(sig.factors)));
  });
  const histTable = hist.length ? h("table", null,
    h("thead", null, h("tr", null, ["Day", "Index", "Signal", "Score", "Spot at 3:15"].map((c, i) => h("th", { class: i < 3 ? "l" : null }, c)))),
    h("tbody", null, hist.map((r) => h("tr", { style: "cursor:default" }, h("td", { class: "l" }, dayLabel(r.day)), h("td", { class: "l" }, r.symbol),
      h("td", { class: "l" }, sideTag(r.direction), r.strength ? ` ${r.strength}` : ""), h("td", null, isNum(r.score) ? r.score : "–"), h("td", null, fmt(r.spot)))))) : null;
  const vol = (e) => ((e.signal && e.signal.trades) || []).find((t) => t.method === "Volatility") || ((e.signal && e.signal.trades) || [])[0];
  const setupTable = events.length ? h("table", null,
    h("thead", null, h("tr", null, ["Formed at", "Index", "Setup", "Score", "Spot", "Futures entry", "Stop", "Target"].map((c, i) => h("th", { class: i < 3 ? "l" : null }, c)))),
    h("tbody", null, events.map((e) => {
      const t = vol(e);
      return h("tr", { style: "cursor:default" }, h("td", { class: "l" }, when(e.ts)), h("td", { class: "l name" }, e.symbol, chartLink(e.symbol, "fut", "60")),
        h("td", { class: "l" }, e.direction === "ENDED" ? h("span", { class: "muted" }, "Setup ended") : [sideTag(e.direction), e.strength ? ` ${e.strength}` : ""]),
        h("td", null, isNum(e.score) ? `${e.score > 0 ? "+" : ""}${e.score}` : "–"), h("td", null, fmt(e.spot)),
        h("td", null, t ? fmt(t.entry) : "–"), h("td", null, t ? fmt(t.stop) : "–"), h("td", null, t ? fmt(t.target) : "–"));
    }))) : null;
  render(app, 
    pageHead("Suggested index trades", `Live, updated every 15 minutes; last update ${when(d.ts)}`),
    h("p", { class: "intro" }, "Score = OI shift (ATM ±2, last 60 min) + PCR level + PCR slope + change-in-OI PCR + futures build-up, each −1 to +1. Long at +2.5 or more, short at −2.5 or less. Each signal shows a futures trade two ways: OI walls (stop and target at the put and call walls, needs R/R 1.5) and Volatility (5-day expected move from ATM IV: stop 0.6×, target 1.5× the stop, skipped if a big OI wall blocks the target). A setup shows here, and in the log below, at the first 15-minute update after its score crosses ±2.5. The day's closing signal is also saved at 3:15 pm."),
    cards,
    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Setups as they formed"), h("p", null, "Last 8 days; levels use the volatility method at the time")),
      setupTable ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, setupTable)) : h("p", { class: "empty" }, "No swing setup has formed yet.")),
    histTable ? h("section", null, h("div", { class: "section-head" }, h("h2", null, "3:15 pm signals, recent days")), h("div", { class: "panel" }, h("div", { class: "table-scroll" }, histTable))) : null);
}

// ------------------------------------------------------------------ tab 5: my trades
// ------------------------------------------------------------------ watchlist tab
async function viewWatch(app) {
  const rows = await loadWatch();
  const today = istDate();
  const rerender = () => route();
  const daysLeft = (w) => { let n = 0, d = today; while (d < String(w.expires_on)) { d = marketDaysAfter(d, 1); n += 1; } return n; };
  const toTrade = (w) => tradeDialog({ kind: w.kind, symbol: w.symbol, side: w.side, entry: w.entry ?? undefined, stop: w.stop ?? undefined,
    target: w.target ?? undefined, lots: 1, lot_size: w.lot_size ?? undefined, expiry: w.expiry ?? undefined,
    method: w.method ?? undefined, source: w.source === "swing signal" ? "swing signal" : "watchlist",
    notes: [w.method, w.notes].filter(Boolean).join("; ") }, async () => { try { await deleteWatch(w.id); } catch (e) { /* keep going */ } location.hash = "#/trades"; });
  const table = (list) => h("table", null,
    h("thead", null, h("tr", null, ["Added", "Symbol", "Type", "Entry", "Stop", "Target", "Kept until", ""].map((c, i) =>
      h("th", { class: [0, 1, 2, 7].includes(i) ? "l" : null }, c)))),
    h("tbody", null, list.map((w) => {
      const left = daysLeft(w);
      return h("tr", { style: "cursor:default" },
        h("td", { class: "l" }, when(w.added_at)),
        h("td", { class: "l name" }, w.symbol, chartLink(w.symbol, w.kind === "index" ? "fut" : "stock", "60"), h("small", null, w.method || w.source || "")),
        h("td", { class: "l" }, w.kind === "index" ? `Index futures${w.lot_size ? `, lot ${w.lot_size}` : ""}` : `Stock${w.lot_size ? `, lot ${w.lot_size}` : ""}`),
        h("td", null, fmt(w.entry)), h("td", null, fmt(w.stop)), h("td", null, fmt(w.target)),
        h("td", { class: left <= 0 ? "neg" : null, title: "Removed automatically after this day" },
          `${new Date(`${w.expires_on}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}${left <= 0 ? " (last day)" : ` (${left} more day${left > 1 ? "s" : ""})`}`),
        h("td", { class: "l" }, h("div", { class: "btn-row nowrap" },
          h("button", { class: "btn primary small", type: "button", onclick: () => toTrade(w) }, "Add to My trades"),
          h("button", { class: "btn small", type: "button", onclick: async () => { await deleteWatch(w.id); rerender(); } }, "Remove"))));
    })));
  const section = (side) => {
    const list = rows.filter((w) => w.side === side);
    return h("section", null,
      h("div", { class: "section-head" }, h("h2", null, h("span", { class: `dot-side ${side.toLowerCase()}` }), `${side} (${list.length})`)),
      list.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, table(list)))
        : h("p", { class: "empty" }, `No ${side.toLowerCase()} ideas on the watchlist.`));
  };
  render(app,
    pageHead("Watchlist", `Ideas you are watching. Each stays for ${WATCH_DAYS} market days after the day you added it, then it is removed.`),
    h("p", { class: "note" }, "Add from the stock screener or the suggested index trades with “Move to watchlist”. “Add to My trades” opens the trade form with the saved levels; after you save, the idea leaves the watchlist. Prices shown are the levels when you added it; check the chart icon for the current price."),
    section("Long"), section("Short"));
}

/* Shares / units traded: lots × lot size; older stock trades may have a quantity instead. */
function tradeQty(t, lotFallback) {
  const lot = t.lot_size || lotFallback;
  if (lot) return (t.lots || 1) * lot;
  return t.qty || null;
}
/* Current price and unrealised P&L of an open trade, from the latest scan (stocks:
   hourly screener / Run scan; index futures: every 15 minutes). */
function livePnl(t, tp) {
  const p = tp?.prices?.[String(t.id)];
  if (!p || !isNum(p.px) || !isNum(t.entry)) return null;
  const dir = t.side === "Long" ? 1 : -1;
  const pctv = (p.px / t.entry - 1) * 100 * dir - (t.kind === "index" ? 0 : 0.1);   // same as when it closes
  const lot = t.lot_size || p.lot;
  const q = tradeQty(t, p.lot);
  const inrv = q ? (p.px - t.entry) * dir * q - (t.charges || 0) : null;
  const basis = lot ? `${t.lots || 1} lot${(t.lots || 1) > 1 ? "s" : ""} × ${lot}` : t.qty ? `${t.qty} qty` : "";
  return { px: p.px, t: p.t, pct: pctv, inr: inrv, basis };
}

async function viewTrades(app) {
  const all = await loadTrades();
  const [tpStock, tpIndex] = LIVE ? await Promise.all([doc("trade_prices_stock").catch(() => null), doc("trade_prices_index").catch(() => null)]) : [null, null];
  const view = state.tradeView;
  const trades = all.filter((t) => view === "all" || t.kind === view);
  const open = trades.filter((t) => t.status === "open"), closed = trades.filter((t) => t.status === "closed");
  const rerender = () => route();
  // closed trades older than 3 months are kept only as monthly totals (table trade_months)
  let archive = [];
  if (LIVE) {
    const { data, error } = await sb.from("trade_months").select("*").eq("book", "fno");
    if (!error && data) archive = data.filter((r) => view === "all" || r.kind === view);
  }
  const blank = () => ({ n: 0, pctN: 0, w: 0, sum: 0, gain: 0, loss: 0, inrN: 0, inr: 0 });
  const addTrade = (g, t) => {
    g.n += 1;
    const v = t.net_pct_after_cost;
    if (isNum(v)) { g.pctN += 1; g.sum += v; if (v > 0) { g.w += 1; g.gain += v; } else g.loss += v; }
    if (isNum(t.pnl_inr)) { g.inrN += 1; g.inr += t.pnl_inr; }
  };
  const addMonth = (g, r) => {
    g.n += r.trades; g.pctN += r.pct_count; g.w += r.wins; g.sum += r.sum_pct; g.gain += r.gain_pct;
    g.loss += r.loss_pct; g.inrN += r.inr_count; g.inr += r.pnl_inr;
  };
  // financial year (April–March), by the month a trade was closed; "2026-11" -> 2026 (FY 2026-27)
  const closeMonth = (t) => String(t.exit_time || t.entry_time || "").slice(0, 7);
  const fyOf = (m) => { const y = +m.slice(0, 4), mo = +m.slice(5, 7); return mo >= 4 ? y : y - 1; };
  const fyLabel = (y) => `FY ${y}-${String((y + 1) % 100).padStart(2, "0")}`;
  const now = new Date();
  const curFy = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  // totals at the top: current financial year only (starts fresh every 1 April)
  const tot = blank();
  closed.forEach((t) => { const m = closeMonth(t); if (m && fyOf(m) === curFy) addTrade(tot, t); });
  archive.forEach((r) => { if (fyOf(r.month) === curFy) addMonth(tot, r); });
  const pf = tot.loss < 0 ? tot.gain / Math.abs(tot.loss) : null;
  const archivedN = archive.filter((r) => fyOf(r.month) === curFy).reduce((a2, r) => a2 + r.trades, 0);
  const openNote = `${open.length} open${archivedN ? ` · ${archivedN} older than 3 months kept as monthly totals` : ""}`;
  const stats = h("div", { class: "stats" },
    stat("Closed trades", tot.n, openNote),
    stat("Win rate", tot.pctN ? `${Math.round((tot.w / tot.pctN) * 100)}%` : "–", `${tot.w} won, ${tot.pctN - tot.w} lost`),
    stat("Average per trade", tot.pctN ? pct(tot.sum / tot.pctN) : "–", "Net % after costs", sign(tot.sum)),
    stat("Profit factor", isNum(pf) ? pf.toFixed(2) : "–", "Total % won ÷ total % lost"),
    stat("Net P&L in %", tot.pctN ? pct(tot.sum) : "–", "Sum of net % of closed trades", sign(tot.sum)),
    stat("Net P&L in ₹", tot.inrN ? inr(tot.inr) : "–", "Closed trades, lots × lot size", sign(tot.inr)));

  // month-wise: by the month a trade was closed (entry month if no exit time was recorded)
  const months = {};
  for (const t of closed) {
    const m = String(t.exit_time || t.entry_time || "").slice(0, 7);
    if (m) addTrade(months[m] ||= blank(), t);
  }
  for (const r of archive) addMonth(months[r.month] ||= blank(), r);
  const monthRows = Object.keys(months).sort().reverse().map((m) => {
    const g = months[m];
    const label = new Date(`${m}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
    return h("tr", { style: "cursor:default" }, h("td", { class: "l name" }, label), h("td", null, g.n),
      h("td", null, `${g.w} / ${g.pctN - g.w}`), h("td", null, g.pctN ? `${Math.round((g.w / g.pctN) * 100)}%` : "–"),
      h("td", { class: sign(g.sum) }, pct(g.sum)), h("td", { class: sign(g.sum) }, g.pctN ? pct(g.sum / g.pctN) : "–"),
      h("td", null, g.loss < 0 ? (g.gain / Math.abs(g.loss)).toFixed(2) : g.pctN ? "∞" : "–"), h("td", { class: sign(g.inr) }, g.inrN ? inr(g.inr) : "–"));
  });
  const monthTable = h("table", null,
    h("thead", null, h("tr", null, ["Month", "Trades", "Won / lost", "Win rate", "Net %", "Avg per trade", "Profit factor", "Net ₹"].map((c, i) => h("th", { class: i === 0 ? "l" : null }, c)))),
    h("tbody", null, monthRows));

  // year by year: completed financial years (Apr–Mar); the running year stays in the totals at the top
  const years = {};
  for (const m of Object.keys(months)) {
    const y = fyOf(m);
    if (y >= curFy) continue;
    const g = years[y] ||= blank(), s = months[m];
    for (const k of Object.keys(g)) g[k] += s[k];
  }
  const yearRows = Object.keys(years).map(Number).sort((a2, b2) => b2 - a2).map((y) => {
    const g = years[y];
    return h("tr", { style: "cursor:default" }, h("td", { class: "l name" }, fyLabel(y), h("small", null, `Apr ${y} – Mar ${y + 1}`)), h("td", null, g.n),
      h("td", null, `${g.w} / ${g.pctN - g.w}`), h("td", null, g.pctN ? `${Math.round((g.w / g.pctN) * 100)}%` : "–"),
      h("td", { class: sign(g.sum) }, pct(g.sum)), h("td", { class: sign(g.sum) }, g.pctN ? pct(g.sum / g.pctN) : "–"),
      h("td", null, g.loss < 0 ? (g.gain / Math.abs(g.loss)).toFixed(2) : g.pctN ? "∞" : "–"), h("td", { class: sign(g.inr) }, g.inrN ? inr(g.inr) : "–"));
  });
  const yearTable = h("table", null,
    h("thead", null, h("tr", null, ["Financial year", "Trades", "Won / lost", "Win rate", "Net %", "Avg per trade", "Profit factor", "Net ₹"].map((c, i) => h("th", { class: i === 0 ? "l" : null }, c)))),
    h("tbody", null, yearRows));

  const row = (t, isOpen) => h("tr", { style: "cursor:default" },
    h("td", { class: "l" }, when(t.entry_time)),
    h("td", { class: "l name" }, t.symbol, chartLink(t.symbol, t.kind === "index" ? "fut" : "stock", "60"), h("small", null, `${t.kind === "index" ? "Index futures" : (t.source || "stock")}${t.lot_size ? ` · ${t.lots || 1} × ${t.lot_size}` : ""}`)),
    h("td", { class: "l" }, sideTag(t.side)),
    h("td", null, fmt(t.entry)), h("td", null, fmt(t.stop)), h("td", null, fmt(t.target)),
    ...(isOpen ? (() => {
      const L = livePnl(t, t.kind === "index" ? tpIndex : tpStock);
      return [
        h("td", { class: "live-cell", title: L ? `Price at ${when(L.t)}` : "Updated by the next scan" }, L ? [fmt(L.px), h("small", null, when(L.t))] : h("span", { class: "muted" }, "–")),
        h("td", { class: L ? sign(L.pct) : null }, L ? pct(L.pct) : "–"),
        h("td", { class: `live-cell ${L && isNum(L.inr) ? sign(L.inr) : ""}`, title: L?.basis || (t.kind === "stock" ? "Add a quantity to see rupees" : "Add the lot size to see rupees") },
          L && isNum(L.inr) ? [inr(L.inr), h("small", null, L.basis)] : "–")];
    })() : []),
    isOpen ? null : h("td", null, fmt(t.exit)),
    isOpen ? null : h("td", { class: "l" }, t.exit_reason || "–"),
    isOpen ? null : h("td", { class: sign(t.net_pct_after_cost) }, pct(t.net_pct_after_cost)),
    isOpen ? null : h("td", { class: sign(t.pnl_inr) }, inr(t.pnl_inr)),
    h("td", { class: "l" }, h("div", { class: "btn-row" },
      isOpen ? h("button", { class: "btn small", type: "button", onclick: () => closeDialog(t, rerender) }, "Close") : null,
      isOpen || canFix(t) ? h("button", { class: "btn small", type: "button", onclick: () => tradeDialog(t, rerender) }, "Edit") : h("span", { class: "muted", title: "Closed trades are locked" }, "Locked"),
      !isOpen && canFix(t) ? h("button", { class: "btn small", type: "button", onclick: () => reopenTrade(t, rerender) }, "Reopen") : null,
      !isOpen && canFix(t) ? h("small", { class: "muted", title: "Closed trades lock after the 7:40 pm check" }, fixLabel(t)) : null,
      isOpen ? h("button", { class: "btn small", type: "button", onclick: async () => { if (confirm(`Delete the ${t.symbol} trade? This cannot be undone.`)) { await deleteTrade(t.id); rerender(); } } }, "Delete") : null)));
  const table = (rows, isOpen) => h("table", null,
    h("thead", null, h("tr", null, ["Entry time", "Symbol", "Side", "Entry", "Stop", "Target", ...(isOpen ? ["Now", "P&L %", "P&L ₹"] : ["Exit", "Reason", "Net %", "P&L ₹"]), ""].map((c, i) =>
      h("th", { class: [0, 1, 2].includes(i) || c === "Reason" ? "l" : null }, c)))),
    h("tbody", null, rows.map((t) => row(t, isOpen))));
  const viewSeg = h("div", { class: "seg", role: "group", "aria-label": "Show" }, [["all", "All"], ["stock", "Stocks"], ["index", "Index futures"]].map(([k, l]) =>
    h("button", { type: "button", "aria-pressed": String(view === k), onclick: () => { state.tradeView = k; rerender(); } }, l)));
  render(app, 
    pageHead("My trades", LIVE ? "Saved to your private database" : "Preview: changes are not saved"),
    h("div", { class: "filters" }, viewSeg,
      h("button", { class: "btn primary", type: "button", onclick: () => tradeDialog({}, rerender) }, "Add a trade"),
      h("button", { class: "btn", type: "button", onclick: () => exportCsv(all) }, "Export CSV")),
    h("p", { class: "note" }, "Open trades close automatically: stocks from the Price Action and Price+OI tabs only at the stop (close the rest by hand; the target is shown), older stock trades at the stop, target or after 5 sessions (hourly candles); index futures at the stop or target on the futures price (every 15 minutes) or after 5 sessions. \"Now\" is the price at the latest check: stocks every hour and when you press Run scan, index futures every 15 minutes. P&L ₹ = (sell − buy) × lots × lot size − charges (long: sell = exit, buy = entry; short: sell = entry, buy = exit). Stock P&L % is after 0.1% costs."),
    h("div", { class: "section-head" }, h("h2", null, `This financial year · ${fyLabel(curFy)}`),
      h("p", null, `Closed trades from 1 Apr ${curFy} to 31 Mar ${curFy + 1}. On 1 April the totals start fresh and this year moves to “Year by year”.`)),
    stats,
    yearRows.length ? h("section", null, h("div", { class: "section-head" }, h("h2", null, "Year by year"), h("p", null, "Completed financial years (April–March), by the date trades were closed.")),
      h("div", { class: "panel" }, h("div", { class: "table-scroll" }, yearTable))) : null,
    monthRows.length ? h("section", null, h("div", { class: "section-head" }, h("h2", null, "Month by month"), h("p", null, "Closed trades, by the month they were closed. Trade details are kept for 3 months; monthly totals are kept for good.")),
      h("div", { class: "panel" }, h("div", { class: "table-scroll" }, monthTable))) : null,
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `Open (${open.length})`)),
      open.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, table(open, true))) : h("p", { class: "empty" }, "No open trades.")),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `Closed (${closed.length})`)),
      closed.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, table(closed, false))) : h("p", { class: "empty" }, "No closed trades yet.")));
}
function exportCsv(rows) {
  const cols = ["entry_time", "kind", "symbol", "side", "entry", "stop", "target", "exit_time", "exit", "exit_reason", "status",
    "net_pct_after_cost", "pnl_inr", "lots", "lot_size", "qty", "expiry", "method", "source", "notes"];
  const esc = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "trade_journal.csv" });
  document.body.append(a); a.click(); a.remove();
}

// ------------------------------------------------------------------ sign-in
function viewSignIn(app, message) {
  const email = h("input", { type: "email", value: CFG.email || "", required: true, autocomplete: "username" });
  const pass = h("input", { type: "password", required: true, autocomplete: "current-password" });
  const msg = h("p", { class: "err", role: "status" }, message || "");
  const show = h("label", { class: "toggle", style: "margin-top:8px" },
    h("input", { type: "checkbox", onchange: (e) => { pass.type = e.target.checked ? "text" : "password"; } }), "Show password");
  const btn = h("button", { class: "btn primary", type: "submit" }, "Sign in");
  const form = h("form", { class: "panel signin" },
    h("h1", null, "Sign in"),
    h("p", { class: "intro" }, "This desk is private. You stay signed in on this device until you sign out."),
    h("label", { class: "note" }, "Email", email), h("div", { style: "height:10px" }),
    h("label", { class: "note" }, "Password", pass), show, h("div", { style: "height:14px" }),
    btn, msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    msg.textContent = "";
    const { error } = await sb.auth.signInWithPassword({ email: email.value.trim(), password: pass.value });
    btn.disabled = false;
    if (error) msg.textContent = /invalid/i.test(error.message) ? "Email or password is wrong." : `Could not sign in: ${error.message}`;
    else route();
  });
  render(app, form);
}

// ------------------------------------------------------------------ track record (signal log)
async function loadSignals() {
  if (LIVE) {
    const { data, error } = await sb.from("signal_log").select("*").order("signal_time", { ascending: false }).limit(5000);
    if (error) throw new Error(/signal_log|does not exist|schema cache/i.test(error.message)
      ? "the signal log table is not set up yet (run supabase/010_signal_log.sql in Supabase)" : error.message);
    return data;
  }
  const r = await fetch("sample/signal_log.json", { cache: "no-cache" });
  return r.ok ? r.json() : [];
}

async function viewRecord(app) {
  const all = await loadSignals();
  const rules = state.recRules || "strategy";
  const alt = rules === "mine";
  const res = (r) => (alt ? r.alt_result : r.result);
  const net = (r) => +(alt ? r.alt_net_pct : r.net_pct);
  const rr = (r) => +(alt ? r.alt_r_mult : r.r_mult);
  const finished = (r) => res(r) && !["no data", "no valid stop"].includes(res(r));
  const info = (r) => r.info || {};
  const want = (r) => (r.side === "Long" ? "Long build-up" : "Short build-up");
  // rule sets: "pa" Price Action, "po" Price+OI (6 Nov 2026), old = 50 EMA cross
  const rulesOf = (r) => (r.info && r.info.rules) || "old";
  const RULE_NAME = { pa: "Price Action", po: "Price+OI", old: "Old rules" };
  const oldRows = all.filter((r) => rulesOf(r) === "old");
  const ideas = oldRows.filter((r) => r.kind === "idea"), rejected = oldRows.filter((r) => r.kind === "rejected");
  const pa = all.filter((r) => rulesOf(r) === "pa" && r.kind === "idea");
  const po = all.filter((r) => rulesOf(r) === "po" && r.kind === "idea"), poRej = all.filter((r) => rulesOf(r) === "po" && r.kind === "rejected");
  const nb = pa.concat(po);

  const agg = (rows) => {
    const f = rows.filter(finished);
    const n = f.length, wins = f.filter((r) => net(r) > 0);
    const gain = wins.reduce((a, r) => a + net(r), 0), loss = f.filter((r) => net(r) <= 0).reduce((a, r) => a + net(r), 0);
    const mf = f.filter((r) => isNum(+r.mfe_r) && r.mfe_r != null);
    return { signals: rows.length, n, win: n ? (wins.length / n) * 100 : null, avg: n ? f.reduce((a, r) => a + net(r), 0) / n : null,
      r: n ? f.reduce((a, r) => a + rr(r), 0) / n : null, pf: loss < 0 ? gain / -loss : n && gain > 0 ? Infinity : null,
      oneR: mf.length ? (mf.filter((r) => +r.mfe_r >= 1).length / mf.length) * 100 : null };
  };
  const MIN_N = 20;
  const rFmt = (v) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}R` : "–");
  const groupRow = (label, note, rows) => {
    const g = agg(rows);
    return h("tr", { class: g.n < MIN_N ? "few" : null, style: "cursor:default" },
      h("td", { class: "l" }, label, note ? h("small", null, note) : null),
      h("td", null, g.signals), h("td", null, g.n),
      h("td", null, isNum(g.win) ? `${Math.round(g.win)}%` : "–"),
      h("td", { class: sign(g.avg) }, pct(g.avg)), h("td", { class: sign(g.r) }, rFmt(g.r)),
      h("td", null, g.pf === Infinity ? "∞" : isNum(g.pf) ? g.pf.toFixed(2) : "–"),
      h("td", null, isNum(g.oneR) ? `${Math.round(g.oneR)}%` : "–"));
  };
  const groupTable = (title, sub, rows) => h("section", null,
    h("div", { class: "section-head" }, h("h2", null, title), sub ? h("p", null, sub) : null),
    h("div", { class: "panel" }, h("div", { class: "table-scroll" }, h("table", { class: "tr-groups" },
      h("thead", null, h("tr", null, ["Group", "Signals", "Finished", "Win rate", "Avg net %", "Avg R", "Profit factor", "Reached 1R"].map((c, i) =>
        h("th", { class: i ? null : "l" }, c)))),
      h("tbody", null, rows.map(([label, note, list]) => groupRow(label, note, list)))))));

  const hourIs = (r, f) => { const hr = info(r).hourly; return f(hr, r); };
  const dayOi = (r) => Math.abs(+(info(r).futures?.pchg_oi) || 0);
  const warnN = (r) => (info(r).warnings || []).length;
  const against = (r) => (r.side === "Long" ? "down" : "up");
  const regimeBad = (r) => (r.side === "Long" ? "Red" : "Green"), regimeGood = (r) => (r.side === "Long" ? "Green" : "Red");
  const risk = (r) => info(r).risk_pct;

  const ranking = [
    ["Live Top 5", "Rank 1–5 in the scan that first listed it", ideas.filter((r) => r.top_rank)],
    ["Not in live Top 5", null, ideas.filter((r) => !r.top_rank)],
    ["Proposed score Top 5", "Signal-hour OI 35, day OI 25, candle shape 25 + size 15, + sector", ideas.filter((r) => r.rank_v2 && r.rank_v2 <= 5)],
    ["All ideas", null, ideas],
    ["Rejected by the day's futures", "Day build-up against the trade; not shown as ideas", rejected],
  ];
  const oi = [
    ["Signal hour agrees", "Same-direction build-up in the signal hour", ideas.filter((r) => hourIs(r, (hr) => hr && hr.buildup === want(r)))],
    ["Signal hour against", "Covering, unwinding or opposite build-up", ideas.filter((r) => hourIs(r, (hr) => hr && hr.buildup !== want(r) && hr.buildup !== "OI flat"))],
    ["Signal hour OI flat", null, ideas.filter((r) => hourIs(r, (hr) => hr && hr.buildup === "OI flat"))],
    ["Signal hour unknown", "No snapshot before the signal", ideas.filter((r) => !info(r).hourly)],
    ["Day OI change under 3%", null, ideas.filter((r) => dayOi(r) < 3)],
    ["Day OI change 3–7%", null, ideas.filter((r) => dayOi(r) >= 3 && dayOi(r) < 7)],
    ["Day OI change 7–15%", null, ideas.filter((r) => dayOi(r) >= 7 && dayOi(r) < 15)],
    ["Day OI change 15% or more", null, ideas.filter((r) => dayOi(r) >= 15)],
    ["Rejected by day, but signal hour agreed", "Would the signal-hour reading rescue these?", rejected.filter((r) => hourIs(r, (hr) => hr && hr.buildup === want(r)))],
  ];
  const ctx = [
    ["Sector boost", "Sector leading in the trade's direction", ideas.filter((r) => info(r).scoring?.boost > 0)],
    ["No sector boost", null, ideas.filter((r) => !(info(r).scoring?.boost > 0))],
    ["With the daily trend", "Long above / Short below the 20-day average", ideas.filter((r) => info(r).daily_trend && info(r).daily_trend !== against(r))],
    ["Against the daily trend", null, ideas.filter((r) => info(r).daily_trend === against(r))],
    ["Regime with the trade", "Long on Green, Short on Red", ideas.filter((r) => info(r).regime === regimeGood(r))],
    ["Regime Amber", null, ideas.filter((r) => info(r).regime === "Amber")],
    ["Regime against the trade", "Long on Red, Short on Green", ideas.filter((r) => info(r).regime === regimeBad(r))],
    ["Breakout volume at or above usual", "Vs the same hourly candle, last 10 sessions", ideas.filter((r) => isNum(info(r).vol_ratio) && info(r).vol_ratio >= 1)],
    ["Breakout volume below usual", null, ideas.filter((r) => isNum(info(r).vol_ratio) && info(r).vol_ratio < 1)],
    ["Small candle (under 0.6x usual range)", "Vs the same hourly candle, last 10 sessions", ideas.filter((r) => isNum(info(r).size_ratio) && info(r).size_ratio < 0.6)],
    ["Normal candle size (0.6–2.5x)", null, ideas.filter((r) => isNum(info(r).size_ratio) && info(r).size_ratio >= 0.6 && info(r).size_ratio <= 2.5)],
    ["Very big candle (over 2.5x)", null, ideas.filter((r) => isNum(info(r).size_ratio) && info(r).size_ratio > 2.5)],
    ["Choppy (3+ EMA crosses before)", null, ideas.filter((r) => (info(r).ema_crosses || 0) >= 3)],
    ["Not choppy", null, ideas.filter((r) => (info(r).ema_crosses || 0) < 3)],
    ["Stop under 0.4%", null, ideas.filter((r) => isNum(risk(r)) && risk(r) < 0.4)],
    ["Stop 0.4–2.5%", null, ideas.filter((r) => isNum(risk(r)) && risk(r) >= 0.4 && risk(r) <= 2.5)],
    ["Stop over 2.5%", null, ideas.filter((r) => isNum(risk(r)) && risk(r) > 2.5)],
    ["Results within 5 sessions", null, ideas.filter((r) => isNum(info(r).results_sessions) && info(r).results_sessions <= 5)],
    ["No warnings", null, ideas.filter((r) => warnN(r) === 0)],
    ["1 warning", null, ideas.filter((r) => warnN(r) === 1)],
    ["2 or more warnings", null, ideas.filter((r) => warnN(r) >= 2)],
    ["Longs", null, ideas.filter((r) => r.side === "Long")],
    ["Shorts", null, ideas.filter((r) => r.side === "Short")],
  ];

  const ruleSets = [
    ["Price Action: all ideas", "Chart only", pa],
    ["Price Action: Top 5", null, pa.filter((r) => r.top_rank)],
    ["Price+OI: all ideas", "Chart + futures OI", po],
    ["Price+OI: Top 5", null, po.filter((r) => r.top_rank)],
    ["Price+OI: OI in the breakout candle", null, po.filter((r) => info(r).confirm === "breakout candle")],
    ["Price+OI: OI in the next candle", "One-candle wait; entry a candle later", po.filter((r) => info(r).confirm === "next candle")],
    ["Price+OI: rejected by OI", "Good chart, OI never confirmed or day build-up against", poRej],
    ["Price Action: base breakouts", "Base 1 or 2, flattening EMA", pa.filter((r) => info(r).kind !== "rejection")],
    ["Price Action: rejection at the 50 EMA", "Wick off a rising (Long) or falling (Short) EMA", pa.filter((r) => info(r).kind === "rejection")],
    ["Price+OI: rejection at the 50 EMA", null, po.filter((r) => info(r).kind === "rejection")],
    ["Old rules: all ideas", "50 EMA cross + day futures build-up", ideas],
    ["Old rules: Top 5", null, ideas.filter((r) => r.top_rank)],
  ];
  const nbDetail = [
    ["Rising 50 EMA", "Price Action ideas", pa.filter((r) => info(r).state === "rising")],
    ["Flat 50 EMA", null, pa.filter((r) => info(r).state === "flat")],
    ["Falling 50 EMA", null, pa.filter((r) => info(r).state === "falling")],
    ["Base 1", null, pa.filter((r) => info(r).base_no === 1)],
    ["Base 2", null, pa.filter((r) => info(r).base_no === 2)],
    ["Stop at the breakout candle (2%+ candle)", null, pa.filter((r) => info(r).stop_from === "breakout candle")],
    ["Stop at the base", null, pa.filter((r) => info(r).stop_from === "base")],
    ["Also qualified on Price+OI", null, pa.filter((r) => info(r).also)],
    ["Price Action only", null, pa.filter((r) => !info(r).also)],
    ["Sector leading", null, pa.filter((r) => info(r).sector)],
    ["No sector boost", null, pa.filter((r) => !info(r).sector)],
    ["Longs", null, pa.filter((r) => r.side === "Long")],
    ["Shorts", null, pa.filter((r) => r.side === "Short")],
  ];
  const top = agg(ideas.filter((r) => r.top_rank)), rest = agg(ideas.filter((r) => !r.top_rank)), allI = agg(ideas);
  const aPA = agg(pa), aPO = agg(po);
  const openN = all.filter((r) => !finished(r) && !r.done).length;
  const first = all.length ? all[all.length - 1].signal_time : null;
  const stats = h("div", { class: "stats" },
    stat("Signals logged", all.length, `${pa.length} Price Action, ${po.length} Price+OI, ${ideas.length} old-rule ideas${first ? ` · since ${dayLabel(first)}` : ""}`),
    stat("Still running", openN, "Not finished yet"),
    stat("Price Action", rFmt(aPA.r), `${aPA.n} finished · win ${isNum(aPA.win) ? Math.round(aPA.win) + "%" : "–"}`, sign(aPA.r)),
    stat("Price+OI", rFmt(aPO.r), `${aPO.n} finished · win ${isNum(aPO.win) ? Math.round(aPO.win) + "%" : "–"}`, sign(aPO.r)),
    stat("Old rules", rFmt(allI.r), `${allI.n} finished · win ${isNum(allI.win) ? Math.round(allI.win) + "%" : "–"}`, sign(allI.r)));

  const resTag = (r) => {
    const v = res(r);
    if (!v) return h("span", { class: "muted" }, "running");
    return h("span", { class: `res-tag ${v}` }, { target: "Target", stop: "Stop", ema_exit: "50 EMA exit", time: "5 sessions" }[v] || v);
  };
  const recent = h("table", null,
    h("thead", null, h("tr", null, ["Signal", "Stock", "Side", "Rules", "List", "Score", "Proposed", "Signal hour", "Warnings", "Result", "Net %", "R", "Best R"].map((c, i) =>
      h("th", { class: i < 5 || i === 9 ? "l" : null }, c)))),
    h("tbody", null, all.slice(0, 60).map((r) => {
      const hr = info(r).hourly, w = info(r).warnings || [];
      return h("tr", { style: "cursor:default" },
        h("td", { class: "l" }, when(r.signal_time)),
        h("td", { class: "l name" }, r.symbol, chartLink(r.symbol)),
        h("td", { class: "l" }, sideTag(r.side)),
        h("td", { class: "l", title: info(r).setup || "" }, RULE_NAME[rulesOf(r)]),
        h("td", { class: "l" }, r.kind === "rejected" ? h("span", { class: "muted", title: info(r).reason || "" }, rulesOf(r) === "old" ? "Rejected (day OI)" : "Rejected (OI)") : r.top_rank ? h("span", { class: "flag fno" }, `Top ${r.top_rank}`) : "Idea"),
        h("td", null, isNum(+r.score) && r.score != null ? Math.round(r.score) : "–"),
        h("td", null, r.rank_v2 ? `#${r.rank_v2}` : "–"),
        h("td", { title: hr ? hourText(hr) : "" }, hr ? `${hr.buildup.replace(" build-up", "")} ${pct(hr.oi_pct, 1)}` : "–"),
        h("td", null, w.length ? h("span", { class: "warn-count", title: w.join("\n") }, w.length) : "–"),
        h("td", { class: "l" }, resTag(r)),
        h("td", { class: finished(r) ? sign(net(r)) : null }, finished(r) ? pct(net(r)) : "–"),
        h("td", { class: finished(r) ? sign(rr(r)) : null }, finished(r) ? rFmt(rr(r)) : "–"),
        h("td", null, r.mfe_r != null ? `${(+r.mfe_r).toFixed(1)}R` : "–"));
    })));

  const rulesSeg = h("div", { class: "seg", role: "group", "aria-label": "Exit rules" },
    [["strategy", "Old rules: strategy exits (with 50 EMA)"], ["mine", "Old rules: stop, target, 5 sessions"]].map(([k, l]) =>
      h("button", { type: "button", "aria-pressed": String(rules === k), onclick: () => { state.recRules = k; route(); } }, l)));

  render(app,
    pageHead("Track record", LIVE ? "Every screener signal, logged automatically: Price Action, Price+OI and the old rules" : "Preview: sample data"),
    h("div", { class: "filters" }, rulesSeg),
    h("p", { class: "intro" }, "Each idea is saved the first time a scan lists it, with its setup, score parts and warnings. Price+OI also saves setups that futures OI did not confirm, and the old rules save 50 EMA signals rejected by the day's build-up. Later scans fill in what happened from the entry candle's open. Price Action and Price+OI: stop, 1:2 target or 5 sessions. Old rules: ",
      alt ? "stop, 1:2 target or 5 sessions." : "stop, 1:2 target, a close back across the 50 EMA, or 5 sessions (their strategy's rules).",
      " R = result ÷ the risk to the stop. Net % is after 0.1% costs. Reached 1R = the trade was at least 1R in profit at some point. Greyed rows have fewer than 20 finished signals: too few to judge."),
    all.length ? stats : h("p", { class: "empty" }, "No signals logged yet. They start with the next scan after the signal log table is set up."),
    all.length ? groupTable("Rule sets", "Price Action and Price+OI (from 6 Nov 2026) vs the old 50 EMA cross rules. New rules: stop, 1:2 target or 5 sessions", ruleSets) : null,
    nb.length ? groupTable("Price Action details", "Which kind of setup works", nbDetail) : null,
    all.length ? groupTable("Old rules: ranking", "50 EMA cross rules, still logged in the background. The exit buttons above apply to these", ranking) : null,
    all.length ? groupTable("Old rules: futures OI", "The day's build-up was the filter; the signal hour was tested", oi) : null,
    all.length ? groupTable("Old rules: context and warnings", "Ideas only", ctx) : null,
    all.length ? h("section", null, h("div", { class: "section-head" }, h("h2", null, "Latest signals"), h("p", null, "Newest first, up to 60")),
      h("div", { class: "panel" }, h("div", { class: "table-scroll" }, recent))) : null);
}

// ------------------------------------------------------------------ readme: current rules and scoring
/* Static text: keep in step with desk/config.py, desk/screener.py, desk/signals.py,
   desk/engine.py and desk/journal.py when a rule changes. */
function viewReadme(app) {
  const sec = (title, sub, ...kids) => h("section", null,
    h("div", { class: "section-head" }, h("h2", null, title), sub ? h("p", null, sub) : null), ...kids);
  const list = (items) => h("ul", { class: "readme-list" }, items.map((t) => h("li", null, t)));
  const tbl = (head, rows) => h("div", { class: "panel" }, h("div", { class: "table-scroll" }, h("table", { class: "static readme-tbl" },
    h("thead", null, h("tr", null, head.map((c, i) => h("th", { class: "l" }, c)))),
    h("tbody", null, rows.map((r) => h("tr", { style: "cursor:default" }, r.map((c, i) => h("td", { class: i === 0 ? "l name" : "l" }, c))))))));
  const tag = (t, cls) => h("span", { class: `flag ${cls || ""}` }, t);

  render(app,
    pageHead("Readme", "How the desk decides: the rules and scores in use today"),
    h("p", { class: "intro" }, "Personal analysis only, not investment advice. Exchange feeds are unofficial NSE/BSE website endpoints and can change without notice."),

    sec("F&O stock screener", "Live rules since 6 Nov 2026: two tabs, Price Action (default) and Price+OI",
      h("h3", { class: "readme-h" }, "1. 50 EMA state"),
      list([
        "Hourly candles, 50 EMA on the close. The slope over the 20 candles before the signal (about 3 sessions) sets the state: rising above +0.5%, flat between −0.5% and +0.5%, falling below −0.5%.",
        "Setups are checked on the last 2 completed hourly candles at every scan.",
      ]),
      h("h3", { class: "readme-h" }, "2. Base and breakout"),
      list([
        "Base: 7 to 30 candles before the breakout whose high–low range is at most 1.5× the stock's average daily range (last 20 sessions), moving sideways: the move from its first close to its last is at most half its range (a rising or falling leg is not a base).",
        "Breakout: a solid candle (body at least 50% of its range, close in the top third) closes above the base high and above the 50 EMA. Short: the mirror, below the base low and the EMA. A gap in the trade's direction counts as part of the candle (body measured from the previous close).",
        "The longest qualifying base is used; if the longest one fails a rule, shorter bases (down to 7 candles) are tried.",
        "Base count: only bases on the trade's side of the 50 EMA count (above it for Longs, below it for Shorts, 80% of closes), stepping one way since price crossed the EMA; each new base starts after the previous breakout. A close on the other side of the EMA resets the count, so a zig-zag never builds one. Only the 1st and 2nd base are taken; later ones are shown as late.",
      ]),
      h("h3", { class: "readme-h" }, "3. Which setups count"),
      tbl(["50 EMA", "Long", "Short"], [
        ["Rising", "Base 1 or 2, with 80% of the base's closes at or above the EMA. Or a rejection at the EMA: price had been above it, the candle's low touches or pierces it and it closes back at or above it, with a lower wick of at least half the candle and the close in the upper half (stop below the wick).", "None. The 1st breakdown below a rising EMA is ignored."],
        ["Flat", "Base 1 or 2, held above the EMA (80% of closes).", "A base more than 1% below the EMA (80% of closes) breaks down."],
        ["Falling", "The 1st breakout above it is ignored (selling not absorbed). Counts only after price has held above the EMA for 7+ candles and formed a base.", "A base below the EMA breaks down, or a rejection: price had been below it, the candle's high touches or pierces the EMA and it closes back at or below it, with an upper wick of at least half the candle and the close in the lower half (stop above the wick)."],
        ["Flattening", "After a fall, the EMA has gone flat over the last 7 candles (changed less than 0.15%) and a base sits on it (80% of closes no more than 0.3% below it): breakout above the base and the EMA.", "After a rise, the same flat EMA with a base on or just under it (80% of closes no more than 0.3% above it): breakdown below the base and the EMA. Example: ICICIBANK 24 Apr 2026, 9:15."],
      ]),
      h("h3", { class: "readme-h" }, "4. Entry, stop, target, exit"),
      list([
        "Entry: the next candle's open (Price+OI with OI in the next candle: one candle later).",
        "Stop: if the breakout candle's range is 2% of price or more, 0.1% beyond its low (high for a Short); otherwise 0.1% beyond the base low (high). Rejections: beyond the rejection candle's wick. A stop more than 5% from entry is skipped.",
        "Target: 1:2, shown only. Your trades close automatically only at the stop; otherwise you close them by hand.",
        "Track record: stop, 1:2 target or 5 sessions, whichever comes first.",
      ]),
      h("h3", { class: "readme-h" }, "5. Price+OI: futures OI"),
      list([
        "Signal-hour OI: futures OI (all expiries) over the breakout candle, from the snapshot taken just after it opened to the one just after it closed. For the 9:15 candle: from yesterday's closing OI.",
        "Usual hourly OI: the stock's average absolute hourly OI change over the stored snapshots (about 10 sessions). The first hour has its own usual (1.65× a normal hour until 3 days of history exist).",
        "Needed: build-up in the trade's direction of at least 1.5× usual. Rising or falling 50 EMA also needs the day's futures build-up in the trade's direction; on a flat EMA the day's OI only adds points.",
        "One-candle wait: if the breakout candle has no surge, the setup shows under Waiting for OI. If the next candle brings the surge and price stays beyond the base, it becomes an idea with entry one candle later; if not, it is dropped and logged as rejected by OI.",
      ]),
      h("h3", { class: "readme-h" }, "6. Top 5 score"),
      tbl(["Part", "Price Action", "Price+OI", "How it is measured"], [
        ["Candle strength", "14", "10", "Body 50% → 0, 80%+ → full; close in the top third → 0, top 10% → full (averaged)."],
        ["Candle size", "11", "8", "Range vs the usual for that hour (last 10 sessions): 1× → 0, 2×+ → full."],
        ["Volume", "10", "7", "Volume vs the usual for that hour: 1× → 0, 2×+ → full. Missing (Yahoo's 9:15 candle): half."],
        ["Base tightness", "16", "12", "Base range vs the daily range: 1.5× → 0, 0.5× or tighter → full."],
        ["Base length", "11", "8", "7 candles → 0, 21+ → full."],
        ["Near the 50 EMA", "14", "10", "Breakout close vs the EMA: 2% or less → full, 6%+ → 0."],
        ["Breakout margin", "14", "10", "Close beyond the base: just beyond → 0, 1%+ → full."],
        ["Signal-hour OI", "–", "15", "1.5× usual → 5, 4×+ usual → 15."],
        ["Day OI", "–", "10", "The day's build-up in the trade's direction: 0% → 0, 8%+ → 10."],
        ["Rejection setups", "same slots", "same slots", "No base, so the slots measure the rejection instead: candle strength → wick strength (half wick size vs the daily range: 0.3× = 0, 1×+ = full; half close position); base tightness → first touch (no earlier EMA touch in ~3 sessions = full, 3+ = 0); base length → stop room (stop 0.25× the daily range = 0, 0.6×+ = full); near 50 EMA → trend strength (EMA slope 0.5% = 0, 2%+ = full over 20 candles); breakout margin → shakeout depth (how far the wick went past the EMA: 0 = 0, 0.5× the daily range+ = full)."],
        ["Sector", "10", "10", "Long: sector Leading or Improving on the Sector Strength RRG. Short: Lagging or Weakening."],
      ]),
      h("h3", { class: "readme-h" }, "7. Warnings (never remove an idea)"),
      tbl(["Warning", "When"], [
        ["F&O ban", "The stock is in NSE's F&O ban list today (no new positions allowed)."],
        ["Results", "Quarterly results within 5 sessions (dates from Sector Strength)."],
        ["Stop distance", "Stop closer than 0.4% from the entry (noise can hit it)."],
        ["Daily trend", "Long below / Short above the 20-day simple average of daily closes."],
        ["Market regime", "Long while Sector Strength's regime light is Red, or Short while it is Green."],
        ["Breakout volume", "Breakout candle's volume below the usual for that hour."],
        ["Candle size", "Range below 0.6× (small) or above 2.5× (very big) the usual for that hour."],
        ["Chop", "3 or more 50 EMA crosses in the 3 sessions before the signal."],
      ]),
      h("h3", { class: "readme-h" }, "8. All trade ideas today"),
      list([
        "Every run's ideas are kept for the day, per tab, as Run 1 (about 10:19), Run 2 (11:19) … plus any Run scanner presses. A setup already listed in an earlier run is tagged “also Run N”; “also PA” / “also P+OI” means it qualifies on the other tab too.",
      ]),
      h("h3", { class: "readme-h" }, "9. Old rules (background only)"),
      list([
        "The earlier 50 EMA cross rules (a solid candle crosses the 50 EMA, the day's futures build-up as the filter, stop at the candle or 10-candle swing, exit on a close back across the EMA) still run at every scan. They are no longer shown on the screener; their signals are logged so Track record can compare them with the new rules.",
      ])),

    sec("Track record", "Signal log",
      list([
        "Every idea from both tabs is saved the first time a scan lists it, with its setup, score parts and warnings; Price+OI also saves setups that OI did not confirm. The old 50 EMA cross rules keep logging in the background.",
        "Later scans fill in the result from the entry candle's open: stop, 1:2 target or 5 sessions (old rules: also a close back across the 50 EMA, or the stop/target/5-session view).",
        "R = result ÷ risk to the stop. Net % is after 0.1% costs. Reached 1R = at least 1R in profit at some point. Groups with fewer than 20 finished signals are greyed out.",
      ])),

    sec("Suggested index trades", "Swing only: monthly chain, up to 5 sessions",
      tbl(["Factor", "Score", "Reading"], [
        ["OI shift, ATM ±2 strikes", "−1 to +1", "Change over the last 60 minutes. Put writing leads: +1 with call unwinding at resistance, +0.5 without. Call writing leads: −1 / −0.5."],
        ["PCR (total OI)", "−1 to +1", "Above 1.20: +1 (above 1.60: +0.5, crowded). Below 0.80: −1 (below 0.50: −0.5). 0.85–1.15: neutral."],
        ["PCR intraday slope", "−1 to +1", "Rising 0.03 or more per hour: +1; falling as much: −1. Needs 4+ snapshots over 45+ minutes."],
        ["Change-in-OI PCR (day)", "−1 to +1", "Fresh puts vs fresh calls today: above 1.20: +1, below 0.80: −1."],
        ["Futures OI build-up", "−1 to +1", "Long build-up +1, short covering +0.5, long unwinding −0.5, short build-up −1."],
      ]),
      list([
        "Total −5 to +5. LONG at +2.5 or more, SHORT at −2.5 or less; Strong at ±3.5 or beyond. The monthly expiry must be 7+ days away.",
        "Futures levels by two methods. OI walls: stop at the put wall, target at the call wall (reverse for Short), valid when reward is at least 1.5 × risk. Volatility: 5-session expected move from ATM IV; stop 0.6 × that move, target 1.5 × the stop.",
        "The day's official signal is saved at 3:15 pm (signal history).",
      ])),

    sec("F&O index analysis warnings", null,
      list([
        "Squeeze: PCR at 0.50 or below, spot up 0.15%+ in 60 minutes and call OI near ATM falling (put-writer covering is the mirror at PCR 1.80+).",
        "Expiry day and expiry eve: OI readings are less reliable as positions close or roll.",
      ])),

    sec("My trades", null,
      list([
        "Stock trades from the Price Action and Price+OI tabs close automatically only at the stop; you close the rest by hand (the target is shown). Older stock trades close at the stop, the target, or after 5 sessions (hourly candles).",
        "Index futures trades close at the stop or target on the futures price (checked every 15 minutes), or after 5 sessions.",
        "P&L ₹ = (sell − buy) × lots × lot size − charges. Stock P&L % is after 0.1% costs.",
        "Totals at the top cover the current financial year (April–March) and start fresh each 1 April; completed years move to Year by year. Closed trades are locked; a trade you close by hand can still be edited or reopened until the 7:40 pm check (trades closed automatically lock at once).",
      ])),

    sec("Timing", null,
      list([
        "Stock screener: about 4 minutes after each hourly candle closes (10:19 … 15:19, and 15:34), plus the Run scanner button.",
        "Index analysis, option chain and suggested index trades: every 15 minutes, 9:15–15:30.",
        "Sector boost, regime light and results dates come from the Sector Strength site's evening update.",
      ])));
}

// ------------------------------------------------------------------ routing
async function route() {
  const app = document.getElementById("app");
  const tab = (location.hash.match(/^#\/(\w+)/) || [])[1] || "stocks";
  document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const who = document.getElementById("who");
  if (LIVE) {
    const { data } = await sb.auth.getSession();
    state.session = data.session;
    if (!state.session) { who.replaceChildren(); return viewSignIn(app); }
    const mail = state.session.user.email;
    who.replaceChildren(h("span", null, mail), h("button", { type: "button", onclick: async () => { await sb.auth.signOut(); route(); } }, "Sign out"));
    if (CFG.email && mail.toLowerCase() !== CFG.email.toLowerCase()) return viewSignIn(app, `${mail} does not have access to this desk.`);
  } else {
    who.replaceChildren(h("span", null, "Preview with sample data"));
  }
  try {
    if (tab === "index") await viewIndex(app);
    else if (tab === "chain") await viewChain(app);
    else if (tab === "swing") await viewSwing(app);
    else if (tab === "trades") await viewTrades(app);
    else if (tab === "watch") await viewWatch(app);
    else if (tab === "record") await viewRecord(app);
    else if (tab === "readme") viewReadme(app);
    else await viewStocks(app);
  } catch (err) {
    render(app, h("p", { class: "empty" }, `Could not load the data (${err.message}). Refresh to try again.`));
  }
  clearInterval(refreshTimer);
  if (tab !== "trades" && tab !== "readme") refreshTimer = setInterval(() => { if (!document.getElementById("dlg").open) route(); }, 5 * 60 * 1000);
}

(function restore() {
  try { const i = localStorage.getItem("desk-idx"); if (SYMS.includes(i)) state.idx = i; } catch (e) { /* off */ }
})();
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
document.getElementById("theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  store("desk-theme", dark ? "light" : "dark");
  route();
});
if (LIVE) {
  sb.auth.onAuthStateChange((event) => {
    if (event === "SIGNED_IN") {
      if (location.search.includes("code=")) history.replaceState(null, "", location.pathname + (location.hash || "#/stocks"));
      route();
    }
  });
}
route();
