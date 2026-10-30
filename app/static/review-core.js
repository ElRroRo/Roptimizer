// The pre-run review's arithmetic, shared by both review layouts. It reads the builder's model (builder-core.js)
// and adds only three things: plain-word sentences for every limit and what it squeezes, each subportfolio's
// equal-weight prior and its blend with a group view, and the shapes the layouts draw (weight rails, return rows).
// Honest before the first run: equilibrium values only; the Black-Litterman posterior arrives with a run.

// ---- weights: what each part can take, and what it could take without its siblings' limits --------------
const own = (n) => [lv(n.lim.min) ?? 0, lv(n.lim.max) ?? 1];
function ownEff(n) {   // the range from its own limits alone, inside what its parent can take
  const p = parentOf(n); if (!p) return [1, 1]; const [mn, mx] = own(n); let lo = p._eff[0] * mn, hi = p._eff[1] * mx;
  const wmin = lv(n.lim.wpmin), wmax = lv(n.lim.wpmax); if (wmax != null) hi = Math.min(hi, wmax); if (wmin != null) lo = Math.max(lo, wmin);
  return [lo, hi];
}
// Nothing fits: its range is empty, its share of its parent is, or it is an only member whose limits forbid 100%.
function bad(n) {
  if (!n._eff) return false; if (n._eff[0] > n._eff[1] + 1e-9 || n._share[0] > n._share[1] + 1e-9) return true;
  const p = parentOf(n); if (p && p.children.length === 1) { const [mn, mx] = own(n); return mx < 1 - 1e-9 || mn > 1 + 1e-9; } return false;
}
const free = (n) => n !== ROOT && n.kind && ["min", "max", "wpmin", "wpmax"].every((k) => lv(n.lim[k]) == null);   // no limit of its own: it takes whatever its parent gets
const p01 = (x) => (Math.abs(x * 100 - Math.round(x * 100)) < 0.05 ? pct(x, 0) : pct(x, 1));   // 5%, 4.5%: no trailing .0
const rangeText = ([a, b]) => (Math.abs(a - b) < 5e-5 ? p01(a) : `${p01(a).replace("%", "")} to ${p01(b)}`);
const poss = (s) => (s.endsWith("s") ? s + "’" : s + "’s");
const andList = (xs) => (xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]);
const groupsInOrder = () => { const out = []; const w = (n) => { if (n.kind === "group") { out.push(n); n.children.forEach(w); } }; w(ROOT); return out; };
const nodesInOrder = () => { const out = []; const w = (n) => { if (n !== ROOT) out.push(n); if (n.kind === "group") n.children.forEach(w); }; w(ROOT); return out; };
const depthOf = (n) => { let d = 0; for (let p = parentOf(n); p; p = parentOf(p)) d++; return d; };
const pinned = (g) => g.children.length > 1 && g.children.every((c) => c._share && Math.abs(c._share[0] - c._share[1]) < 1e-9);

