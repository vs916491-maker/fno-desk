/* F&O Desk - static site on GitHub Pages, data in Supabase.
   Tabs (hash routes): #/stocks  #/index  #/chain  #/swing  #/trades
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
async function updateTrade(id, vals) {
  if (LIVE) {
    const { error } = await sb.from("trades").update(vals).eq("id", id);
    if (error) throw new Error(error.message);
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

// ------------------------------------------------------------------ trade dialog
function tradeDialog(prefill, onSaved) {
  if (prefill && prefill.id && prefill.status === "closed") return;   // closed trades are locked
  const dlg = document.getElementById("dlg");
  const t = { kind: "stock", side: "Long", source: "manual", ...prefill };
  const field = (label, name, attrs = {}, wide = false) =>
    h("label", { class: wide ? "wide" : null }, label, h("input", { name, value: t[name] ?? "", ...attrs }));
  const isIndex = t.kind === "index";
  const nowLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const err = h("p", { class: "err", role: "alert" });
  const form = h("form", { method: "dialog" },
    h("h2", null, prefill.id ? "Edit trade" : prefill.symbol ? `I took this trade: ${prefill.symbol}` : "Add a trade"),
    h("p", { class: "note" }, isIndex ? "Index futures, P&L in rupees (points × lots × lot size − charges)." : "Stock trade, P&L in % after 0.1% costs (add quantity for rupees)."),
    h("div", { class: "form-grid" },
      h("label", null, "Type", h("select", { name: "kind" },
        ["stock", "index"].map((k) => h("option", { value: k, selected: t.kind === k || null }, k === "stock" ? "Stock" : "Index futures")))),
      field("Symbol", "symbol", { required: true, autocapitalize: "characters" }),
      h("label", null, "Side", h("select", { name: "side" }, ["Long", "Short"].map((k) => h("option", { selected: t.side === k || null }, k)))),
      field("Entry time", "entry_time", { type: "datetime-local", value: (t.entry_time || nowLocal).slice(0, 16), required: true }),
      field("Entry", "entry", { type: "number", step: "any", required: true }),
      field("Stop", "stop", { type: "number", step: "any" }),
      field("Target", "target", { type: "number", step: "any" }),
      isIndex ? field("Lots", "lots", { type: "number", step: "1", min: "1", value: t.lots ?? 1 }) : field("Quantity (optional)", "qty", { type: "number", step: "1" }),
      isIndex ? field("Lot size", "lot_size", { type: "number", step: "1" }) : null,
      isIndex ? field("Futures expiry", "expiry", { type: "date" }) : null,
      isIndex ? field("Charges ₹ (optional)", "charges", { type: "number", step: "any" }) : null,
      isIndex ? field("Method", "method") : null,
      h("label", { class: "wide" }, "Notes", h("textarea", { name: "notes" }, t.notes || ""))),
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
    if (v.kind === "index") Object.assign(row, { lots: +v.lots || 1, lot_size: +v.lot_size || null, expiry: v.expiry || null,
      charges: v.charges ? +v.charges : 0, method: v.method || null, instrument: "Futures" });
    else row.qty = v.qty ? +v.qty : null;
    try {
      if (prefill.id) await updateTrade(prefill.id, row); else await addTrade({ ...row, status: "open" });
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
    const v = readForm(form), exit = +v.exit, dir = tr.side === "Long" ? 1 : -1;
    const vals = { exit, exit_time: v.exit_time, exit_reason: v.exit_reason, status: "closed" };
    if (tr.kind === "index") {
      vals.pnl_inr = +((exit - tr.entry) * dir * (tr.lots || 1) * (tr.lot_size || 1) - (tr.charges || 0)).toFixed(2);
      vals.net_pct_after_cost = +(((exit / tr.entry) - 1) * 100 * dir).toFixed(3);
    } else {
      vals.net_pct_after_cost = +(((exit / tr.entry) - 1) * 100 * dir - 0.1).toFixed(3);
      if (tr.qty) vals.pnl_inr = +((exit - tr.entry) * dir * tr.qty - tr.entry * tr.qty * 0.001).toFixed(2);
    }
    try { await updateTrade(tr.id, vals); dlg.close(); onSaved && onSaved(); } catch (ex) { err.textContent = ex.message; }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
}

// ------------------------------------------------------------------ tab 1: stock screener
async function viewStocks(app) {
  const d = await doc("stock_screener");
  if (!d) return render(app, pageHead("F&O stock screener", null), h("p", { class: "empty" }, "No scan yet. The first scan runs at about 10:20 on the next market day."));
  const ideas = d.ideas || [];
  const top = ideas.filter((x) => x.top_rank).sort((a, b) => a.top_rank - b.top_rank);
  const early = d.early ? h("div", { class: "banner expiry" }, h("b", null, "Early scan. "),
    `No hourly candle has closed yet today (the first one closes at 10:15). These signals come from the previous session's candles, up to ${new Date(d.early.last_candle).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}, and the futures check covers only the first ${d.early.futures_minutes} minutes of today, so OI changes and scores are small. New signals for today start with the 10:19 scan.`) : null;
  const watch = (x) => watchDialog({ kind: "stock", symbol: x.symbol, side: x.side, entry: x.levels.entry, stop: x.levels.stop,
    target: x.levels.target, lot_size: x.lot_size, source: "screener", signal_time: x.signal_time,
    method: `50 EMA cross ${x.signal_time.slice(11, 16)}${x.futures ? ` + ${x.futures.buildup}` : ""}` });
  const took = (x) => tradeDialog({ kind: "stock", symbol: x.symbol, side: x.side, entry: x.levels.entry, stop: x.levels.stop,
    target: x.levels.target, source: "scanner", notes: `50 EMA cross ${x.signal_time.slice(11, 16)} + ${x.futures.buildup}` }, () => { location.hash = "#/trades"; });

  const topCards = top.map((x) => h("div", { class: "idea top" },
    h("h3", null, h("span", null, h("span", { class: "rank" }, `#${x.top_rank}`), " ", x.symbol, " ", chartLink(x.symbol)), h("small", null, `score ${Math.round(x.scoring.score)}`)),
    h("div", { class: "btn-row" }, sideTag(x.side), h("span", { class: "meta" }, `signal ${x.signal_time.slice(11, 16)}, ${x.entry_status}`),
      x.lot_size ? h("span", { class: "flag fno" }, `lot ${x.lot_size}`) : null),
    levelsBox(x.levels),
    h("div", { class: "meta" }, `Futures: ${x.futures.buildup}, OI ${pct(x.futures.pchg_oi, 1)}, price ${pct(x.futures.pchange)}. `,
      `Futures levels ${fmt(x.futures_levels.entry)} / ${fmt(x.futures_levels.stop)} / ${fmt(x.futures_levels.target)}`),
    h("div", { class: "parts" },
      part("Candle clarity", x.scoring.clarity, `${Math.round(x.scoring.clarity)}`),
      part("OI change", x.scoring.oi_change, `${Math.round(x.scoring.oi_change)}`),
      part("Sector boost", x.scoring.boost * 10, x.scoring.boost ? `+${x.scoring.boost}` : "0")),
    x.scoring.sector ? h("div", { class: "meta" }, `${x.scoring.sector} sector is ${x.scoring.sector_quadrant} on the Sector Strength RRG`) : null,
    h("div", { class: "btn-row" }, h("button", { class: "btn primary small", type: "button", onclick: () => took(x) }, "I took this trade"),
      h("button", { class: "btn small", type: "button", onclick: () => watch(x) }, "Move to watchlist"))));

  const ideaTable = h("table", null,
    h("thead", null, h("tr", null, ["Stock", "Side", "Signal", "Entry", "Stop", "Target", "Risk", "Futures", "OI chg", "Score", ""].map((c, i) =>
      h("th", { class: i < 2 ? "l" : null }, c)))),
    h("tbody", null, ideas.map((x) => h("tr", { style: "cursor:default" },
      h("td", { class: "l name" }, x.symbol, x.top_rank ? h("span", { class: "flag fno" }, `Top ${x.top_rank}`) : null, chartLink(x.symbol)),
      h("td", { class: "l" }, sideTag(x.side)),
      h("td", null, x.signal_time.slice(11, 16)),
      h("td", null, fmt(x.levels.entry)), h("td", null, fmt(x.levels.stop)), h("td", null, fmt(x.levels.target)),
      h("td", null, pct(x.levels.risk_pct, 2, false)),
      h("td", null, x.futures.buildup), h("td", null, pct(x.futures.pchg_oi, 1)),
      h("td", null, Math.round(x.scoring.score)),
      h("td", null, h("div", { class: "btn-row nowrap" }, h("button", { class: "btn small", type: "button", onclick: () => took(x) }, "I took this trade"),
        h("button", { class: "btn small", type: "button", onclick: () => watch(x) }, "Watchlist")))))));

  const others = d.others || [];
  const otherTable = h("table", null,
    h("thead", null, h("tr", null, ["Stock", "Side", "Signal", "Close", "Why it is not listed"].map((c, i) => h("th", { class: i === 1 || i === 0 || i === 4 ? "l" : null }, c)))),
    h("tbody", null, others.map((x) => h("tr", { style: "cursor:default" },
      h("td", { class: "l name" }, x.symbol, chartLink(x.symbol)), h("td", { class: "l" }, sideTag(x.side)), h("td", null, x.signal_time.slice(11, 16)),
      h("td", null, fmt(x.close)), h("td", { class: "l" }, x.reason)))));

  render(app, 
    pageHead("F&O stock screener", `Last scan ${when(d.ts)}, ${d.scanned} F&O stocks`),
    scanBar(d.ts),
    early,
    h("p", { class: "intro" }, "A solid hourly candle closes across the 50 EMA, and futures show fresh build-up in the same direction. Entry at the next candle's open, stop beyond the breakout candle or recent swing (whichever is closer), target 1:2, exit on a close back across the 50 EMA or after 5 sessions."),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Top 5"),
      h("p", null, "Candle clarity 60% + OI change 40%, plus 10 points when the stock's sector leads in the trade's direction")),
      top.length ? h("div", { class: "ideas" }, topCards) : h("p", { class: "empty" }, "No confirmed ideas in this scan.")),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `All trade ideas (${ideas.length})`), h("p", null, "Newest first")),
      ideas.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, ideaTable)) : h("p", { class: "empty" }, "None right now.")),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `Other trend switches (${others.length})`), h("p", null, "50 EMA crosses that did not qualify")),
      others.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, otherTable)) : h("p", { class: "empty" }, "None.")),
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
    target: w.target ?? undefined, lots: w.kind === "index" ? 1 : undefined, lot_size: w.lot_size ?? undefined, expiry: w.expiry ?? undefined,
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

async function viewTrades(app) {
  const all = await loadTrades();
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
  const tot = blank();
  closed.forEach((t) => addTrade(tot, t));
  archive.forEach((r) => addMonth(tot, r));
  const pf = tot.loss < 0 ? tot.gain / Math.abs(tot.loss) : null;
  const archivedN = archive.reduce((a2, r) => a2 + r.trades, 0);
  const stats = h("div", { class: "stats" },
    stat("Closed trades", tot.n, `${open.length} open${archivedN ? ` · ${archivedN} older than 3 months kept as monthly totals` : ""}`),
    stat("Win rate", tot.pctN ? `${Math.round((tot.w / tot.pctN) * 100)}%` : "–", `${tot.w} won, ${tot.pctN - tot.w} lost`),
    stat("Average per trade", tot.pctN ? pct(tot.sum / tot.pctN) : "–", "Net % after costs", sign(tot.sum)),
    stat("Profit factor", isNum(pf) ? pf.toFixed(2) : "–", "Total % won ÷ total % lost"),
    stat("Net P&L in %", tot.pctN ? pct(tot.sum) : "–", "Sum of net % of closed trades", sign(tot.sum)),
    stat("Net P&L in ₹", tot.inrN ? inr(tot.inr) : "–", "Index futures and stocks with quantity", sign(tot.inr)));

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

  const row = (t, isOpen) => h("tr", { style: "cursor:default" },
    h("td", { class: "l" }, when(t.entry_time)),
    h("td", { class: "l name" }, t.symbol, chartLink(t.symbol, t.kind === "index" ? "fut" : "stock", "60"), h("small", null, t.kind === "index" ? `Index futures${t.lots ? `, ${t.lots} lot${t.lots > 1 ? "s" : ""}` : ""}` : (t.source || "stock"))),
    h("td", { class: "l" }, sideTag(t.side)),
    h("td", null, fmt(t.entry)), h("td", null, fmt(t.stop)), h("td", null, fmt(t.target)),
    isOpen ? null : h("td", null, fmt(t.exit)),
    isOpen ? null : h("td", { class: "l" }, t.exit_reason || "–"),
    isOpen ? null : h("td", { class: sign(t.net_pct_after_cost) }, pct(t.net_pct_after_cost)),
    isOpen ? null : h("td", { class: sign(t.pnl_inr) }, inr(t.pnl_inr)),
    h("td", { class: "l" }, h("div", { class: "btn-row" },
      isOpen ? h("button", { class: "btn small", type: "button", onclick: () => closeDialog(t, rerender) }, "Close") : null,
      isOpen ? h("button", { class: "btn small", type: "button", onclick: () => tradeDialog(t, rerender) }, "Edit") : h("span", { class: "muted", title: "Closed trades are locked" }, "Locked"),
      h("button", { class: "btn small", type: "button", onclick: async () => { if (confirm(`Delete the ${t.symbol} trade? This cannot be undone.`)) { await deleteTrade(t.id); rerender(); } } }, "Delete"))));
  const table = (rows, isOpen) => h("table", null,
    h("thead", null, h("tr", null, ["Entry time", "Symbol", "Side", "Entry", "Stop", "Target", ...(isOpen ? [] : ["Exit", "Reason", "Net %", "P&L ₹"]), ""].map((c, i) =>
      h("th", { class: [0, 1, 2].includes(i) || c === "Reason" ? "l" : null }, c)))),
    h("tbody", null, rows.map((t) => row(t, isOpen))));
  const viewSeg = h("div", { class: "seg", role: "group", "aria-label": "Show" }, [["all", "All"], ["stock", "Stocks"], ["index", "Index futures"]].map(([k, l]) =>
    h("button", { type: "button", "aria-pressed": String(view === k), onclick: () => { state.tradeView = k; rerender(); } }, l)));
  render(app, 
    pageHead("My trades", LIVE ? "Saved to your private database" : "Preview: changes are not saved"),
    h("div", { class: "filters" }, viewSeg,
      h("button", { class: "btn primary", type: "button", onclick: () => tradeDialog({}, rerender) }, "Add a trade"),
      h("button", { class: "btn", type: "button", onclick: () => exportCsv(all) }, "Export CSV")),
    h("p", { class: "note" }, "Open trades close automatically: stocks at the stop, target or after 5 sessions (hourly candles); index futures at the stop or target on the futures price (every 15 minutes) or after 5 sessions."),
    stats,
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
    else await viewStocks(app);
  } catch (err) {
    render(app, h("p", { class: "empty" }, `Could not load the data (${err.message}). Refresh to try again.`));
  }
  clearInterval(refreshTimer);
  if (tab !== "trades") refreshTimer = setInterval(() => { if (!document.getElementById("dlg").open) route(); }, 5 * 60 * 1000);
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
