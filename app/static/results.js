// ---- Run results: five views over one real run (and a second run for Compare). Every number here comes from
// results-data.js, written by benchmarks/prototypes/tree_run.py on the laptop GPU; nothing is computed for show.
const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const RUNS = DATA.runs, R0 = RUNS[0], R1 = RUNS[1];
// group colours: the builder's fixed list, one slot per top-level subportfolio in order
const PALETTE = ["#e0af68", "#bb9af7", "#9ece6a", "#f7768e", "#7dcfff", "#ff9e64", "#73daca", "#7aa2f7"];
const idOf = (r) => [...r.path, r.name].join("/");
const TOPS = R0.rows.filter((r) => r.path.length === 1).map((r) => r.name);
const colorOf = (r) => (r.path.length === 0 ? "var(--ink-2)" : PALETTE[TOPS.indexOf(r.path.length === 1 ? r.name : r.path[1])] ?? "var(--mute)");
const byId = (run) => new Map(run.rows.map((r) => [idOf(r), r]));
const M0 = byId(R0), M1 = byId(R1);
const kids = (run, r) => run.rows.filter((x) => x.path.length === r.path.length + 1 && idOf({ path: x.path.slice(0, -1), name: x.path[x.path.length - 1] }) === idOf(r));
let sel = "Portfolio", view = "results";
const FOLD = new Set(), OPEN = new Set();
const p1 = (x) => pct(x, 1), p2 = (x) => pct(x, 2), sgn = (x, dp = 1) => (x > 0 ? "+" : x < 0 ? MINUS : "") + Math.abs(x * 100).toFixed(dp);
const tip = (e, html) => { const t = $("#tip"); if (!html) { t.style.display = "none"; return; } t.innerHTML = html; t.style.display = "block";
  t.style.left = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8) + "px"; t.style.top = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8) + "px"; };
const size = (id) => { const el = $(id); return [el.clientWidth, el.clientHeight]; };
const svg = (w, h, inner) => `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${inner}</svg>`;
const when = (iso) => iso.replace("T", " ").slice(0, 16);
{ const T = DATA.thisRun; $("#meta").textContent = DATA.live ? `${T.label}: queued ${when(T.finished)}` : `${T.label}. ${DATA.gpu}, finished ${when(T.finished)}; market data of ${when(DATA.inputs_created)}${DATA.compareBase ? `; compared with the run of ${when(R0.finished)}` : ""}`; }
$("#note").textContent = DATA.live ? "The run is going: Progress follows it live. Results open when it finishes."
  : `${DATA.config.bank.toLocaleString("en-US")}-path bank on ${R0.machine === "a100" ? `the ${machName(DATA.thisRun.record)}` : "this computer"}, searches on ${DATA.config.train.toLocaleString("en-US")} of it, every figure on the other ${R0.validation_paths.toLocaleString("en-US")} paths.${R0.rows.some((r) => r.band) ? "" : " No sensitivity band was run."}`;

// ---- Results: the tree table ------------------------------------------------------------------------
function visible(run) { const out = []; let skip = null;
  run.rows.forEach((r) => { const id = idOf(r); if (skip && id.startsWith(skip + "/")) return; skip = null; out.push(r); if (r.kind === "group" && FOLD.has(id)) skip = id; }); return out; }
function bindText(run, r) {   // the limit this row sits at, from its parent's search
  const parent = run.rows.find((x) => idOf(x) === r.path.join("/")); const b = parent?.search?.binding?.find((x) => x.child === r.name);
  return b ? `at its ${p01(b.limit)} ${b.at}` : "";
}
const p01 = (x) => (Math.abs(x * 100 - Math.round(x * 100)) < 0.05 ? pct(x, 0) : pct(x, 1));
function tree() {
  const rows = visible(R0), maxShare = 1;
  const body = rows.map((r) => { const id = idOf(r), c = colorOf(r), m = r.metrics, g = r.kind === "group", d = r.path.length, b = bindText(R0, r), S = r.search;
    const name = g ? `<button class="fold" type="button" data-fold="${esc(id)}" aria-expanded="${!FOLD.has(id)}" aria-label="Fold ${esc(r.name)}">${FOLD.has(id) ? "▸" : "▾"}</button>${esc(r.name)}` : `<span class="tk">${esc(r.name)}</span>`;
    const det = g && S && S.generations ? `<button class="srch" type="button" data-det="${esc(id)}" aria-expanded="${OPEN.has(id)}" title="Show its search">${S.generations} gen ${OPEN.has(id) ? "▾" : "▸"}</button>` : "";
    let s = `<tr data-r="${esc(id)}" class="${g ? "g d" + d : ""}${id === sel ? " on" : ""}"><td class="l nm" style="--c:${c};padding-left:${8 + 14 * d}px">${name}${det}${b ? `<span class="bind">${b}</span>` : ""}</td>`
      + `<td><span class="sh">${d ? `<i class="bar" style="--c:${c};width:${Math.max(1, 34 * r.share / maxShare)}px;opacity:${g ? 0.7 : 1}"></i>` : ""}${d ? p1(r.share) : ""}</span></td><td>${p2(r.effective)}</td>`
      + `<td>${pct(m.er_12w, 2, true)}</td><td>${p1(m.vol_12w)}</td><td>${p1(m.cvar)}</td><td>${p1(m.cdar)}</td><td>${m.upi == null ? "—" : num(m.upi, 3)}</td></tr>`;
    if (OPEN.has(id) && S) s += `<tr class="det"><td colspan="8">${searchLine(r)}</td></tr>`;
    return s; }).join("");
  $("#p-tree").innerHTML = `<table><thead><tr><th class="l">Part</th><th>Share<small>of parent</small></th><th>Effective<small>of portfolio</small></th><th>Expected<small>return</small></th><th>Vol</th><th>CVaR<small>5%</small></th><th>CDaR<small>5%</small></th><th>UPI</th></tr></thead><tbody>${body}</tbody></table>`;
}
function searchLine(r) {
  const S = r.search, h = S.history, w = 220, ht = 34, x = d3.scaleLinear().domain([1, Math.max(2, h.length)]).range([2, w - 2]), y = d3.scaleLinear().domain(d3.extent(h)).range([ht - 3, 3]);
  const path = h.length > 1 ? d3.line().x((v, i) => x(i + 1)).y((v) => y(v))(h) : "";
  return `<span style="display:inline-flex;gap:14px;align-items:center">${svg(w, ht, `<path d="${path}" fill="none" stroke="${colorOf(r)}" stroke-width="1.5"/>`)}<span>${S.generations} generations, stopped by the ${S.stopped === "window" ? "5-generation window" : S.stopped}; ${S.s_per_gen} s a generation, ${S.wall_s} s in all. Best score ${num(-h[h.length - 1], 4)} (UPI less penalties).</span></span>`;
}

