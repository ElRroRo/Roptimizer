// The portfolio builder's model, rules and editor, shared by every way of drawing the tree.
// A page supplies drawTree() and dropAt(px, py, node), plus its own styles.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---- the model: one tree of subportfolios and assets ----------------------------------------------
let uid = 0;
const LIM = () => ({ min: { on: false, v: null }, max: { on: false, v: null }, wpmin: { on: false, v: null }, wpmax: { on: false, v: null } });
function G(name, children, o = {}) {
  const lim = LIM(); if (o.min != null) lim.min = { on: true, v: o.min }; if (o.max != null) lim.max = { on: true, v: o.max };
  return { id: "n" + ++uid, kind: "group", name, children, lim, view: { r: null, m: null, p: null }, set: {}, inherit: false, open: true };
}
function A(t, o = {}) {
  const a = byTicker[t], lim = LIM(); if (o.min != null) lim.min = { on: true, v: o.min };
  return { id: "n" + ++uid, kind: "asset", t: t || "", tradeAs: "", h: 12, lim,
    vt: a && a.view != null ? { k: "ret", v: a.view } : null,            // the box the manager typed: target price or return
    um: a && a.sdMinus != null ? { k: "pts", v: a.sdMinus } : null,      // uncertainty below, typed in $ or points
    up: a && a.sdPlus != null ? { k: "pts", v: a.sdPlus } : null };      // uncertainty above
}
// ---- the library bridge: the saved portfolio <-> this tree (mso/portfolio.py's shape) --------------------
const SETKEYS = { cvar: "cvar_floor", strict: "floor_strictness", tail: "tail", conc: "concentration", stop: "window", cap: "maxgen", pop: "pop_per_dim" };
const KEYSET = Object.fromEntries(Object.entries(SETKEYS).map(([a, b]) => [b, a]));
const limIn = (L) => ({ on: !!(L && L.on), v: L && L.value != null ? L.value : null });
const limOut = (l) => ({ on: !!l.on, value: l.v });
function fromPortfolio(P) {
  const conv = (x) => {
    if (x.kind === "asset") {
      const a = P.assets[x.ticker] || {}, v = a.view, n = A(x.ticker);
      n.tradeAs = a.trade_as || ""; n.eq = a.equilibrium ?? null; n.exIdio = !!a.exclude_idio_jump; n.h = v && v.horizon_months ? v.horizon_months : 12;
      n.vt = v ? { k: v.form === "price" ? "price" : "ret", v: v.value } : null;
      const u = (side) => (v && v[side] != null ? { k: (v[`unit_${side}`] || v.unit) === "dollars" ? "$" : "pts", v: v[side] } : null);
      n.um = u("minus"); n.up = u("plus");
      n.lim = { min: limIn(x.limits?.min), max: limIn(x.limits?.max), wpmin: limIn(x.portfolio_limits?.min), wpmax: limIn(x.portfolio_limits?.max) };
      return n; }
    const g = G(x.name, x.children.map(conv));
    g.lim = { min: limIn(x.limits?.min), max: limIn(x.limits?.max), wpmin: limIn(x.portfolio_limits?.min), wpmax: limIn(x.portfolio_limits?.max) };
    g.view = x.view ? { r: x.view.value, m: x.view.minus, p: x.view.plus } : { r: null, m: null, p: null };
    g.set = {}; Object.entries(x.settings || {}).forEach(([k, v]) => { if (KEYSET[k]) g.set[KEYSET[k]] = v; });
    g.inherit = Object.values(x.inherit || {}).some(Boolean);
    if (x.color_slot != null) g.slot = x.color_slot;
    return g; };
  return conv(P.tree);
}
function toPortfolio() {
  const assets = {};
  const conv = (n) => {
    const limits = n === ROOT ? {} : { min: limOut(n.lim.min), max: limOut(n.lim.max) }, plimits = n === ROOT ? {} : { min: limOut(n.lim.wpmin), max: limOut(n.lim.wpmax) };
    if (n.kind === "asset") {
      const old = PF.assets[n.t] || {};
      const view = n.vt ? { form: n.vt.k === "price" ? "price" : "return", value: n.vt.v, horizon_months: n.h,
        unit_minus: n.um?.k === "$" ? "dollars" : "points", unit_plus: n.up?.k === "$" ? "dollars" : "points", minus: n.um ? n.um.v : null, plus: n.up ? n.up.v : null } : null;
      if (n.t) assets[n.t] = { equilibrium: n.eq ?? old.equilibrium ?? null, view, exclude_idio_jump: n.exIdio ?? !!old.exclude_idio_jump, trade_as: n.tradeAs || null };
      return { kind: "asset", ticker: n.t, limits, portfolio_limits: plimits }; }
    const settings = {}; Object.entries(n.set || {}).forEach(([k, v]) => { if (SETKEYS[k] && v !== undefined) settings[SETKEYS[k]] = v; });
    const inherit = n.inherit ? Object.fromEntries(Object.values(SETKEYS).map((k) => [k, true])) : {};
    const v = n.view || {};
    return { kind: "group", name: n.name, children: n.children.map(conv), limits, portfolio_limits: plimits, settings, inherit,
      view: v.r != null ? { form: "return", value: v.r, horizon_months: 12, unit: "points", minus: v.m, plus: v.p } : null, color_slot: n.slot ?? null }; };
  const tree = conv(ROOT);
  return { ...PF, assets, tree, run: { ...(PF.run || {}), horizon_weeks: RUNSET.weeks, rf: RUNSET.rfSet ? RUNSET.rf : null, bands: RUNSET.bands || null } };
}
let ROOT = fromPortfolio(PF);
// Run-wide settings: the horizon and risk-free rate are the portfolio's (an unset rate is today's ^TNX); the
// scenario count follows the machine chosen for the next run (A100 30M; this computer up to 2M on a GPU, 400k on a CPU).
const MACHINE = () => API.store("mso.machine") || "laptop";
const RUNSET = { weeks: RUN.horizonWeeks, paths: MACHINE() === "a100" ? 30000000 : /^CPU/.test(LIVE.device || "") ? 400000 : 2000000,
  rf: PF.run && PF.run.rf != null ? PF.run.rf : LIVE.rf, rfSet: !!(PF.run && PF.run.rf != null), bands: (PF.run && PF.run.bands) || null };
