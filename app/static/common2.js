// Shared data and model for the screens, now on live data (live.js).
// Sources:
//   reference run: benchmarks/reference/inputs.json + answer.json (v4.1, A100, 2026-10-27)
//   inputs: portfolio_data.csv
//   history: hist.js (Yahoo Finance weekly closes, 5y, fetched 2026-10-28)
//   jump betas: surprise-day crash/rally betas from the #9 jump-DB study (daily, GARCH residual beyond ±3)
// Illustrative: the grouping into sub-portfolios and the limits (the reference run was flat).

// Live data (live.js loads it from the API): the latest finished run, betas from the jump database, today's
// prices and the portfolio's own inputs. Before the first run, the run figures are blank, never invented.
const LR = LIVE.last_run;
const RUN = {
  id: LR ? LR.id : null, date: LR ? (LR.ended || "").slice(0, 10) : "no run yet", snapshot: LR ? (LR.ended || "").replace("T", " ").slice(0, 16) : "",
  hardware: LR ? (LR.machine === "a100" ? `Colab, ${LR.gpu}` : LR.gpu || "this computer") : "", generations: null, evaluations: null,
  paths: LR ? `${LR.bank.toLocaleString("en-US")}-path bank` : "", horizonWeeks: (LIVE.portfolio.run && LIVE.portfolio.run.horizon_weeks) || 12,
  metrics: LR ? { ret: LR.metrics.er_12w, vol: LR.metrics.vol_12w, cvar: LR.metrics.cvar, cdar: LR.metrics.cdar } : { ret: null, vol: null, cvar: null, cdar: null },
  objective: LR ? LR.objective : null,
};

const BETAS = Object.fromEntries(Object.entries(LIVE.betas || {}).map(([t, b]) => [t, { normal: b.normal, crash: b.crash_beta, crashN: b.crash_days,
  rally: b.rally_beta, rallyN: b.rally_days, crashSrc: b.crash_source, rallySrc: b.rally_source, cojump: b.cojump, cojumpSrc: b.cojump_source }]));
// The jump-DB rule: a beta needs at least 10 surprise days to be estimated directly; below that it falls back.
const DIRECT_MIN = 10;

const PF = LIVE.portfolio;
const TICKERS = (() => { const out = []; const w = (n) => { if (n.kind === "asset") out.push(n.ticker); else n.children.forEach(w); }; w(PF.tree); return out; })();
const ASSETS = TICKERS.map((t) => {
  const a = PF.assets[t] || {}, v = a.view, price = LIVE.prices[t] ? LIVE.prices[t].price : null;
  return { t, price, priceTime: LIVE.prices[t] ? LIVE.prices[t].time : null, eq: a.equilibrium ?? null,
    view: v && v.form === "return" ? v.value : null, sdMinus: v ? v.minus : null, sdPlus: v ? v.plus : null,
    w: LR && LR.weights[t] != null ? LR.weights[t] : 1 / TICKERS.length, typed: v ? (v.form === "price" ? "price" : "return") : null,
    beta: BETAS[t], hist: (typeof HIST !== "undefined" ? HIST.series[t] : null) };
});
const byTicker = Object.fromEntries(ASSETS.map((a) => [a.t, a]));
const addTicker = (t) => {   // a ticker typed into the builder: a card that waits for Refresh data until it has a price
  if (byTicker[t]) return byTicker[t];
  const p = LIVE.prices[t]; const a = { t, price: p ? p.price : null, priceTime: p ? p.time : null, eq: null, view: null, sdMinus: null, sdPlus: null,
    w: 0, typed: null, beta: BETAS[t], hist: HIST.series[t] || null };
  ASSETS.push(a); byTicker[t] = a; return a; };
// hist.js stores drawdowns to 4 decimals, which turns MNTS's -99.996% into -100%: recompute the worst fall from closes.
ASSETS.forEach((a) => { if (!a.hist) return; let peak = -Infinity, worst = 0; for (const c of a.hist.close) { peak = Math.max(peak, c); worst = Math.min(worst, c / peak - 1); } a.hist.maxdd = worst; });