// ---- every limit and its squeeze, in plain words -------------------------------------------------------
// Each item: { ids: the nodes it is about (for linking), id: where it lives (for colour), text }.
function limitNotes() {
  const out = [];
  const walk = (n) => {
    if (n !== ROOT && bad(n)) { const p = parentOf(n), mn = lv(n.lim.min), mx = lv(n.lim.max), what = mn != null && mx != null ? `${p01(mn).replace("%", "")} to ${p01(mx)}` : mn != null ? `at least ${p01(mn)}` : mx != null ? `at most ${p01(mx)}` : null;
      out.push({ id: n.id, ids: [n.id], b: true, text: p.children.length === 1 && what ? `${label(n)} takes ${what} of ${p.name}, but it is ${poss(p.name)} only member, so it must take all of it.`
        : what ? `${label(n)} takes ${what} of ${p.name}; with the others' limits this cannot fit.` : `${label(n)}: the limits around it leave no feasible weight.` }); }
    if (n !== ROOT && !bad(n)) {
      const p = parentOf(n), mn = lv(n.lim.min), mx = lv(n.lim.max);
      if (mn != null || mx != null) { const what = mn != null && mx != null ? `${p01(mn).replace("%", "")} to ${p01(mx)}` : mn != null ? `at least ${p01(mn)}` : `at most ${p01(mx)}`;
        out.push({ id: n.id, ids: [n.id], text: `${label(n)} takes ${what} of ${p.name}${p === ROOT ? "" : `, so ${rangeText(n._eff)} of the portfolio`}.` }); }
      const wmax = lv(n.lim.wpmax), wmin = lv(n.lim.wpmin), lo0 = p._eff[0] * n._share[0], hi0 = p._eff[1] * n._share[1];
      if (wmax != null) out.push({ id: n.id, ids: [n.id], text: wmax < hi0 - 1e-9
        ? `${label(n)} holds at most ${p01(wmax)} of the whole portfolio. Its other limits would allow ${p01(hi0)}, so this one binds${p === ROOT ? "" : `: its share of ${p.name}, times ${poss(p.name)} share of the portfolio, stays at or below ${p01(wmax)}`}.`
        : `${label(n)} holds at most ${p01(wmax)} of the whole portfolio. Its other limits already keep it at or below ${p01(hi0)}, so this one never binds.` });
      if (wmin != null) { const need = n._share[1] > 0 ? wmin / n._share[1] : Infinity;
        out.push({ id: n.id, ids: [n.id, p.id], text: wmin > lo0 + 1e-9
          ? `${label(n)} holds at least ${p01(wmin)} of the whole portfolio. Its other limits would allow as little as ${p01(lo0)}, so this one binds${p !== ROOT && need > p._eff[0] + 1e-9 ? `, and ${p.name} needs at least ${p01(need)} of the portfolio to make room` : ""}.`
          : `${label(n)} holds at least ${p01(wmin)} of the whole portfolio. Its other limits already give it ${p01(lo0)} or more, so this one never binds.` }); }
    }
    if (n.kind !== "group") return;
    if (n.children.length > 1 && !n.children.some(bad) && n.children.some((c) => lv(c.lim.min) != null || lv(c.lim.max) != null)) {
      const sq = n.children.filter((c) => { const [mn, mx] = own(c); return c._share[0] > mn + 1e-9 || c._share[1] < mx - 1e-9; });
      if (sq.length) out.push({ id: n.id, ids: [n.id, ...sq.map((c) => c.id)], text: `Inside ${n.name}, the others' limits leave ${andList(sq.map((c) => `${label(c)} ${rangeText(c._share)}`))} of it.` });
    }
    if (n !== ROOT && n.children.length === 1 && !bad(n.children[0])) out.push({ id: n.id, ids: [n.id, n.children[0].id], text: `${n.name} has one member: ${label(n.children[0])} takes all of it, with no search.` });
    if (pinned(n)) out.push({ id: n.id, ids: [n.id, ...n.children.map((c) => c.id)], text: `Every share inside ${n.name} is fixed by its limits, so no search runs there.` });
    n.children.forEach(walk);
  };
  walk(ROOT); return out;
}
// The searches the run will do: one per subportfolio with two or more members whose shares are not all fixed.
const searches = () => groupsInOrder().filter((g) => g.children.length > 1 && !pinned(g));