// ---- Results: charts for the selected row --------------------------------------------------------------
const QS = ["0.05", "0.25", "0.5", "0.75", "0.95"];
function fanSvg(id, runs, W, H) {
  const m = { l: 44, r: 52, t: 10, b: 24 }, all = runs.flatMap(({ r }) => QS.flatMap((q) => r.fan[q]));
  const x = d3.scaleLinear().domain([0, 12]).range([m.l, W - m.r]), y = d3.scaleLinear().domain(d3.extent(all)).nice().range([H - m.b, m.t]);
  let s = "";
  y.ticks(5).forEach((t) => s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="${Math.abs(t - 1) < 1e-9 ? "var(--frame-2)" : "var(--frame)"}"/><text x="${m.l - 5}" y="${y(t) + 3.5}" text-anchor="end">${sgn(t - 1, 0)}%</text>`);
  [0, 4, 8, 12].forEach((t) => s += `<text x="${x(t)}" y="${H - 7}" text-anchor="middle">${t === 0 ? "now" : t + " wk"}</text>`);
  runs.forEach(({ r, c, dash }, k) => { const F = (q) => r.fan[q], band = (a, b, op) => `<path d="${d3.area().x((v, i) => x(i)).y0((v, i) => y(F(a)[i])).y1((v, i) => y(F(b)[i]))(F(a))}" fill="${c}" fill-opacity="${op}"${dash ? ` stroke="${c}" stroke-dasharray="3 3" stroke-opacity="0.7"` : ""}/>`;
    s += band("0.05", "0.95", dash ? 0.06 : 0.16) + band("0.25", "0.75", dash ? 0.1 : 0.3) + `<path d="${d3.line().x((v, i) => x(i)).y((v) => y(v))(F("0.5"))}" fill="none" stroke="${c}" stroke-width="2"${dash ? ' stroke-dasharray="5 3"' : ""}/>`;
    if (k === 0) QS.forEach((q) => { const v = F(q)[12]; s += `<text x="${W - m.r + 5}" y="${y(v) + 3.5}" style="fill:${q === "0.5" ? "var(--ink)" : "var(--ink-2)"}">${sgn(v - 1)}%</text>`; }); });
  return svg(W, H, s);
}
function histSvg(h, marks, c, W, H, unitNeg) {
  const m = { l: 12, r: 12, t: 16, b: 24 }, E = h.edges, x = d3.scaleLinear().domain([E[0], E[E.length - 1]]).range([m.l, W - m.r]), y = d3.scaleLinear().domain([0, d3.max(h.counts)]).range([H - m.b, m.t]);
  let s = "";
  h.counts.forEach((n, i) => { const x0 = x(E[i]), x1 = x(E[i + 1]), tail = marks.tail != null && E[i + 1] <= marks.tail + 1e-12;
    s += `<rect x="${x0 + 0.5}" y="${y(n)}" width="${Math.max(0.5, x1 - x0 - 1)}" height="${H - m.b - y(n)}" fill="${tail ? "var(--down)" : c}" fill-opacity="${tail ? 0.75 : 0.55}"/>`; });
  x.ticks(6).forEach((t) => s += `<text x="${x(t)}" y="${H - 7}" text-anchor="middle">${sgn(t, 0)}%</text>`);
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--frame-2)"/>`;
  marks.lines.forEach(({ v, label, k }, i) => { const xv = x(v), right = xv < W * 0.62;   // each label on its own row, so none collide
    s += `<line x1="${xv}" x2="${xv}" y1="${m.t + 13 * i - 2}" y2="${H - m.b}" stroke="var(--ink)" stroke-width="1.5"${k === "dash" ? ' stroke-dasharray="3 2"' : ""}/><text x="${xv + (right ? 5 : -5)}" y="${m.t + 6 + 13 * i}" text-anchor="${right ? "start" : "end"}" style="fill:var(--ink);paint-order:stroke;stroke:var(--panel);stroke-width:3px">${label} ${sgn(v)}%</text>`; });
  return svg(W, H, s);
}
function charts() {
  const r = M0.get(sel), c = colorOf(r) === "var(--ink-2)" ? "#c0caf5" : colorOf(r), m = r.metrics;
  $$("[data-for]").forEach((e) => (e.textContent = r.name));
  let [w, h] = size("#p-fan"); $("#p-fan").innerHTML = fanSvg("fan", [{ r, c }], w, h);
  [w, h] = size("#p-ret"); $("#p-ret").innerHTML = histSvg(r.ret_hist, { tail: m.var, lines: [{ v: m.sim_mean_12w, label: "mean" }, { v: m.var, label: "VaR" }, { v: m.cvar, label: "CVaR", k: "dash" }] }, c, w, h);
  [w, h] = size("#p-dd"); $("#p-dd").innerHTML = histSvg(r.dd_hist, { lines: [{ v: m.cdar, label: "CDaR", k: "dash" }] }, c, w, h);
}
function alloc() {
  const el = $("#p-alloc"), W = el.clientWidth, H = el.clientHeight;
  const node = (r) => (r.kind === "asset" ? { r, value: r.effective } : { r, children: kids(R0, r).map(node) });
  const root = d3.hierarchy(node(R0.rows[0])).sum((d) => d.value || 0);
  d3.treemap().size([W - 8, H - 8]).paddingOuter(2).paddingTop((d) => (d.depth === 0 ? 0 : 16)).paddingInner(2).round(true)(root);
  let s = "";
  root.descendants().forEach((d) => { if (!d.depth) return; const r = d.data.r, c = colorOf(r), w = d.x1 - d.x0, h = d.y1 - d.y0, id = idOf(r), on = id === sel;
    if (r.kind === "group") { s += `<rect x="${d.x0}" y="${d.y0}" width="${w}" height="${h}" rx="3" fill="none" stroke="${on ? "var(--att)" : `color-mix(in oklab, ${c} 45%, var(--frame-2))`}" stroke-width="${on ? 2 : 1}" data-r="${esc(id)}" class="hit"/>`;
      if (w > 40) s += `<text class="lbl" x="${d.x0 + 5}" y="${d.y0 + 12}" style="font-size:11px">${esc(r.name.length * 6.5 > w - 10 ? r.name.slice(0, Math.max(3, Math.floor((w - 10) / 6.5))) + "…" : r.name)} <tspan class="mu" style="font:400 10.5px var(--code)">${w > 120 ? p1(r.effective) : ""}</tspan></text>`; }
    else { s += `<rect x="${d.x0}" y="${d.y0}" width="${w}" height="${h}" rx="2" fill="color-mix(in oklab, ${c} 34%, var(--panel))" stroke="${on ? "var(--att)" : "none"}" stroke-width="2" data-r="${esc(id)}" class="hit"/>`;
      if (w > 34 && h > 16) s += `<text x="${d.x0 + 4}" y="${d.y0 + 12}" style="font-weight:600;fill:color-mix(in oklab, ${c} 70%, white)">${esc(r.name)}</text>`;
      if (w > 34 && h > 30) s += `<text x="${d.x0 + 4}" y="${d.y0 + 25}">${p1(r.effective)}</text>`; } });
  el.innerHTML = `<div style="position:absolute;inset:4px">${svg(W - 8, H - 8, s)}</div>`;
}

// ---- Builder: shares and dollars -----------------------------------------------------------------------
// Trade-as tickers: the portfolio's own (set in the builder), editable here; each gets its own price from the day's data.
const TRADE = {}, TA_PRICE = {}; let BUDGET = 100000;
{ const A = (LIVE.portfolio && LIVE.portfolio.assets) || {}; Object.entries(A).forEach(([t, a]) => { if (a.trade_as) TRADE[t] = a.trade_as; }); }
async function tradeAsPrices() {
  const need = [...new Set(Object.values(TRADE).filter((t) => t && !(t in TA_PRICE)))];
  if (!need.length) return;
  const d = await (await fetch(`/api/prices?tickers=${encodeURIComponent(need.join(","))}`)).json();
  need.forEach((t) => { TA_PRICE[t] = d.prices[t] ? d.prices[t].price : null; });
  if (view === "builder") orders();
}
async function saveTradeAs(t, ta) {   // the mapping belongs to the portfolio: the builder shows it too
  const p = API.get(`/api/portfolios/${LIVE.portfolio.id}`); delete p.as_of; delete p.jump_version;
  if (!p.assets[t]) return; p.assets[t].trade_as = ta || null;
  await fetch(`/api/portfolios/${LIVE.portfolio.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(p) });
}
function orders() {
  const assets = R0.rows.filter((r) => r.kind === "asset"), snap = HIST.fetched;
  tradeAsPrices();
  const line = (r) => { const t = TRADE[r.name] || "", own = !t, price = own ? byTicker[r.name]?.price : TA_PRICE[t] ?? null, dollars = r.effective * BUDGET;
    const shares = price ? Math.floor((dollars / price) * 100) / 100 : null, spent = shares != null ? shares * price : 0;
    return { r, t, price, dollars, shares, spent, fut: own && /=F$/.test(r.name) }; };
  const L = assets.map(line), spent = d3.sum(L, (x) => x.spent), left = BUDGET - spent;
  const groups = R0.rows.filter((r) => r.kind === "group" && r.path.length);
  const rows = R0.rows.filter((r) => r.path.length).map((r) => { const id = idOf(r), d = r.path.length, c = colorOf(r);
    if (r.kind === "group") { const mine = L.filter((x) => idOf(x.r).startsWith(id + "/")); return `<tr class="g d${d}"><td class="l nm" style="--c:${c};padding-left:${8 + 14 * (d - 1)}px">${esc(r.name)}</td><td></td><td></td><td>${p2(r.effective)}</td><td>${money(d3.sum(mine, (x) => x.dollars))}</td><td></td><td>${money(d3.sum(mine, (x) => x.spent))}</td></tr>`; }
    const x = L.find((q) => q.r === r);
    return `<tr><td class="l nm" style="--c:${c};padding-left:${8 + 14 * (d - 1)}px"><span class="tk">${esc(r.name)}</span>${x.fut ? `<span class="flag" style="margin-left:6px">futures: set a trade-as ticker</span>` : ""}</td>
      <td class="l"><input class="box ta" data-ta="${esc(r.name)}" value="${esc(x.t)}" placeholder="" aria-label="Trade ${esc(r.name)} as" autocomplete="off" spellcheck="false"></td>
      <td>${x.price == null ? `<span class="flag">${x.t && !(x.t in TA_PRICE) ? "fetching the price…" : x.t ? `no price for ${esc(x.t)}` : "price arrives with Refresh data"}</span>` : money(x.price)}</td><td>${p2(r.effective)}</td><td>${money(x.dollars)}</td><td>${x.shares == null ? "—" : x.shares.toFixed(2)}</td><td>${money(x.spent)}</td></tr>`; }).join("");
  $("#p-orders").innerHTML = `<div class="bset"><label for="budget">Portfolio size, $</label><input class="box" id="budget" value="${BUDGET.toLocaleString("en-US")}" autocomplete="off">
      <span class="mu">prices: last close in the market data of ${snap}; a trade-as ticker uses its own</span></div>
    <table><thead><tr><th class="l">Asset</th><th class="l">Trade as</th><th>Price</th><th>Weight</th><th>Target $</th><th>Shares</th><th>Spent $</th></tr></thead><tbody>${rows}</tbody></table>`;
  moneyPanel(L, spent, left, groups);
}
function moneyPanel(L, spent, left, groups) {
  const el = $("#p-money"), W = el.clientWidth, top = R0.rows.filter((r) => r.path.length === 1);
  const parts = top.map((g) => ({ g, v: d3.sum(L.filter((x) => idOf(x.r) === idOf(g) || idOf(x.r).startsWith(idOf(g) + "/")), (x) => x.spent) })).concat([{ g: null, v: left }]);
  const x = d3.scaleLinear().domain([0, BUDGET]).range([12, W - 12]); let a = 0, s = "";
  parts.forEach(({ g, v }) => { const x0 = x(a), x1 = x(a + v); a += v;
    s += `<rect x="${x0}" y="20" width="${Math.max(0, x1 - x0 - 2)}" height="26" rx="2" fill="${g ? `color-mix(in oklab, ${colorOf(g)} 55%, var(--panel))` : "none"}" stroke="${g ? "none" : "var(--frame-2)"}" stroke-dasharray="${g ? "" : "3 2"}"/>`; });
  const fut = L.filter((x) => x.fut);
  el.innerHTML = svg(W, 58, s) + `<dl class="kv" style="padding:0 12px 6px">${parts.map(({ g, v }) => `<div><dt><i class="bar" style="--c:${g ? colorOf(g) : "var(--frame-2)"};width:10px"></i>${g ? esc(g.name) : "Left over"}</dt><dd>$${money(v)}</dd></div>`).join("")}</dl>`
    + `<p class="note" style="margin-bottom:10px;max-width:none">Spent $${money(spent)} of $${money(BUDGET)}. ${fut.length ? `${fut.map((x) => x.r.name).join(", ")} ${fut.length === 1 ? "is a futures contract" : "are futures contracts"}: $${money(d3.sum(fut, (x) => x.spent))} of it buys the futures price until a trade-as ticker (an ETF you hold) is set. ` : ""}The model keeps simulating the original ticker; a trade-as ticker only changes what you buy.</p>`;
}

// ---- Compare: two runs of the same tree -------------------------------------------------------------------
function compare() {
  $("#cmp-sub").textContent = "this run against the reference tree (baseline); signed, in points";
  const d = (a, b, dp = 1) => { const v = b - a; return `<span style="color:${Math.abs(v) < 5e-5 ? "var(--mute)" : v > 0 ? "var(--up)" : "var(--down)"}">${Math.abs(v) < 5e-5 ? "0.0" : (v > 0 ? "▲ +" : "▼ " + MINUS) + Math.abs(v * 100).toFixed(dp)}</span>`; };
  const rows = R0.rows.map((a) => { const id = idOf(a), b = M1.get(id), c = colorOf(a), g = a.kind === "group", dep = a.path.length;
    return `<tr data-r="${esc(id)}" class="${g ? "g d" + dep : ""}${id === sel ? " on" : ""}"><td class="l nm" style="--c:${c};padding-left:${8 + 14 * dep}px">${g ? esc(a.name) : `<span class="tk">${esc(a.name)}</span>`}</td>
      <td>${p2(a.effective)}</td><td>${p2(b.effective)}</td><td>${d(a.effective, b.effective, 2)}</td><td>${d(a.metrics.er_12w, b.metrics.er_12w, 2)}</td><td>${d(a.metrics.cvar, b.metrics.cvar)}</td><td>${d(a.metrics.cdar, b.metrics.cdar)}</td>
      <td>${a.metrics.upi == null || b.metrics.upi == null ? "—" : `${Math.abs(b.metrics.upi - a.metrics.upi) < 0.005 ? `<span class="mu">0.00</span>` : `<span style="color:${b.metrics.upi > a.metrics.upi ? "var(--up)" : "var(--down)"}">${b.metrics.upi > a.metrics.upi ? "▲ +" : "▼ " + MINUS}${Math.abs(b.metrics.upi - a.metrics.upi).toFixed(2)}</span>`}`}</td></tr>`; }).join("");
  $("#p-ctab").innerHTML = `<table><thead><tr><th class="l">Part</th><th>Effective<small>baseline</small></th><th>Effective<small>this run</small></th><th>Δ weight</th><th>Δ expected</th><th>Δ CVaR</th><th>Δ CDaR</th><th>Δ UPI</th></tr></thead><tbody>${rows}</tbody></table>`;
  whatChanged();
  const [w, h] = size("#p-cfan"), r0 = M0.get(sel), r1 = M1.get(sel), c = colorOf(r0) === "var(--ink-2)" ? "#c0caf5" : colorOf(r0);
  $("#p-cfan").innerHTML = fanSvg("cfan", [{ r: r0, c }, { r: r1, c: "#c0caf5", dash: true }], w, h - 26) + `<div class="legend"><span><i class="bar" style="--c:${c};width:14px"></i>baseline</span><span><i style="width:16px;border-top:2px dashed #c0caf5"></i>this run</span></div>`;
  $$("[data-for]").forEach((e) => (e.textContent = r0.name));
}

// what changed between the baseline and this run, from the engine's own record of both (/api/compare)
const SETLABEL = { cvar_floor: "CVaR floor", floor_strictness: "floor strictness", tail: "tail level", concentration: "concentration penalty",
  window: "stop window", tol: "stop tolerance", maxgen: "generation cap", pop_per_dim: "population" };
function changeText(c) {
  const names = [...c.what.matchAll(/\[([^\]]+)\]/g)].map((m) => m[1]), keys = c.what.replace(/\[[^\]]+\]/g, "").split(".").filter(Boolean);
  const v = (x) => (x == null ? "none" : typeof x === "number" ? (Math.abs(x) < 5 && !Number.isInteger(x) ? pct(x, 1) : String(x)) : String(x));
  const where = names.length ? names.join(" / ") : "", last = keys[keys.length - 1], k2 = keys[keys.length - 2];
  let what = c.what;
  if (keys[0] === "assets") what = `${c.what.split(".")[1]} ${keys.slice(2).join(" ")}`;
  else if (k2 === "min" || k2 === "max") what = `${where}: ${keys.includes("portfolio_limits") ? "share of the Portfolio" : "share of its parent"}, ${k2}imum${last === "on" ? " (on/off)" : ""}`;
  else if (keys.includes("settings")) what = `${where}: ${SETLABEL[last] || last}`;
  else if (keys.includes("view")) what = `${where}: view ${last}`;
  else if (keys[0] === "run") what = `run-wide ${last.replace("_", " ")}`;
  else if (!keys.length || ["data day", "jump version", "machine", "scenario count"].includes(c.what)) what = c.what;
  return `<li><b style="color:var(--att)">${esc(what)}</b><span>${esc(v(c.before))} → ${esc(v(c.after))}</span></li>`;
}
function whatChanged() {
  const el = $("#p-changed");
  const opts = DATA.others.map((r) => `<option value="${esc(r.id)}"${r.id === DATA.compareBase ? " selected" : ""}>${esc(when(r.ended || r.queued))}, ${r.machine === "a100" ? "A100" : "this computer"}</option>`).join("");
  const pick = `<label class="preset" style="margin:0 0 8px">Baseline <select id="cmp-base">${DATA.compareBase ? "" : `<option value="">choose a run</option>`}${opts}</select></label>`;
  if (!DATA.compareBase) { el.innerHTML = pick + `<p class="mu">${DATA.others.length ? "Choose the run to compare this one with." : "This portfolio has no other finished run to compare with."}</p>`; return; }
  let d;
  try { d = API.get(`/api/compare?ids=${encodeURIComponent(DATA.compareBase)},${encodeURIComponent(DATA.thisRun.id)}`).against[0]; }
  catch (e) { el.innerHTML = pick + `<p class="mu">Could not compare: ${esc(e.message)}</p>`; return; }
  const ch = d.changed;
  const same = [["Data", "data day"], ["Jump calibration", "jump version"], ["Machine and scenarios", "machine"]].filter(([, k]) => !ch.some((c) => c.what === k))
    .map(([label]) => `<li><b>${label}</b><span class="mu">the same</span></li>`);
  el.innerHTML = pick + `<ul class="stages">${ch.map(changeText).join("")}${same.join("")}</ul>` + (ch.length ? "" : `<p class="mu">Nothing in the inputs changed: the difference is the scenario draw.</p>`);
}
document.addEventListener("change", (e) => { if (e.target.id === "cmp-base" && e.target.value) {
  location.href = `results.html?run=${encodeURIComponent(DATA.thisRun.id)}&base=${encodeURIComponent(e.target.value)}#compare`; } });

// extensions (app/extensions) add buttons beside the exports; none ship with the tool
let EXT_ACTIONS = [];
try { EXT_ACTIONS = API.get("/api/extensions").items; } catch { /* a server without the endpoint */ }
EXT_ACTIONS.forEach((a) => { const b = document.createElement("button"); b.className = "q"; b.type = "button"; b.dataset.x = a.id; b.textContent = a.label;
  document.querySelector(".top").appendChild(b); });

// ---- exports: the workbook, the report and the builder CSV at the shares view's portfolio size; extension buttons
async function exportRun(kind, btn) {
  const id = DATA.thisRun.id, q = `budget=${encodeURIComponent(BUDGET)}`;
  if (DATA.live) { $("#note").textContent = "Exports open when the run has finished."; return; }
  const ext = EXT_ACTIONS.find((a) => a.id === kind);
  if (ext) {
    btn.disabled = true;
    try { const r = await fetch(ext.post.replace("{run}", encodeURIComponent(id)), { method: "POST" }); const d = await r.json();
      $("#note").textContent = r.ok ? ext.done : `${ext.label} did not work: ${d.detail}`; }
    finally { btn.disabled = false; }
    return; }
  const url = { xlsx: `/api/runs/${encodeURIComponent(id)}/export.xlsx?${q}`, pdf: `/api/runs/${encodeURIComponent(id)}/export.pdf?${q}`, csv: `/api/runs/${encodeURIComponent(id)}/builder.csv?${q}` }[kind];
  location.href = url;
  $("#note").textContent = `${({ xlsx: "Excel workbook", pdf: "PDF report", csv: "Builder CSV" })[kind]} at a portfolio size of $${BUDGET.toLocaleString("en-US")}.`;
}

// ---- Diagnostics ----------------------------------------------------------------------------------------
function diag() {
  const assets = R0.rows.filter((r) => r.kind === "asset");
  { const [W, H0] = size("#p-post"), H = H0 - 24, m = { l: 52, r: 16, t: 10, b: 24 }, rh = (H - m.t - m.b) / assets.length, n = R0.validation_paths;   // H leaves room for the legend
    const v = assets.flatMap((r) => [r.metrics.er_12w, r.metrics.sim_mean_12w]), x = d3.scaleLinear().domain(d3.extent(v)).nice().range([m.l, W - m.r]);
    let s = ""; x.ticks(5).forEach((t) => s += `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--frame)"/><text x="${x(t)}" y="${H - 7}" text-anchor="middle">${sgn(t, 0)}%</text>`);
    assets.forEach((r, i) => { const y = m.t + i * rh + rh / 2, se = r.metrics.vol_12w / Math.sqrt(n), z = (r.metrics.sim_mean_12w - r.metrics.er_12w) / se, c = colorOf(r);
      s += `<text x="${m.l - 6}" y="${y + 3.5}" text-anchor="end" style="fill:color-mix(in oklab, ${c} 70%, white)">${r.name}</text><line x1="${x(r.metrics.er_12w)}" x2="${x(r.metrics.sim_mean_12w)}" y1="${y}" y2="${y}" stroke="${Math.abs(z) > 3 ? "var(--att)" : "var(--frame-2)"}" stroke-width="2"/>`
        + `<line x1="${x(r.metrics.er_12w)}" x2="${x(r.metrics.er_12w)}" y1="${y - 5}" y2="${y + 5}" stroke="var(--ink)" stroke-width="1.5"/><circle cx="${x(r.metrics.sim_mean_12w)}" cy="${y}" r="3.2" fill="${c}"/>`
        + `<rect class="hit" x="0" y="${y - rh / 2}" width="${W}" height="${rh}" fill="transparent" data-tipx="${esc(`${r.name}: posterior ${pct(r.metrics.er_12w, 2, true)}, simulated ${pct(r.metrics.sim_mean_12w, 2, true)} over ${n.toLocaleString("en-US")} paths (${z >= 0 ? "+" : MINUS}${Math.abs(z).toFixed(1)} standard errors)`)}"/>`; });
    $("#p-post").innerHTML = svg(W, H, s); }
  { const S = R0.rows.filter((r) => r.search && r.search.generations), [W, H] = size("#p-hist"), cols = 3, rowsN = Math.ceil(S.length / cols), cw = W / cols, ch = H / rowsN;
    let s = ""; S.forEach((r, i) => { const h = r.search.history, x0 = (i % cols) * cw, y0 = Math.floor(i / cols) * ch, x = d3.scaleLinear().domain([1, h.length]).range([x0 + 8, x0 + cw - 8]), y = d3.scaleLinear().domain(d3.extent(h)).range([y0 + ch - 8, y0 + 22]);
      s += `<text class="lbl" x="${x0 + 8}" y="${y0 + 14}" style="font-size:11px">${esc(r.name)}</text><text x="${x0 + cw - 8}" y="${y0 + 14}" text-anchor="end">${r.search.generations} gen</text><path d="${d3.line().x((v, j) => x(j + 1)).y((v) => y(v))(h)}" fill="none" stroke="${colorOf(r)}" stroke-width="1.5"/>`; });
    $("#p-hist").innerHTML = svg(W, H, s); }
  $("#p-betas").innerHTML = `<table><thead><tr><th class="l">Asset</th><th>Crash β</th><th>Days</th><th class="l">Estimated</th><th>Rally β</th><th>Days</th><th class="l">Estimated</th></tr></thead><tbody>${assets.map((r) => { const b = BETAS[r.name];
    return `<tr><td class="l nm" style="--c:${colorOf(r)}"><span class="tk">${r.name}</span></td><td>${num(b.crash)}</td><td>${b.crashN}</td><td class="l mu">${betaSource(b.crashN)}</td><td>${num(b.rally)}</td><td>${b.rallyN}</td><td class="l mu">${betaSource(b.rallyN)}</td></tr>`; }).join("")}</tbody></table>`;
  { const [W, H0] = size("#p-sim"), H = H0 - 24, cols = 4, rowsN = Math.ceil(assets.length / cols), cw = W / cols, ch = H / rowsN; let s = "";
    assets.forEach((r, i) => { const x0 = (i % cols) * cw, y0 = Math.floor(i / cols) * ch, E = r.ret_hist.edges, cl = HIST.series[r.name]?.close || [];
      const hr = cl.slice(12).map((v, k) => v / cl[k] - 1), x = d3.scaleLinear().domain([E[0], E[E.length - 1]]).range([x0 + 4, x0 + cw - 4]);
      const sim = r.ret_hist.counts, tot = d3.sum(sim), bw = E[1] - E[0], dens = sim.map((n) => n / tot / bw);
      const hh = E.slice(0, -1).map((e, k) => { const a = E[Math.max(0, k - 2)], b = E[Math.min(E.length - 1, k + 3)]; return hr.filter((v) => v >= a && v < b).length / Math.max(1, hr.length) / (b - a); });   // 5 years is ~250 overlapping windows: smoothed over 5 bins
      const y = d3.scaleLinear().domain([0, d3.max(dens.concat(hh))]).range([y0 + ch - 4, y0 + 18]), mid = E.slice(0, -1).map((e) => e + bw / 2);
      s += `<text x="${x0 + 4}" y="${y0 + 12}" style="fill:color-mix(in oklab, ${colorOf(r)} 70%, white)">${r.name}</text>`
        + `<path d="${d3.area().x((v, k) => x(mid[k])).y0(y0 + ch - 4).y1((v) => y(v))(dens)}" fill="${colorOf(r)}" fill-opacity="0.35"/>`
        + `<path d="${d3.line().x((v, k) => x(mid[k])).y((v) => y(v))(hh)}" fill="none" stroke="var(--ink)" stroke-width="1"/>`; });
    $("#p-sim").innerHTML = svg(W, H, s); }
  const HC = DATA.heston;
  $("#p-heston").innerHTML = `<table><thead><tr><th class="l">Asset</th><th>Vol now<small>√v₀·√52</small></th><th>Long-run<small>√θ·√52</small></th><th>Pull κ</th><th>Vol of vol ξ</th><th>ρ</th></tr></thead><tbody>${assets.map((r) => { const h = HC[r.name];
    const atb = h.xi <= 0.00011 || (h.at_bound || []).length > 0;   // a fitted value at its bound: the engine reports which
    const pooled = h.source && h.source !== "fit";                    // no shock response in its GARCH: constant variance, κ and ξ pooled
    const tipx = atb ? `${r.name}: ${(h.at_bound || []).join("; ") || "vol of vol at the fit's lower bound (0.0001)"}. Check this fit before trusting the run.`
      : pooled ? `${r.name}: its GARCH showed no response to shocks on 5 years of weekly data, so its variance is constant at its own realized level; κ and ξ are ${h.source}.` : "";
    return `<tr${tipx ? ` data-tipx="${esc(tipx)}"` : ""}><td class="l nm" style="--c:${colorOf(r)}"><span class="tk">${r.name}</span>${atb ? `<span class="bind">at bound</span>` : pooled ? `<span class="bind">pooled</span>` : ""}</td><td>${p1(Math.sqrt(h.v0 * 52))}</td><td>${p1(Math.sqrt(h.theta * 52))}</td><td>${num(h.kappa, 3)}</td><td${atb ? ' style="color:var(--att)"' : ""}>${num(h.xi, 4)}</td><td>${num(h.rho, 2)}</td></tr>`; }).join("")}</tbody></table>`;
  const J = DATA.jumps, jr = (k, label) => `<tr><td class="l">${label}</td><td>${num(J.systematic[k], 3)}</td><td>${num(J.idiosyncratic[k], 3)}</td></tr>`;
  $("#p-jumps").innerHTML = `<table><thead><tr><th class="l">Parameter</th><th>Systematic</th><th>Idiosyncratic</th></tr></thead><tbody>
    <tr><td class="l">Jumps a week, λ</td><td>${num(DATA.jumps.systematic.lambda, 4)}</td><td>${num(DATA.jumps.idiosyncratic.lambda, 4)}</td></tr>${jr("prob_crash", "Share that are crashes")}${jr("crash_scale", "Crash size, scale")}${jr("crash_shape", "Crash size, shape")}${jr("rally_scale", "Rally size, scale")}${jr("rally_shape", "Rally size, shape")}${jr("threshold", "Jump threshold, σ")}</tbody></table>`;
}

// ---- Progress: the record of this run, and the launch choice ---------------------------------------------------
let MACH = "laptop";
function progress() {
  const S = []; const post = (r) => { kids(R0, r).forEach(post); if (r.search && r.search.generations) S.push(r); }; post(R0.rows[0]);
  const [W, H] = size("#p-gantt"), m = { l: 150, r: 104, t: 26, b: 28 }, total = d3.sum(S, (r) => r.search.wall_s), bank = DATA.bank_build_s;
  const x = d3.scaleLinear().domain([0, bank + total]).range([m.l, W - m.r]), rh = Math.min(52, (H - m.t - m.b) / (S.length + 1));
  let s = `<text class="lbl" x="${m.l - 10}" y="${m.t + rh / 2 + 4}" text-anchor="end">Scenario bank</text><rect x="${x(0)}" y="${m.t + 6}" width="${x(bank) - x(0)}" height="${rh - 12}" fill="var(--frame-2)"/><text x="${x(bank) + 6}" y="${m.t + rh / 2 + 4}">${bank} s</text>`;
  let t = bank;
  S.forEach((r, i) => { const y = m.t + (i + 1) * rh, sw = r.search.wall_s, g = r.search.generations, c = colorOf(r);
    s += `<text class="lbl" x="${m.l - 10}" y="${y + rh / 2 + 4}" text-anchor="end">${esc(r.name)}</text><rect x="${x(t)}" y="${y + 6}" width="${Math.max(2, x(t + sw) - x(t))}" height="${rh - 12}" fill="color-mix(in oklab, ${c} 60%, var(--panel))"/>`;
    for (let k = 1; k < g; k++) s += `<line x1="${x(t + (sw * k) / g)}" x2="${x(t + (sw * k) / g)}" y1="${y + 6}" y2="${y + rh - 6}" stroke="var(--panel)" stroke-width="0.8"/>`;
    s += `<text x="${x(t + sw) + 6}" y="${y + rh / 2 + 4}">${g} gen, ${sw} s</text>`; t += sw; });
  x.ticks(6).forEach((v) => s += `<line x1="${x(v)}" x2="${x(v)}" y1="${m.t - 4}" y2="${H - m.b}" stroke="var(--frame)" stroke-dasharray="2 3"/><text x="${x(v)}" y="${H - m.b + 14}" text-anchor="middle">${v < 60 ? v + " s" : Math.floor(v / 60) + ":" + String(Math.round(v % 60)).padStart(2, "0")}</text>`);
  $("#p-gantt").innerHTML = svg(W, H, s);
  $("#prog-sub").textContent = `finished ${when(R0.finished)}`;
  $("#p-run").innerHTML = `<div class="machines" role="group" aria-label="Where the next run goes">
      <button class="mach" type="button" data-m="laptop" aria-pressed="${MACH === "laptop"}"><b>This computer${LIVE.device ? `, ${esc(LIVE.device)}` : ""}</b><span>as many paths as fit: up to 2,000,000 on an NVIDIA GPU, 400,000 on a CPU; free</span></button>
      <button class="mach" type="button" data-m="a100" aria-pressed="${MACH === "a100"}"><b>Colab ${colabGPU()}</b><span>up to 30,000,000 paths kept on the rented GPU; about a minute to start; set it up and pick the GPU on the <a href="setup.html" style="color:inherit">setup screen</a></span></button></div>
    <ul class="stages"><li><b>Data and fits</b><span>reused from the snapshot of ${when(DATA.inputs_created)}</span></li><li><b>Scenario bank</b><span>${DATA.config.bank.toLocaleString("en-US")} paths in ${bank} s</span></li>
      <li><b>Searches</b><span>${S.length}, inside out, ${Math.round(total)} s; one-member subportfolios take 100% with no search</span></li><li><b>Figures</b><span>on ${R0.validation_paths.toLocaleString("en-US")} paths no search saw</span></li>
      <li><b>Time</b><span>${Math.floor(R0.wall_s / 60)} min ${Math.round(R0.wall_s % 60)} s in all, plus the bank</span></li></ul>
    <div class="runbtns"><button class="go" type="button" id="again">Run again</button><button class="stop" type="button" id="cancel" disabled title="Nothing is running">Cancel</button></div>
    <p class="note">While a run is going, the bars grow live and Cancel stops it; on Colab, Cancel always shuts the machine down. Runs continue in the background, one per machine.</p>`;
}

// ---- wiring ---------------------------------------------------------------------------------------------
function draw() {
  if (DATA.live) view = "progress";   // a run still going has no figures yet: only Progress can draw
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.v === view)));
  ["progress", "results", "builder", "compare", "diag"].forEach((v) => ($("#v-" + v).hidden = v !== view));
  if (view === "results") roomBuild(); else if (view === "builder") orders(); else if (view === "compare") compare(); else if (view === "diag") diag(); else progress();
}
const go = (v) => {
  if (v === "compare" && !DATA.compareBase && DATA.others.length) { location.href = `results.html?run=${encodeURIComponent(DATA.thisRun.id)}&base=${encodeURIComponent(DATA.others[0].id)}#compare`; return; }
  if (v !== "compare" && DATA.compareBase) { location.href = `results.html?run=${encodeURIComponent(DATA.thisRun.id)}#${v}`; return; }
  view = v; try { history.replaceState(null, "", "#" + v); } catch {} draw(); };