const SETTINGS = [
  { k: "cvar", label: "CVaR floor", def: () => -0.40, unit: "%", pct: true },
  { k: "strict", label: "Floor strictness", def: () => "soft", opts: [["soft", "soft, penalty 5 × breach"], ["hard", "hard"]] },
  { k: "tail", label: "Tail level", def: () => 0.05, unit: "%", pct: true },
  { k: "conc", label: "Concentration penalty", def: (n) => (n === ROOT ? 0.20 : null), blankOff: true },
  { k: "stop", label: "Stop window", def: () => 5, unit: "generations" },
  { k: "cap", label: "Generation cap", def: () => 80 },
  { k: "pop", label: "Population", def: () => 30 },
];

let PARENT = new Map(), sel = null, drag = null, dragged = false;
const undoStack = [];
function index() { PARENT = new Map(); const walk = (n, p) => { PARENT.set(n.id, p); if (n.kind === "group") n.children.forEach((c) => walk(c, n)); }; walk(ROOT, null); assignSlots(); }
function find(id, n = ROOT) { if (n.id === id) return n; if (n.kind === "group") for (const c of n.children) { const f = find(id, c); if (f) return f; } return null; }
const parentOf = (n) => PARENT.get(n.id);
const byLabel = (l) => { let f = null; const w = (n) => { if (!f && label(n) === l) f = n; if (n.kind === "group") n.children.forEach(w); }; w(ROOT); return f; };
const isAncestor = (a, n) => { for (let p = n; p; p = parentOf(p)) if (p === a) return true; return false; };
const label = (n) => (n.kind === "asset" ? n.t || "new asset" : n.name);
const pathText = (n) => { const out = []; for (let p = parentOf(n); p; p = parentOf(p)) out.push(p.name); return out.join(" / "); };
const topOf = (n) => { let x = n; while (parentOf(x) && parentOf(x) !== ROOT) x = parentOf(x); return x; };
// Group colours: a fixed list (Tokyo Night hues, adjacent pairs checked against dataviz's normal-vision floor on the
// panel; blue comes last). Each top-level subportfolio holds a slot for life, whatever
// it is called and wherever it moves, so renaming or reordering never repaints. Past eight, groups are drawn muted.
const PALETTE = ["#e0af68", "#bb9af7", "#9ece6a", "#f7768e", "#7dcfff", "#ff9e64", "#73daca", "#7aa2f7"];
function assignSlots() { const used = new Set(); ROOT.children.forEach((c) => { if (c.kind !== "group") return;
  if (c.slot == null || used.has(c.slot)) c.slot = [...PALETTE.keys()].find((i) => !used.has(i)) ?? -1; used.add(c.slot); }); }
const colorOf = (n) => { if (n === ROOT) return "var(--ink-2)"; const t = topOf(n); return t.kind === "group" ? PALETTE[t.slot] ?? "var(--mute)" : "var(--ink-2)"; };
function snapshot() { undoStack.push(JSON.stringify({ ROOT, RUNSET, sel })); if (undoStack.length > 100) undoStack.shift(); }
function restore() { const s = undoStack.pop(); if (!s) return; const o = JSON.parse(s); ROOT = o.ROOT; Object.assign(RUNSET, o.RUNSET); sel = o.sel; render(true); }

// ---- view arithmetic: exact, no interpretation (view-inputs ticket) ---------------------------------
const priceOf = (n) => byTicker[n.t]?.price ?? null;
const annual = (n, p) => Math.pow(p / priceOf(n), 12 / n.h) - 1;
const fromAnnual = (n, r) => priceOf(n) * Math.pow(1 + r, n.h / 12);
function target(n) { if (!n.vt || priceOf(n) == null) return n.vt?.k === "price" ? n.vt.v : null; return n.vt.k === "price" ? n.vt.v : fromAnnual(n, n.vt.v); }
function retOf(n) { if (!n.vt) return null; if (n.vt.k === "ret") return n.vt.v; return priceOf(n) == null ? null : annual(n, n.vt.v); }
function sigma(n, side) {           // one side of the uncertainty, in annual points
  const u = n[side], r = retOf(n); if (!u || r == null) return null;
  if (u.k === "pts") return u.v;
  const T = target(n); if (T == null) return null; const edge = side === "um" ? T - u.v : T + u.v; if (edge <= 0) return null;
  return Math.abs(annual(n, edge) - r);
}
function dollars(n, side) {
  const u = n[side], r = retOf(n); if (!u || r == null) return null; if (u.k === "$") return u.v;
  const T = target(n); if (T == null || priceOf(n) == null) return null; const e = side === "um" ? r - u.v : r + u.v; if (1 + e <= 0) return null;
  return Math.abs(fromAnnual(n, e) - T);
}
// Lopsided view -> the split-normal mean and sd the model can use.
function splitNormal(m, sm, sp) { const k = Math.sqrt(2 / Math.PI); return { mean: m + k * (sp - sm), sd: Math.sqrt((1 - 2 / Math.PI) * (sp - sm) ** 2 + sp * sm) }; }
function modelOf(n) { const m = retOf(n), sm = sigma(n, "um"), sp = sigma(n, "up"); if (m == null || sm == null || sp == null) return null; return { m, sm, sp, ...splitNormal(m, sm, sp) }; }
function groupModel(g) { const v = g.view; if (v.r == null || v.m == null || v.p == null) return null; return { m: v.r, sm: v.m, sp: v.p, ...splitNormal(v.r, v.m, v.p) }; }

// ---- limits and their consequences -----------------------------------------------------------------
const lv = (l) => (l.on && l.v != null ? l.v : null);
function shareBounds(n) {
  const p = parentOf(n); if (!p) return [1, 1]; const sib = p.children; if (sib.length === 1) return [1, 1];
  const mn = (c) => lv(c.lim.min) ?? 0, mx = (c) => lv(c.lim.max) ?? 1, others = sib.filter((c) => c !== n);
  return [Math.max(0, mn(n), 1 - d3.sum(others, mx)), Math.max(0, Math.min(mx(n), 1 - d3.sum(others, mn)))];
}
function effective() {   // each node's possible share of the whole portfolio; levels are searched independently
  const walk = (n, lo, hi) => { const [a, b] = shareBounds(n); n._share = [a, b]; let l = lo * a, h = hi * b;
    if (n !== ROOT) { const wmin = lv(n.lim.wpmin), wmax = lv(n.lim.wpmax); if (wmax != null) h = Math.min(h, wmax); if (wmin != null) l = Math.max(l, wmin); }
    n._eff = [l, h]; if (n.kind === "group") n.children.forEach((c) => walk(c, l, h)); };
  walk(ROOT, 1, 1);
}
const eqEW = (n) => (n.kind === "asset" ? byTicker[n.t]?.eq ?? null : d3.mean(n.children.map(eqEW).filter((x) => x != null)) ?? null);
function eqRange(g) {   // linear in the mix: put each child at its floor, then fill the best (or worst) first up to its cap
  const items = g.children.map((c) => ({ r: eqEW(c), lo: c._share[0], hi: c._share[1] })).filter((x) => x.r != null);
  if (!items.length) return null;
  const fill = (order) => { let left = 1 - d3.sum(items, (x) => x.lo), v = d3.sum(items, (x) => x.lo * x.r);
    for (const x of order) { const add = Math.min(x.hi - x.lo, Math.max(0, left)); v += add * x.r; left -= add; } return v; };
  return [fill([...items].sort((a, b) => a.r - b.r)), fill([...items].sort((a, b) => b.r - a.r))];
}