// ---- returns: each subportfolio's equal-weight prior, the range its limits allow, the view and the blend -----
// The prior on a mix w is N(wᵀπ, τ·wᵀΣw): π the equilibrium returns, Σ from 5 years of weekly prices (the run uses
// its own forecast). A view on the subportfolio as a whole is a view on that same mix, so the blend is exact:
// the precision-weighted mean of the prior and the view.
function mixOf(n, w = 1, out = new Map()) {
  if (n.kind === "asset") { if (byTicker[n.t]?.eq != null) out.set(n.t, (out.get(n.t) || 0) + w); return out; }
  const kids = n.children.filter((c) => eqEW(c) != null); kids.forEach((c) => mixOf(c, w / kids.length, out)); return out;
}
function priorSd(n) {
  if (n.kind === "asset") return eqBand(n)?.sd ?? null;
  const m = mixOf(n), T = [...m.keys()]; let v = 0;
  for (const a of T) for (const b of T) { const sa = HIST.series[a]?.vol, sb = HIST.series[b]?.vol; if (sa == null || sb == null) return null; v += m.get(a) * m.get(b) * corr(a, b) * sa * sb; }
  return T.length ? Math.sqrt(TAU * v) : null;
}
function groupReturn(g) {
  const eq = eqEW(g); if (eq == null) return null;
  const sd0 = priorSd(g), rg = g.kind === "group" && g.children.length > 1 ? eqRange(g) : null, vw = g.kind === "group" && g !== ROOT ? groupModel(g) : null;
  let blend = null; if (vw && sd0) { const a = 1 / sd0 ** 2, b = 1 / vw.sd ** 2; blend = { mean: (eq * a + vw.mean * b) / (a + b), sd: 1 / Math.sqrt(a + b) }; }
  const kids = g.kind === "group" ? g.children.filter((c) => eqEW(c) != null) : [], ewOk = kids.every((c) => 1 / kids.length >= c._share[0] - 1e-9 && 1 / kids.length <= c._share[1] + 1e-9);
  const missing = g.kind === "group" ? (() => { const m = []; const w = (n) => { if (n.kind === "asset") { if (byTicker[n.t]?.eq == null) m.push(n.t || "a new asset"); } else n.children.forEach(w); }; w(g); return m; })() : [];
  return { eq, sd0, rg, vw, blend, ewOk, missing };
}

// ---- settings: every value and where it comes from ------------------------------------------------------
const SHORT = { cvar: "CVaR", strict: "Strict", tail: "Tail", conc: "Conc.", stop: "Stop", cap: "Cap", pop: "Pop." };
function fmtSet(S, v) { if (S.k === "strict") return v === "hard" ? "hard" : "soft"; if (S.k === "conc") return v == null ? "off" : num(v, 2); if (S.pct) return p01(v); return String(v); }
const DEFAULT_INSIDE = (S) => fmtSet(S, S.def({}));   // the default below the Portfolio (the concentration penalty is on only at the top)

// ---- what blocks, what is only worth knowing --------------------------------------------------------------
function issues() { const c = checks(); return { blocks: c.filter((x) => x.b), notes: c.filter((x) => !x.b && !/has one member/.test(x.text)) }; }
const runWideText = () => `Run-wide, set on the Portfolio: ${RUNSET.weeks}-week horizon, ${RUNSET.paths.toLocaleString("en-US")} scenario paths, risk-free ${pct(RUNSET.rf, 3)} a year, data of ${HIST.fetched}.`;
const runWide = () => [["Horizon", `${RUNSET.weeks} weeks`], ["Scenarios", `${RUNSET.paths.toLocaleString("en-US")} paths`], ["Risk-free", pct(RUNSET.rf, 3) + " a year"], ["Data", HIST.fetched]];