// The tree is editable: the builder (builder-core.js) owns it; this older flat list is kept empty.
const TREE = [];
const ORIGINAL = JSON.stringify(TREE.map((g) => g.children));
const groupOf = (t) => TREE.find((g) => g.children.includes(t));
const groupWeight = (g) => g.children.reduce((s, t) => s + byTicker[t].w, 0);
const shareInGroup = (t) => byTicker[t].w / groupWeight(groupOf(t));
const groupEq = (g) => g.children.length ? g.children.reduce((s, t) => s + byTicker[t].w * byTicker[t].eq, 0) / groupWeight(g) : null;
function moveAsset(t, toName, index) {
  const from = groupOf(t), to = TREE.find((g) => g.name === toName);
  if (!to) return false;
  from.children.splice(from.children.indexOf(t), 1);
  const i = index == null ? to.children.length : Math.max(0, Math.min(index, to.children.length));
  to.children.splice(i, 0, t);
  return true;
}
const treeMoved = () => JSON.stringify(TREE.map((g) => g.children)) !== ORIGINAL;
const VIEW_EDITS = new Set();
function changeCount() {
  const orig = JSON.parse(ORIGINAL); let n = VIEW_EDITS.size;
  ASSETS.forEach((a) => { const gi = orig.findIndex((c) => c.includes(a.t)); if (!TREE[gi].children.includes(a.t)) n++; });
  return n;
}
function dirtyText() {
  const n = changeCount();
  return n ? `${n} edit${n > 1 ? "s" : ""} since the reference run (group totals re-summed, not re-optimized)` : "";
}

const corr = (a, b) => { const T = HIST.tickers; return HIST.corr[T.indexOf(a)][T.indexOf(b)]; };
const overlap = (a, b) => { const T = HIST.tickers; return HIST.overlap[T.indexOf(a)][T.indexOf(b)]; };

// Formatting: true minus, explicit + where a sign means something, one precision per kind of number.
const MINUS = "−";
function pct(x, dp = 1, signed = false) {
  if (x == null || Number.isNaN(x)) return "—";
  const s = Math.abs(x * 100).toFixed(dp);
  if (x < 0 && Number(s) !== 0) return MINUS + s + "%";
  return (signed && x > 0 ? "+" : "") + s + "%";
}
const pts = (x, dp = 1) => (x == null ? "" : (x < 0 ? MINUS : "") + Math.abs(x * 100).toFixed(dp));
const num = (x, dp = 2) => (x == null ? "—" : (x < 0 ? MINUS : "") + Math.abs(x).toFixed(dp));
const money = (x) => (x == null ? "—" : x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 0 }) : x.toFixed(2));
const targetFromReturn = (a, r) => a.price * (1 + r);          // 12-month horizon
const returnFromTarget = (a, p) => p / a.price - 1;
const annualised = (r) => Math.pow(1 + r, 52 / RUN.horizonWeeks) - 1;
// A fall of 99.6% must not print as "100%": keep two decimals once it is that deep.
const ddPct = (x) => pct(x, x <= -0.9995 ? 3 : x <= -0.995 ? 2 : 1);
const betaSource = (n) => (n >= DIRECT_MIN ? "direct" : "fallback");
const RISK_LINE = () => `expected return ${pct(RUN.metrics.ret, 2, true)} over 12 weeks (${pct(annualised(RUN.metrics.ret), 1, true)} compounded to a year), volatility ${pct(RUN.metrics.vol, 2)}, CVaR 5% ${pct(RUN.metrics.cvar, 2)}, CDaR 5% ${pct(RUN.metrics.cdar, 2)}; search objective ${num(RUN.objective, 5)}, lower is better.`;

function setView(t, v, typed) { const a = byTicker[t]; a.view = v; a.typed = v == null ? null : typed; VIEW_EDITS.add(t); }

const PROTO_NOTE = `${PF.name}. ${LR ? `Weights and risk: run ${RUN.snapshot}, ${RUN.hardware}.` : "No run yet: weights are equal until the first run."} ` +
  `History: Yahoo weekly, 5y, data of ${typeof HIST !== "undefined" ? HIST.fetched : "n/a"}. Jump betas: jump database ${LIVE.jump_version ? LIVE.jump_version.version : "none"}.`;
const limitText = (g) => g.max != null ? `max ${pct(g.max, 0)}` : g.min != null ? `min ${pct(g.min, 0)}` : "no limit";
// Against the reference weights re-added after a move: "breach" when outside, "near" within 2 points of a bound.
function limitState(g) {
  const w = groupWeight(g);
  if ((g.max != null && w > g.max + 1e-9) || (g.min != null && w < g.min - 1e-9)) return "breach";
  if ((g.max != null && g.max - w < 0.02) || (g.min != null && w - g.min < 0.02)) return "near";
  return "ok";
}

// Drag hygiene shared by every prototype: no text selection while dragging, pointer capture on the source.
function startDrag(e) {
  document.body.classList.add("dragging"); window.getSelection()?.removeAllRanges();
  try { if (e && e.pointerId != null) e.target.setPointerCapture(e.pointerId); } catch { /* not every drag source can capture */ }
}
function endDrag() { document.body.classList.remove("dragging"); window.getSelection()?.removeAllRanges(); }