// ---- what blocks the run ---------------------------------------------------------------------------
function checks() {
  const out = [], seen = new Map();
  const walk = (n) => {
    if (n.kind === "asset") {
      if (!n.t) out.push({ id: n.id, b: true, text: "A new asset has no ticker yet." });
      else { if (priceOf(n) == null) out.push({ id: n.id, b: true, text: `${n.t} has no price yet; Refresh data fetches it.` });
        if (seen.has(n.t)) out.push({ id: n.id, b: true, text: `${n.t} is in the tree twice (also in ${seen.get(n.t)}).` }); else seen.set(n.t, parentOf(n).name);
        if (n.eq == null) out.push({ id: n.id, b: true, text: `${n.t} has no equilibrium return.` });
        if (n.vt && (!n.um || !n.up)) out.push({ id: n.id, b: true, text: `${n.t}: the view has no uncertainty ${!n.um && !n.up ? "on either side" : !n.um ? "below" : "above"}.` }); }
    } else {
      if (n !== ROOT && !n.children.length) out.push({ id: n.id, b: true, text: `${n.name} is empty.` });
      const kids = n.children, smin = d3.sum(kids, (c) => lv(c.lim.min) ?? 0), smax = d3.sum(kids, (c) => lv(c.lim.max) ?? 1);
      if (kids.length === 1) { const c = kids[0]; const mx = lv(c.lim.max), mn = lv(c.lim.min);
        if ((mx != null && mx < 1) || (mn != null && mn > 1)) out.push({ id: c.id, b: true, text: `${label(c)} is the only member of ${n.name}, so it must take 100%, but its limit says ${mx != null && mx < 1 ? "at most " + pct(mx, 0) : "at least " + pct(mn, 0)}.` });
        else if (n !== ROOT) out.push({ id: n.id, b: false, text: `${n.name} has one member: it takes 100% with no search.` }); }
      else if (kids.length > 1) { if (smin > 1 + 1e-9) out.push({ id: n.id, b: true, text: `Minimums inside ${n.name} add to ${pct(smin, 0)}.` });
        if (smax < 1 - 1e-9) out.push({ id: n.id, b: true, text: `Maximums inside ${n.name} add to only ${pct(smax, 0)}, so it cannot be fully invested.` }); }
      const v = n.view; if (v.r != null && (v.m == null || v.p == null)) out.push({ id: n.id, b: true, text: `${n.name}: the group view has no uncertainty.` });
      kids.forEach(walk);
    }
    if (n !== ROOT) { const L = n.lim; if (lv(L.min) != null && lv(L.max) != null && lv(L.min) > lv(L.max)) out.push({ id: n.id, b: true, text: `${label(n)}: minimum above maximum.` });
      if (lv(L.wpmin) != null && lv(L.wpmax) != null && lv(L.wpmin) > lv(L.wpmax)) out.push({ id: n.id, b: true, text: `${label(n)}: whole-portfolio minimum above maximum.` });
      if (n._eff && n._eff[0] > n._eff[1] + 1e-9) out.push({ id: n.id, b: true, text: `${label(n)}: its limits leave no feasible weight (${pct(n._eff[0], 1)} needed, ${pct(n._eff[1], 1)} allowed).` }); }
  };
  walk(ROOT); return out;
}

// ---- the tree view: each page supplies drawTree() and dropAt(px, py, node) ---------------------------
function visibleOrder() { const out = []; const walk = (n) => { out.push(n); if (n.kind === "group" && n.open) n.children.forEach(walk); }; walk(ROOT); return out; }
const countAssets = (n) => (n.kind === "asset" ? 1 : d3.sum(n.children, countAssets));
const effText = ([a, b]) => (Math.abs(a - b) < 5e-5 ? pct(a, 1) : `${pct(a, 1)} to ${pct(b, 1)}`);
function limitLabel(n) {
  if (n === ROOT) return ""; const p = parentOf(n), mn = lv(n.lim.min), mx = lv(n.lim.max), parts = [];
  if (mn != null && mx != null) parts.push(`${pct(mn, 0)} to ${pct(mx, 0)} of ${p.name}`); else if (mn != null) parts.push(`at least ${pct(mn, 0)} of ${p.name}`); else if (mx != null) parts.push(`at most ${pct(mx, 0)} of ${p.name}`);
  const wmax = lv(n.lim.wpmax); if (wmax != null) parts.push(`≤ ${pct(wmax, 0)} overall`);
  const gm = groupModel(n); if (gm) parts.push(`view ${pct(gm.mean, 1, true)}`);
  return parts.join(", ");
}