// ---- shapes ---------------------------------------------------------------------------------------------
// The weight scale: square root, so 0.5% and 50% both read; the same scale everywhere on the screen.
const WTICKS = [0, 0.01, 0.05, 0.1, 0.25, 0.5, 1];
const wscale = (x0, x1) => d3.scaleSqrt().domain([0, 1]).range([x0, x1]);
// One rail: the range it can take (solid), what its own limits alone would allow (dashed, when wider), brackets
// where its own limits set an end, and a cross where nothing fits.
function rail(n, x, y, h, c, opts = {}) {
  if (n.kind === "group" && !n.children.length) return "";   // an empty subportfolio has nothing to weigh; it blocks the run instead
  const [lo, hi] = n._eff, [glo, ghi] = ownEff(n), mid = y + h / 2;
  let s = "";
  if (bad(n)) { const a = x(Math.min(1, Math.max(lo, hi))), b = x(Math.max(0, Math.min(lo, hi)));
    return `<line x1="${b}" x2="${a}" y1="${mid}" y2="${mid}" stroke="var(--att)" stroke-width="2" stroke-dasharray="3 3"/><path d="M${a - 4},${mid - 4} l8,8 M${a + 4},${mid - 4} l-8,8" stroke="var(--att)" stroke-width="2"/><line x1="${b}" x2="${b}" y1="${mid - 5}" y2="${mid + 5}" stroke="var(--att)" stroke-width="2"/>`; }
  if (glo < lo - 1e-6 || ghi > hi + 1e-6) s += `<rect x="${x(glo)}" y="${y - 2}" width="${Math.max(2, x(ghi) - x(glo))}" height="${h + 4}" rx="2" fill="none" stroke="color-mix(in oklab, ${c} 55%, var(--frame-2))" stroke-dasharray="3 2.5"/>`;
  const a = x(lo), b = Math.max(x(hi), a + 3);
  if (opts.quiet && free(n) && glo >= lo - 1e-6 && ghi <= hi + 1e-6) return s + `<line x1="${a}" x2="${b}" y1="${mid}" y2="${mid}" stroke="color-mix(in oklab, ${c} 68%, var(--panel))" stroke-width="${Math.max(2.5, h * 0.45)}" stroke-linecap="round"/>`;
  s += `<rect x="${a}" y="${y}" width="${b - a}" height="${h}" rx="${Math.min(2, h / 2)}" fill="${opts.fill || c}"/>`;
  if (n !== ROOT && n.kind) { const [mn, mx] = [lv(n.lim.min), lv(n.lim.max)], wmn = lv(n.lim.wpmin), wmx = lv(n.lim.wpmax);
    const br = (px, dir) => `<path d="M${px + dir * 4},${y - 4} H${px} V${y + h + 4} H${px + dir * 4}" fill="none" stroke="var(--ink)" stroke-width="1.4"/>`;
    if ((mn != null && Math.abs(n._share[0] - mn) < 1e-9 && mn > 0 && lo > 1e-9) || (wmn != null && Math.abs(lo - wmn) < 1e-9)) s += br(a, 1);
    if ((mx != null && Math.abs(n._share[1] - mx) < 1e-9 && mx < 1) || (wmx != null && Math.abs(hi - wmx) < 1e-9)) s += br(b, -1); }
  return s;
}
function wAxis(x, y0, y1, labels = true) {
  return WTICKS.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${y0}" y2="${y1}" stroke="${t === 0 ? "var(--frame-2)" : "var(--frame)"}"/>` + (labels ? `<text class="ax" x="${x(t)}" y="${y0 - 5}" text-anchor="middle">${t === 1 ? "100%" : Math.round(t * 100)}</text>` : "")).join("");
}
// One return row: the equilibrium dot with its ±√τσ, the band its limits let the mix reach, the view (split-normal
// mean ± sd) and the blend the parent's search hears.
function retRow(R, x, y, c) {
  if (!R) return "";
  let s = "";
  if (R.rg && R.rg[1] - R.rg[0] > 5e-4) s += `<rect x="${x(R.rg[0])}" y="${y - 5}" width="${x(R.rg[1]) - x(R.rg[0])}" height="10" rx="2" fill="color-mix(in oklab, ${c} 22%, transparent)"/>`
    + [R.rg[0], R.rg[1]].map((v) => `<line x1="${x(v)}" x2="${x(v)}" y1="${y - 8}" y2="${y + 8}" stroke="color-mix(in oklab, ${c} 60%, transparent)" stroke-width="1.5"/>`).join("");   // end ticks: a narrow band still shows past the dot
  if (R.sd0) s += `<line x1="${x(R.eq - R.sd0)}" x2="${x(R.eq + R.sd0)}" y1="${y}" y2="${y}" stroke="${c}" stroke-width="1.5"/>`;
  if (R.vw) { const vy = y + 9; s += `<line x1="${x(R.vw.mean - R.vw.sd)}" x2="${x(R.vw.mean + R.vw.sd)}" y1="${vy}" y2="${vy}" stroke="var(--ink-2)" stroke-width="1.5" stroke-dasharray="3 2"/><rect x="${x(R.vw.mean) - 3}" y="${vy - 3}" width="6" height="6" fill="var(--ink-2)"/>`; }
  s += `<circle cx="${x(R.eq)}" cy="${y}" r="4" fill="var(--panel)" stroke="${c}" stroke-width="2"${R.ewOk ? "" : ' stroke-dasharray="2.2 1.6"'}/>`;
  if (R.blend) s += `<line x1="${x(R.blend.mean - R.blend.sd)}" x2="${x(R.blend.mean + R.blend.sd)}" y1="${y}" y2="${y}" stroke="var(--ink)" stroke-width="2.5"/><path d="M${x(R.blend.mean)},${y - 6} l6,6 l-6,6 l-6,-6 Z" fill="var(--ink)" stroke="var(--panel)" stroke-width="1.5"/>`;
  return s;
}
function retDomain(Rs) {
  const v = Rs.filter(Boolean).flatMap((R) => [R.eq - (R.sd0 || 0), R.eq + (R.sd0 || 0), ...(R.rg || []), ...(R.vw ? [R.vw.mean - R.vw.sd, R.vw.mean + R.vw.sd] : [])]);
  if (!v.length) return [0, 0.2]; const lo = d3.min(v), hi = d3.max(v), pad = Math.max(0.01, (hi - lo) * 0.08);
  return [Math.floor((lo - pad) * 50) / 50, Math.ceil((hi + pad) * 50) / 50];
}
const retLegend = (anyView, anyOut, anyBlend = anyView, viewWord = "group view") => `<span><i class="lg-dot"></i>equilibrium at equal weights, ± √τ·σ</span>${anyOut ? `<span><i class="lg-dot out"></i>equal weights break its limits</span>` : ""}<span><i class="lg-band"></i>what its limits let the mix reach</span>${anyView ? `<span><i class="lg-view"></i>${viewWord}</span>` : ""}${anyBlend ? `<span><i class="lg-blend"></i>blend the parent hears</span>` : ""}`;
function retText(n) {   // the sentence for hover and the ledger
  const R = groupReturn(n); if (!R) return n.kind === "group" && !n.children.length ? `${esc(n.name)} is empty.` : `${esc(label(n))} has no prices yet, so no equilibrium: Refresh data fetches them.`;
  let t = `Equilibrium at equal weights ${pct(R.eq, 1, true)} ± ${pts(R.sd0)} points${R.missing.length ? ` (without ${esc(andList(R.missing))}: no prices yet)` : ""}`;
  if (!R.ewOk) t += `. Equal weights break its limits, so the run's mix sits inside the band`;
  if (R.rg && R.rg[1] - R.rg[0] > 5e-4) t += `; its limits let the mix move it from ${pct(R.rg[0], 1, true)} to ${pct(R.rg[1], 1, true)}`;
  if (R.vw) t += `. Group view ${pct(R.vw.mean, 1, true)} ± ${pts(R.vw.sd)}; ${poss(parentOf(n).name)} search hears the blend, ${pct(R.blend.mean, 1, true)} ± ${pts(R.blend.sd)}`;
  return t + ".";
}
// The hover readout for any part of the review
function reviewTip(n) {
  if (n.kind === "asset") { const m = modelOf(n), E = eqBand(n);
    return `<code>${esc(n.t || "new asset")}</code> in ${esc(parentOf(n).name)}<br>can take ${bad(n) ? `<span style="color:var(--att)">nothing: ${pct(n._eff[0], 1)} needed, ${pct(n._eff[1], 1)} allowed</span>` : `${effText(n._eff)} of the portfolio, ${effText(n._share)} of ${esc(parentOf(n).name)}`}`
      + `<br>${m ? `view: the model uses ${pct(m.mean, 1, true)} ± ${pts(m.sd)}` : n.vt ? `<span style="color:var(--att)">view needs − / +</span>` : E ? `no view: equilibrium ${pct(E.m, 1, true)} ± ${pts(E.sd)}` : "no prices yet"}`; }
  return `<b>${esc(n.name)}</b>${n === ROOT ? "" : `<br>can take ${bad(n) ? `<span style="color:var(--att)">nothing: ${pct(n._eff[0], 1)} needed, ${pct(n._eff[1], 1)} allowed</span>` : `${effText(n._eff)} of the portfolio`}`}<br>${retText(n)}`;
}