$(".tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (b) go(b.dataset.v); });
document.addEventListener("click", (e) => {
  const f = e.target.closest("[data-fold]"); if (f) { const id = f.dataset.fold; FOLD.has(id) ? FOLD.delete(id) : FOLD.add(id); roomBuild(); return; }
  const d = e.target.closest("[data-det]"); if (d) { const id = d.dataset.det; OPEN.has(id) ? OPEN.delete(id) : OPEN.add(id); roomBuild(); return; }
  const m = e.target.closest("[data-m]"); if (m) { MACH = m.dataset.m; progress(); return; }
  if (e.target.closest("#again")) { $("#note").textContent = `Prototype: Run again goes back to the review before the run, then to ${MACH === "a100" ? `Colab ${colabGPU()}` : "this computer"}.`; return; }
  const x = e.target.closest("[data-x]"); if (x) { exportRun(x.dataset.x, x); return; }
  const r = e.target.closest("[data-r]"); if (r && !e.target.closest("input")) { sel = r.dataset.r; draw(); }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "budget") { const v = parseFloat(e.target.value.replace(/[^0-9.]/g, "")); if (v > 0) { BUDGET = v; const k = e.target.selectionStart; orders(); const b = $("#budget"); b.focus(); try { b.setSelectionRange(k, k); } catch {} } }
});
document.addEventListener("change", (e) => { if (e.target.dataset.ta != null) { const t = e.target.dataset.ta, ta = e.target.value.trim().toUpperCase();
  if (ta) TRADE[t] = ta; else delete TRADE[t]; orders(); saveTradeAs(t, ta); } });
document.addEventListener("pointermove", (e) => { const t = e.target.closest?.("[data-tipx]"); if (t) return tip(e, esc(t.dataset.tipx));
  const r = e.target.closest?.("#p-alloc [data-r]"); if (r) { const x = M0.get(r.dataset.r); return tip(e, `<b>${esc(x.name)}</b><br>${p2(x.effective)} of the portfolio${x.path.length ? `, ${p1(x.share)} of ${esc(x.path[x.path.length - 1])}` : ""}`); } tip(e, null); });
addEventListener("resize", draw);
view = ["progress", "results", "builder", "compare", "diag"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "results";
addEventListener("DOMContentLoaded", draw);   // after room.js, which draws the results view