// ---- the inspector ---------------------------------------------------------------------------------
const fmtPts = (x) => (x == null ? "" : (x < 0 ? MINUS : x > 0 ? "+" : "") + Math.abs(x * 100).toFixed(1));
const fmtAbs = (x) => (x == null ? "" : (x * 100).toFixed(1));
const parseNum = (s) => { const v = parseFloat(String(s).replace(/[−–]/g, "-").replace(/[^0-9.\-]/g, "")); return Number.isFinite(v) ? v : null; };
function box(f, cls = "", attrs = "") { return `<input class="box ${cls}" data-f="${f}" ${attrs} autocomplete="off" spellcheck="false">`; }
function limBlock(n) {
  if (n === ROOT) return "";
  const p = parentOf(n), row = (k, text) => `<input type="checkbox" data-f="lim.${k}.on" id="l-${k}"><label for="l-${k}">${text}</label><span class="pair">${box(`lim.${k}.v`, "", 'placeholder="—"')}<span class="u">%</span></span>`;
  return `<div class="sec"><h3>Weight limits <span>each one on or off on its own</span></h3>
    <div class="lim">${row("min", `Minimum share of ${esc(p.name)}`)}${row("max", `Maximum share of ${esc(p.name)}`)}${row("wpmin", "Minimum of the whole portfolio")}${row("wpmax", "Maximum of the whole portfolio")}</div>
    <p class="cons" id="cons"></p></div>`;
}
function settingsBlock(n) {
  const p = parentOf(n);
  return `<div class="sec"><h3>Risk and search <span>for the search inside ${esc(n.name)}</span></h3>
    ${p ? `<label class="inh"><input type="checkbox" data-f="inherit"> Inherit from ${esc(p.name)}</label>` : ""}
    <table class="set"><tbody>${SETTINGS.map((S) => `<tr><td>${S.label}</td><td>${S.opts ? `<select class="box" data-f="set.${S.k}">${S.opts.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select>`
      : `${box(`set.${S.k}`, "", S.blankOff ? 'placeholder="off"' : "")}${S.unit ? ` <span class="u" style="color:var(--mute);font-size:12px">${S.unit}</span>` : ""}`}</td><td data-src="${S.k}"></td></tr>`).join("")}</tbody></table></div>`;
}
function resolve(n, k) {
  if (k in n.set) return { v: n.set[k], src: "set here" };
  const p = parentOf(n); if (n.inherit && p) { const r = resolve(p, k); return { v: r.v, src: r.src === "set here" || r.src === "default" ? `from ${p.name}` : r.src }; }
  return { v: SETTINGS.find((S) => S.k === k).def(n), src: "default" };
}
function inspector() {
  const n = find(sel) || ROOT, el = $("#insp");
  $("#insp-sub").textContent = n === ROOT ? "run-wide settings and the top-level search" : n.kind === "group" ? "subportfolio" : "asset view";
  if (n.kind === "asset") {
    const b = byTicker[n.t]?.beta;
    el.innerHTML = `<div class="ih"><h2><code>${esc(n.t || "new asset")}</code></h2></div><div class="path">in ${esc(pathText(n))}</div>
      <div class="f"><label for="f-t">Ticker</label><span class="pair">${box("t", "w", 'id="f-t" placeholder="e.g. AMD"')}</span>
        <label for="f-eq">Equilibrium</label><span class="pair">${box("eq", "", 'id="f-eq" placeholder="% a year"')}<span class="u">% a year, your input</span></span>
        <label for="f-ta">Trade as</label><span class="pair">${box("tradeAs", "w", `id="f-ta" placeholder="${esc(n.t || "same ticker")}" title="The ticker you actually buy, e.g. an ETF for a futures series"`)}</span>
        <span class="lab">Last close</span><span id="close"></span>
        <label for="f-ix">Own jumps</label><span class="pair" style="flex-wrap:nowrap"><input type="checkbox" data-f="exIdio" id="f-ix" style="accent-color:var(--att);margin:0"><label for="f-ix" class="u" style="cursor:pointer">exempt</label></span>
        <span></span><span class="u" style="color:var(--mute);font-size:12px;margin-top:-4px">market jumps only, none of its own (funds, bonds, indexes)</span></div>
      <div class="sec"><h3>View <span>optional; without one the asset uses its equilibrium return</span></h3>
        <div class="f"><label for="f-h">Horizon</label><span class="pair">${box("h", "", 'id="f-h"')}<span class="u">months; annualised by compounding</span></span>
          <span class="lab">Target ⟷ return</span><span class="pair">${box("target", "", 'placeholder="target $"')}<span class="link">⟷</span>${box("ret", "", 'placeholder="% a year"')}<span class="u">%</span></span>
          <span class="lab">Below the target</span><span class="pair">${box("um$", "", 'placeholder="− $"')}<span class="link">⟷</span>${box("umpts", "", 'placeholder="points"')}<span class="u">pts</span></span>
          <span class="lab">Above the target</span><span class="pair">${box("up$", "", 'placeholder="+ $"')}<span class="link">⟷</span>${box("uppts", "", 'placeholder="points"')}<span class="u">pts</span></span></div>
        <p class="hint">Alt-Down and Alt-Up step to the next asset in the same box. Bold = typed, kept when prices refresh. Below and above: how sure you are of the estimate (a DCF range), not bear and bull cases.</p>
        <p class="read" id="read"></p><div id="curve"></div></div>
      ${limBlock(n)}
      <div class="sec"><h3>Jump betas <span>from the jump database, read-only</span></h3><p class="cons" style="margin:0">${b ? `Crash β ${num(b.crash)} from ${b.crashN} surprise days (${betaSource(b.crashN)}). Rally β ${num(b.rally)} from ${b.rallyN} day${b.rallyN === 1 ? "" : "s"} (${betaSource(b.rallyN)}; direct needs ${DIRECT_MIN}).` : "None yet: the next Refresh data estimates them."}</p></div>`;
  } else {
    const isRoot = n === ROOT;
    el.innerHTML = `<div class="ih"><h2>${esc(n.name)}</h2></div><div class="path">${isRoot ? "the whole portfolio" : `in ${esc(pathText(n))}`}; ${countAssets(n)} asset${countAssets(n) === 1 ? "" : "s"}</div>
      ${isRoot ? `<div class="f"><span class="lab">Data snapshot</span><span>${HIST.fetched}</span>
        <label for="f-w">Horizon</label><span class="pair">${box("run.weeks", "", 'id="f-w"')}<span class="u">weeks, run-wide</span></span>
        <label for="f-p">Scenarios</label><span class="pair">${box("run.paths", "w", 'id="f-p"')}<span class="u">paths</span></span>
        <label for="f-rf">Risk-free rate</label><span class="pair">${box("run.rf", "", 'id="f-rf"')}<span class="u">% a year</span></span>
        <label for="f-bd">Sensitivity band</label><span class="pair">${box("run.bands", "", 'id="f-bd" placeholder="off"')}<span class="u">repeats per search; off when empty</span></span></div>`
      : `<div class="f"><label for="f-n">Name</label><span class="pair">${box("name", "w", 'id="f-n"')}</span></div>`}
      ${limBlock(n)}
      ${isRoot ? "" : `<div class="sec"><h3>View on the group <span>optional; a macro call on ${esc(n.name)} as a whole</span></h3>
        <div class="f"><span class="lab">Return</span><span class="pair">${box("gv.r", "", 'placeholder="% a year"')}<span class="u">% a year</span></span>
          <span class="lab">Below / above</span><span class="pair">${box("gv.m", "", 'placeholder="points"')}${box("gv.p", "", 'placeholder="points"')}<span class="u">pts</span></span></div>
        <p class="hint">Moves how much ${esc(parentOf(n).name)} gives it, never the mix inside. Uncertainty = how much the view is heard.</p><p class="read" id="read"></p></div>`}
      ${settingsBlock(n)}`;
  }
  fill();
}
// Write every derived value into the inspector, leaving the box being typed in alone.
function fill() {
  const n = find(sel) || ROOT, act = document.activeElement;
  { const h = $("#insp .ih h2"); if (h && act?.dataset?.f === (n.kind === "asset" ? "t" : "name")) h.innerHTML = n.kind === "asset" ? `<code>${esc(n.t || "new asset")}</code>` : esc(n.name); }   // the heading follows the name as it is typed
  const set = (f, v, cls) => { const e = $(`#insp [data-f="${f}"]`); if (!e) return; if (e !== act) e.value = v ?? ""; if (cls !== undefined) { e.classList.toggle("typed", cls === "typed"); e.classList.toggle("derived", cls === "derived"); } };
  const chk = (f, v) => { const e = $(`#insp [data-f="${f}"]`); if (e) e.checked = !!v; };
  if (n !== ROOT) ["min", "max", "wpmin", "wpmax"].forEach((k) => { chk(`lim.${k}.on`, n.lim[k].on); set(`lim.${k}.v`, n.lim[k].v == null ? "" : fmtAbs(n.lim[k].v)); const e = $(`#insp [data-f="lim.${k}.v"]`); if (e) e.disabled = !n.lim[k].on; });
  if (n !== ROOT) { const [a, b] = n._share, p = parentOf(n), c = $("#cons"), bad = n._eff[0] > n._eff[1] + 1e-9;
    c.className = "cons" + (bad ? " bad" : "");
    c.textContent = bad ? `These limits leave no feasible weight: ${pct(n._eff[0], 1)} is needed but only ${pct(n._eff[1], 1)} is allowed.`
      : `Can take ${effText([a, b])} of ${p.name}, so ${effText(n._eff)} of the portfolio${a === b && a === 1 && p.children.length === 1 ? " (it is the only member)" : ""}.`; }
  if (n.kind === "asset") {
    set("t", n.t); set("tradeAs", n.tradeAs); set("h", n.h); set("eq", n.eq == null ? "" : fmtPts(n.eq)); chk("exIdio", n.exIdio);
    $("#close").innerHTML = priceOf(n) == null ? `<span style="color:var(--att)">no price yet; Refresh data fetches it</span>` : `${money(priceOf(n))} <span style="color:var(--mute)">at ${(byTicker[n.t]?.priceTime || HIST.fetched).replace("T", " ").slice(0, 16)}</span>`;
    const T = target(n), r = retOf(n);
    set("target", T == null ? "" : money(T), n.vt?.k === "price" ? "typed" : n.vt ? "derived" : ""); set("ret", r == null ? "" : fmtPts(r), n.vt?.k === "ret" ? "typed" : n.vt ? "derived" : "");
    for (const s of ["um", "up"]) { const u = n[s], d = dollars(n, s), g = sigma(n, s);
      set(s + "$", d == null ? (u?.k === "$" ? money(u.v) : "") : money(d), u?.k === "$" ? "typed" : u ? "derived" : "");
      set(s + "pts", g == null ? (u?.k === "pts" ? fmtAbs(u.v) : "") : fmtAbs(g), u?.k === "pts" ? "typed" : u ? "derived" : ""); }
    const m = modelOf(n), rd = $("#read");
    rd.className = "read" + (n.vt && !m ? " bad" : "");
    rd.innerHTML = !n.vt ? (byTicker[n.t]?.eq == null ? "No view, and no equilibrium return yet: type it above." : `No view: the model uses the equilibrium return, ${pct(n.eq ?? byTicker[n.t]?.eq, 1, true)}.`)
      : !m ? "Fill both uncertainty boxes. A view without them blocks the run."
      : Math.abs(m.sp - m.sm) < 5e-5 ? `The model uses <b>${pct(m.mean, 1, true)} ± ${pts(m.sd)} points</b>; the sides are equal, so the most likely value is the mean.`
      : `Most likely ${pct(m.m, 1, true)} → the model uses <b>${pct(m.mean, 1, true)} ± ${pts(m.sd)} points</b> (the split-normal mean and sd of a lopsided range).`;
    $("#curve").innerHTML = m ? curve(m, byTicker[n.t]?.eq, colorOf(n)) : "";
  } else {
    if (n === ROOT) { set("run.weeks", RUNSET.weeks); set("run.paths", RUNSET.paths.toLocaleString("en-US")); set("run.rf", fmtAbs(RUNSET.rf)); set("run.bands", RUNSET.bands || ""); }
    else { set("name", n.name); const v = n.view; set("gv.r", v.r == null ? "" : fmtPts(v.r)); set("gv.m", v.m == null ? "" : fmtAbs(v.m)); set("gv.p", v.p == null ? "" : fmtAbs(v.p));
      const gm = groupModel(n), eq = eqEW(n), rg = eqRange(n), rd = $("#read");
      rd.className = "read" + (v.r != null && !gm ? " bad" : "");
      rd.innerHTML = v.r != null && !gm ? "Fill both uncertainty boxes. A view without them blocks the run."
        : gm ? `The parent's search hears <b>${pct(gm.mean, 1, true)} ± ${pts(gm.sd)} points</b>, blended with ${n.name}'s implied return.`
        : eq == null ? `No view, and no equilibrium yet: none of ${esc(n.name)}'s members has prices until Refresh data.`
        : `No view. Before its first run, ${n.name} is shown at equal weights: equilibrium ${pct(eq, 1, true)}${rg && rg[1] - rg[0] > 5e-4 ? `, and its limits let the mix move that from ${pct(rg[0], 1, true)} to ${pct(rg[1], 1, true)}` : ""}. After a run this shows the implied return at the frozen mix.`; }
    chk("inherit", n.inherit);
    SETTINGS.forEach((S) => { const r = resolve(n, S.k), td = $(`#insp td[data-src="${S.k}"]`);
      set(`set.${S.k}`, S.opts ? r.v : r.v == null ? "" : S.pct ? (r.v < 0 ? MINUS : "") + fmtAbs(Math.abs(r.v)) : String(r.v));
      td.className = r.src === "set here" ? "here" : ""; td.innerHTML = r.src === "set here" ? `set here<button type="button" data-reset="${S.k}">reset</button>` : esc(r.src); });
  }
}
function curve(m, eq, c) {   // the split-normal density of the view, with the most likely value, the mean the model uses, and equilibrium
  const W = 372, H = 84, lo = Math.min(m.m - 3 * m.sm, eq ?? Infinity) - 0.02, hi = Math.max(m.m + 3 * m.sp, eq ?? -Infinity) + 0.02;
  const x = d3.scaleLinear().domain([lo, hi]).range([8, W - 8]), A = Math.sqrt(2 / Math.PI) / (m.sm + m.sp);
  const f = (v) => A * Math.exp(-((v - m.m) ** 2) / (2 * (v < m.m ? m.sm : m.sp) ** 2)), y = d3.scaleLinear().domain([0, A]).range([H - 22, 10]);
  const xs = d3.range(0, 161).map((i) => lo + (hi - lo) * i / 160);
  const area = d3.area().x((v) => x(v)).y0(H - 22).y1((v) => y(f(v)))(xs);
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribution of the view"><path d="${area}" fill="color-mix(in oklab, ${c} 22%, transparent)" stroke="${c}" stroke-width="1.5"/>`;
  x.ticks(5).forEach((t) => s += `<text class="ax" x="${x(t)}" y="${H - 6}" text-anchor="middle">${t > 0 ? "+" : t < 0 ? MINUS : ""}${Math.abs(Math.round(t * 100))}</text>`);
  s += `<line x1="8" x2="${W - 8}" y1="${H - 22}" y2="${H - 22}" stroke="var(--frame-2)"/>`;
  if (eq != null) s += `<line x1="${x(eq)}" x2="${x(eq)}" y1="${H - 30}" y2="${H - 14}" stroke="var(--ink-2)" stroke-width="1.5"/>`;
  s += `<line x1="${x(m.m)}" x2="${x(m.m)}" y1="${y(A)}" y2="${H - 22}" stroke="${c}" stroke-width="2"/><circle cx="${x(m.mean)}" cy="${H - 22}" r="4.5" fill="${c}" stroke="var(--panel)" stroke-width="1.5"/></svg>`;
  return s + `<div class="legend"><span><i style="width:2px;height:11px;background:${c}"></i>most likely</span><span><i style="width:8px;height:8px;border-radius:50%;background:${c}"></i>model uses</span>${eq != null ? `<span><i style="width:1.5px;height:11px;background:var(--ink-2)"></i>equilibrium</span>` : ""}<span>% a year</span></div>`;
}