// the verdict's sign, drawn rather than typed, so it never depends on a font's glyphs
const MARK = { ok: `<svg class="mk" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 7.5 5.5 11 12 3.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  no: `<svg class="mk" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3 11 11M11 3 3 11" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>` };

// ---- the shell: Review and run opens the review; Back to the builder returns; Run lives here ---------------
// The review opens even when something blocks: that is where the blockers are named, and Run stays disabled.
let REVIEW = false;
const RV = { draw: null, open: null, close: null };
{ const top = $(".top");
  top.insertAdjacentHTML("beforeend", `<label class="preset rvonly">Portfolio <select id="rv-preset">${$("#preset").innerHTML}</select></label>`
    + `<button class="q rvonly" id="rv-back" type="button">Back to the builder</button><button class="rvonly" id="rv-run" type="button">Run</button>`);
  ["#addg", "#adda", "#undo", "#review"].forEach((s) => $(s).classList.add("bonly")); }
function openReview() { REVIEW = true; document.body.classList.add("reviewing"); $(".top h1").textContent = "Review before the run"; $("#rv-preset").value = $("#preset").value;
  $("#note").textContent = `Returns here are equilibrium at equal weights; the posterior comes with a run. Market data of ${HIST.fetched}. Run goes to ${MACHINE() === "a100" ? `Colab ${colabGPU()}` : "this computer"} (change it on the progress or setup screen). Esc goes back to the builder.`; RV.open?.(); render(true); }
function closeReview(id) { REVIEW = false; document.body.classList.remove("reviewing"); $(".top h1").textContent = "Build the portfolio"; RV.close?.(); if (id) { for (let p = parentOf(find(id)); p; p = parentOf(p)) p.open = true; sel = id; } render(true); }
const _renderNow = renderNow;
renderNow = function (full) {
  _renderNow(full);
  $("#review").disabled = false; $("#review").title = "";
  if (!REVIEW) return;
  const { blocks } = issues();
  $("#state").textContent = blocks.length ? `${blocks.length} thing${blocks.length === 1 ? "" : "s"} block${blocks.length === 1 ? "s" : ""} the run` : "Ready to run";
  $("#rv-run").disabled = !!blocks.length; $("#rv-run").title = blocks.length ? "Blocked: " + blocks.map((b) => b.text).join(" ") : `Runs ${searches().length} searches on ${RUNSET.paths.toLocaleString("en-US")} paths`;
  RV.draw?.();
};
$("#review").addEventListener("click", openReview);
$("#rv-back").addEventListener("click", () => closeReview());
$("#rv-preset").addEventListener("change", (e) => { const s = $("#preset"); s.value = e.target.value; s.dispatchEvent(new Event("change")); });
$("#rv-run").addEventListener("click", async () => {   // save, send the frozen tree to the engine, follow it on the progress screen
  const btn = $("#rv-run"); btn.disabled = true; btn.textContent = "Starting…";
  try {
    await saveNow();
    const options = RUNSET.pathsSet ? { bank: RUNSET.paths } : {};
    if (MACHINE() === "a100") options.gpu = colabGPU();
    const r = await fetch("/api/runs", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ portfolio_id: PF.id, machine: MACHINE(), options }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail && d.detail.blockers ? d.detail.blockers.join(" ") : JSON.stringify(d.detail || d));
    location.href = `results.html?run=${encodeURIComponent(d.id)}#progress`;
  } catch (e) { $("#note").textContent = `The run did not start: ${e.message}`; btn.disabled = false; btn.textContent = "Run"; }
});
document.addEventListener("keydown", (e) => { if (REVIEW && e.key === "Escape" && !e.target.closest?.("input, select")) closeReview(); });
const rvTip = (e, html) => { const t = $("#tip"); if (!html) { t.style.display = "none"; return; } t.innerHTML = html; t.style.display = "block";
  t.style.left = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8) + "px"; t.style.top = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8) + "px"; };
addEventListener("load", () => { if (/review/.test(location.hash)) { sel = ROOT.id; openReview(); } });
// a link to #review on the page already open (no reload) opens the review too
addEventListener("hashchange", () => { if (/review/.test(location.hash) && !REVIEW) { sel = ROOT.id; openReview(); } });