// ---- editing ---------------------------------------------------------------------------------------
let typingSnap = false;
document.addEventListener("focusin", (e) => { if (e.target.closest("#insp") && e.target.matches("input, select")) typingSnap = false; });
function edit(el) {
  const n = (el.dataset.id && find(el.dataset.id)) || find(sel) || ROOT, f = el.dataset.f, raw = el.type === "checkbox" ? el.checked : el.value, v = parseNum(raw);
  if (!typingSnap) { snapshot(); typingSnap = true; }
  if (f === "t") { n.t = String(raw).trim().toUpperCase(); if (n.t) { const a = addTicker(n.t); if (n.eq == null) n.eq = a.eq; } }
  else if (f === "eq") { n.eq = v == null ? null : v / 100; if (byTicker[n.t]) byTicker[n.t].eq = n.eq; }
  else if (f === "tradeAs") n.tradeAs = String(raw).trim().toUpperCase();
  else if (f === "exIdio") n.exIdio = !!raw;
  else if (f === "name") n.name = String(raw);
  else if (f === "h") { if (v > 0) n.h = v; }
  else if (f === "target") n.vt = v == null ? null : { k: "price", v };
  else if (f === "ret") n.vt = v == null ? null : { k: "ret", v: v / 100 };
  else if (/^u[mp](\$|pts)$/.test(f)) { const s = f.slice(0, 2); n[s] = v == null ? null : f.endsWith("$") ? { k: "$", v: Math.abs(v) } : { k: "pts", v: Math.abs(v) / 100 }; }
  else if (f.startsWith("lim.")) { const [, k, part] = f.split("."); if (part === "on") n.lim[k].on = raw; else n.lim[k].v = v == null ? null : v / 100; }
  else if (f.startsWith("gv.")) { const k = f.slice(3); n.view[k] = v == null ? null : k === "r" ? v / 100 : Math.abs(v) / 100; }
  else if (f === "inherit") n.inherit = raw;
  else if (f.startsWith("set.")) { const k = f.slice(4), S = SETTINGS.find((x) => x.k === k);
    if (S.opts) n.set[k] = raw; else if (v == null) { if (S.blankOff) n.set[k] = null; else delete n.set[k]; } else n.set[k] = S.pct ? v / 100 : v; }
  else if (f === "run.weeks") { if (v > 0) RUNSET.weeks = v; } else if (f === "run.paths") { if (v > 0) { RUNSET.paths = Math.round(v); RUNSET.pathsSet = true; } } else if (f === "run.rf") { if (v != null) { RUNSET.rf = v / 100; RUNSET.rfSet = true; } } else if (f === "run.bands") { RUNSET.bands = v != null && v >= 2 ? Math.round(v) : null; }
  render(false);
}
document.addEventListener("input", (e) => { if (e.target.closest("#insp, #canvas") && e.target.dataset.f && e.target.type !== "checkbox") edit(e.target); });
document.addEventListener("change", (e) => { const el = e.target; if (render.busy || !el.closest("#insp, #canvas") || !el.dataset.f) return;
  if (el.closest("#canvas")) { typingSnap = false; if (el.type === "checkbox") edit(el); else render(false); return; }
  if (el.type === "checkbox" || el.tagName === "SELECT") { edit(el); if (el.dataset.f.endsWith(".on") && el.checked) $(`#insp [data-f="${el.dataset.f.replace(".on", ".v")}"]`)?.focus(); }
  else { typingSnap = false; if (el.dataset.f === "t" || el.dataset.f === "name") inspector(); fill(); } });
document.addEventListener("click", (e) => { const r = e.target.closest("[data-reset]"); if (!r) return; const n = find(sel) || ROOT; snapshot(); delete n.set[r.dataset.reset]; render(false); });

// ---- structure: select, move, add, remove ----------------------------------------------------------
function select(id) { sel = id; render(true); }
function moveNode(n, into, at) {   // into: a group; at: index among its children (null = append)
  if (n === ROOT || into.kind !== "group" || isAncestor(n, into)) return false;
  const from = parentOf(n), i0 = from.children.indexOf(n); from.children.splice(i0, 1);
  let i = at == null ? into.children.length : at; if (from === into && at != null && i0 < at) i--;
  into.children.splice(Math.max(0, Math.min(i, into.children.length)), 0, n); into.open = true; return true;
}
function addNode(kind) {
  const cur = find(sel) || ROOT, into = cur.kind === "group" ? cur : parentOf(cur), at = cur.kind === "group" ? null : into.children.indexOf(cur) + 1;
  snapshot(); const n = kind === "group" ? G("New subportfolio", []) : A("");
  into.children.splice(at == null ? into.children.length : at, 0, n); into.open = true; sel = n.id; render(true);
  const f = $(`#insp [data-f="${kind === "group" ? "name" : "t"}"]`); f?.focus(); f?.select?.();
}
function removeNode(n) { if (n === ROOT) return; const p = parentOf(n), i = p.children.indexOf(n); snapshot(); p.children.splice(i, 1); sel = (p.children[i] || p.children[i - 1] || p).id; render(true); }
$("#addg").addEventListener("click", () => addNode("group"));
$("#adda").addEventListener("click", () => addNode("asset"));
$("#undo").addEventListener("click", restore);
$("#foldall").addEventListener("click", () => { const groups = []; const w = (n) => { if (n.kind === "group") { if (n !== ROOT) groups.push(n); n.children.forEach(w); } }; w(ROOT);
  const close = groups.some((g) => g.open); groups.forEach((g) => (g.open = !close)); if (close && find(sel) && find(sel) !== ROOT && !groups.includes(find(sel))) sel = topOf(find(sel)).id; render(true); });
$("#review").addEventListener("click", () => { $("#note").textContent = "The pre-run review is the next screen: every limit, setting and source, each asset's weight range, and the Run button."; });

// clicks on the tree: a row or a group node selects; a second click on a group folds it
$("#canvas").addEventListener("click", (e) => {
  if (dragged) { dragged = false; return; }
  const h = e.target.closest("[data-id], [data-gid]"); if (!h) return; const id = h.dataset.id || h.dataset.gid, n = find(id);
  if (e.target.closest("input, select, button")) { if (sel !== id) { sel = id; markSel(); inspector(); } return; }
  if (n.kind === "group" && id === sel && n !== ROOT && (h.dataset.gid || !n.open)) { n.open = !n.open; render(true); return; }
  select(id); $("#canvas").focus({ preventScroll: true });
});
// drag a row or a group node: onto a group node = into it; onto a row = before or after it (the line's indent shows the level)
$("#canvas").addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || e.target.closest("input, select, button, .nodrag")) return; const h = e.target.closest("[data-id], [data-gid]"); if (!h) return;
  const id = h.dataset.id || h.dataset.gid; if (id === ROOT.id) return; drag = { id, x: e.clientX, y: e.clientY }; e.preventDefault(); $("#canvas").focus({ preventScroll: true });
});
document.addEventListener("pointermove", (e) => {
  if (!drag) return;
  if (!drag.on && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
  const n = find(drag.id);
  if (!drag.on) { drag.on = true; startDrag(e); drag.ghost = Object.assign(document.createElement("div"), { className: "ghost", textContent: label(n) }); document.body.appendChild(drag.ghost); }
  Object.assign(drag.ghost.style, { left: e.clientX + 12 + "px", top: e.clientY + 8 + "px" });
  const host = $("#canvas"), r = host.getBoundingClientRect(), px = e.clientX - r.left + host.scrollLeft, py = e.clientY - r.top + host.scrollTop;
  drag.into = null; drag.ins = null; drag.to = null; Object.assign(drag, dropAt(px, py, n) || {});
  drawTree();
});
document.addEventListener("pointerup", () => {
  if (!drag) return; const d = drag; drag = null; d.ghost?.remove(); endDrag();
  if (!d.on) return; dragged = true; setTimeout(() => (dragged = false), 0);
  if (d.to) { const json = JSON.stringify({ ROOT, RUNSET, sel }); if (moveNode(find(d.id), d.to.into, d.to.at)) { undoStack.push(json); sel = d.id; } }
  render(true);
});
// keyboard on the tree: outliner semantics
$("#canvas").addEventListener("keydown", (e) => {
  if (e.target.closest("input, select")) return;   // a cell in the tree keeps its own keys
  const n = find(sel) || ROOT, vis = visibleOrder(), i = vis.indexOf(n), p = parentOf(n);
  const k = e.key; let done = true;
  if (k === "Escape" && drag) { drag.ghost?.remove(); drag = null; endDrag(); render(true); }
  else if (k === "ArrowDown" && e.altKey) { if (p && p.children.indexOf(n) < p.children.length - 1) { snapshot(); moveNode(n, p, p.children.indexOf(n) + 2); render(true); } }
  else if (k === "ArrowUp" && e.altKey) { if (p && p.children.indexOf(n) > 0) { snapshot(); moveNode(n, p, p.children.indexOf(n) - 1); render(true); } }
  else if (k === "ArrowDown") { if (vis[i + 1]) select(vis[i + 1].id); }
  else if (k === "ArrowUp") { if (i > 0) select(vis[i - 1].id); }
  else if (k === "ArrowLeft") { if (n.kind === "group" && n.open && n !== ROOT && n.children.length) { n.open = false; render(true); } else if (p) select(p.id); }
  else if (k === "ArrowRight") { if (n.kind === "group" && !n.open) { n.open = true; render(true); } else if (n.kind === "group" && n.children[0]) select(n.children[0].id); }
  else if (k === "Tab" && !e.shiftKey) { const prev = p?.children[p.children.indexOf(n) - 1]; if (prev?.kind === "group") { snapshot(); moveNode(n, prev, null); render(true); } }
  else if (k === "Tab" && e.shiftKey) { const gp = p && parentOf(p); if (gp) { snapshot(); moveNode(n, gp, gp.children.indexOf(p) + 1); render(true); } }
  else if (k === "Delete" || k === "Backspace") removeNode(n);
  else if (k === " " && n.kind === "group" && n !== ROOT) { n.open = !n.open; render(true); }
  else if (k === "Enter") ($(n.kind === "asset" && n.t ? '#insp [data-f="target"]' : "#insp input.box:not([disabled])"))?.focus();
  else if ((k === "z" || k === "Z") && (e.ctrlKey || e.metaKey)) restore();
  else done = false;
  if (done) e.preventDefault();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drag) { drag.ghost?.remove(); drag = null; endDrag(); render(true); } });
$("#insp").addEventListener("keydown", (e) => {
  if (!e.altKey || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return; const f = e.target.dataset?.f; if (!f) return;
  const cur = find(sel); if (!cur) return; const vis = visibleOrder().filter((n) => n.kind === cur.kind && n !== ROOT), i = vis.indexOf(cur), next = vis[i + (e.key === "ArrowDown" ? 1 : -1)];
  e.preventDefault(); if (!next) return; e.target.dispatchEvent(new Event("change", { bubbles: true })); select(next.id);
  const el = $(`#insp [data-f="${f}"]`); el?.focus(); el?.select?.();
});
// paste rows from Excel into the tree: ticker, target $, − $, + $ (later columns optional)
document.addEventListener("paste", (e) => {
  if (e.target.closest?.("input, select")) return; const text = e.clipboardData?.getData("text") || ""; const rows = text.trim().split(/\r?\n/).map((l) => l.split(/\t|,/).map((c) => c.trim())).filter((r) => r[0]);
  if (!rows.length) return; e.preventDefault(); snapshot();
  const cur = find(sel) || ROOT, into = cur.kind === "group" ? cur : parentOf(cur); let last = null;
  const all = []; const w = (n) => { if (n.kind === "asset") all.push(n); else n.children.forEach(w); }; w(ROOT);
  rows.forEach(([t, T, m, p]) => { t = t.toUpperCase(); if (!/^[A-Z0-9.=^-]{1,12}$/.test(t)) return;
    let n = all.find((a) => a.t === t); if (!n) { n = A(t); n.vt = n.um = n.up = null; into.children.push(n); into.open = true; }
    const v = parseNum(T), vm = parseNum(m), vp = parseNum(p);
    if (v != null) n.vt = { k: "price", v }; if (vm != null) n.um = { k: "$", v: Math.abs(vm) }; if (vp != null) n.up = { k: "$", v: Math.abs(vp) }; last = n; });
  if (last) sel = last.id; render(true); $("#note").textContent = `Pasted ${rows.length} row${rows.length === 1 ? "" : "s"} into ${into.name}.`;
});

function markSel() { document.querySelectorAll("#canvas .on[data-id]").forEach((x) => x.classList.remove("on")); document.querySelectorAll(`#canvas [data-id="${sel}"].row, #canvas [data-id="${sel}"].sel-able`).forEach((x) => x.classList.add("on")); }
function render(full) {
  if (render.busy) return; render.busy = true;   // redrawing removes a focused cell, whose blur fires change: never re-enter
  try { renderNow(full); } finally { render.busy = false; }
}
function renderNow(full) {
  index(); effective();
  const a = document.activeElement, keep = a?.closest?.("#canvas") && a.dataset.f ? { id: a.dataset.id, f: a.dataset.f, v: a.value, s: a.selectionStart } : null;
  // the checks strip first: it changes the canvas height, and the tree is measured from that height
  const c = checks(), blocks = c.filter((x) => x.b);
  $("#checks").hidden = !blocks.length;   // notes alone do not earn the space; the one-member note also shows in the editor
  $("#checks").innerHTML = `<h2>Before the run</h2><ul>${c.map((x) => `<li data-cid="${x.id}"><span class="${x.b ? "b" : "n"}">${x.b ? "Blocks" : "Note"}</span>${esc(x.text)}</li>`).join("")}</ul>`;
  drawTree();
  if (keep) { const el = $(`#canvas [data-id="${keep.id}"][data-f="${keep.f}"]`); if (el) { el.value = keep.v; el.focus({ preventScroll: true }); try { el.setSelectionRange(keep.s, keep.s); } catch {} } }
  $("#state").textContent = blocks.length ? `${blocks.length} thing${blocks.length === 1 ? "" : "s"} block${blocks.length === 1 ? "s" : ""} the run` : "Ready for review";
  $("#state").className = "state" + (blocks.length ? " bad" : "");
  $("#review").disabled = !!blocks.length; $("#review").title = blocks.length ? "Fix what is listed under Before the run first" : "";
  $("#undo").disabled = !undoStack.length;
  if (full) inspector(); else fill();
  scheduleSave();
}
// ---- saving: every change goes to the library (versioned: a save from a stale tab is refused) -----------
let SAVED = JSON.stringify(toPortfolio()), saveTimer = null;
function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 700); }
let DELETED = false;
async function saveNow() {
  if (DELETED) return;
  const body = toPortfolio(), text = JSON.stringify(body);
  if (text === SAVED) return;
  try {
    const r = await fetch(`/api/portfolios/${PF.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: text });
    const d = await r.json();
    if (r.status === 409) { $("#state").textContent = "Changed in another tab: reload to continue"; $("#state").className = "state bad"; return; }
    if (!r.ok) throw new Error(d.detail || r.status);
    PF.version = d.version; SAVED = JSON.stringify(toPortfolio());
    if (ROOT.children.some(function miss(c) { return c.kind === "asset" ? c.t && byTicker[c.t]?.price == null : c.children.some(miss); })) {
      $("#note").textContent = "Saved. New tickers wait for Refresh data to fetch their prices."; }
  } catch (e) { $("#state").textContent = `Not saved: ${e.message}`; $("#state").className = "state bad"; }
}
$("#checks").addEventListener("click", (e) => { const li = e.target.closest("[data-cid]"); if (!li) return; const n = find(li.dataset.cid); for (let p = parentOf(n); p; p = parentOf(p)) p.open = true; select(n.id); $("#canvas").focus({ preventScroll: true }); });
new ResizeObserver(() => { if (!render.busy && !drag?.on) drawTree(); }).observe($("#canvas"));   // any change of the canvas size redraws it

$("#meta").textContent = `${PF.name}: prices of ${HIST.fetched}${RUN.id ? `; last run ${RUN.snapshot}` : "; no run yet"}.`;
$("#note").textContent = PROTO_NOTE + " Changes save as you edit.";
index(); sel = ROOT.id;
render(true);
