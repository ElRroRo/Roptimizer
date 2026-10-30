// ---- Round 11: three takes on Progress and on Compare, switched in the panel header, and the Diagnostics fixes.
// Progress replays the real run's record (bank, then each search's generations in post-order) at speed; nothing
// is invented, the replay only moves a clock over the times the run logged.
const PV = { mode: "rings", t: null, anim: null }, CV = { mode: "bells" };   // the owner's picks from round 11 open first
let SCHED = (() => { const S = []; const post = (r) => { kids(R0, r).forEach(post); if (r.kind === "group" && r.path.length >= 0 && r.search) S.push(r); }; post(R0.rows[0]);
  let t = DATA.bank_build_s; return S.map((r) => { const d = r.search.wall_s || 0, o = { r, t0: t, t1: t + d, g: r.search.generations }; t += d; return o; }); })();
let T_END = SCHED[SCHED.length - 1].t1;
let now = () => (PV.t == null ? T_END : PV.t);
let fracOf = (s) => (s.g === 0 ? (now() >= s.t0 ? 1 : 0) : Math.max(0, Math.min(1, (now() - s.t0) / Math.max(1e-6, s.t1 - s.t0))));
let stateOf = (s) => (s.g === 0 ? (now() >= s.t0 ? "one" : "wait") : now() >= s.t1 ? "done" : now() > s.t0 ? "run" : "wait");
const wrap2 = (a) => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
const clock = (v) => (v < 60 ? `${v.toFixed(0)} s` : `${Math.floor(v / 60)}:${String(Math.round(v % 60)).padStart(2, "0")}`);
const segHTML = (key, opts, cur) => `<span class="seg" role="group" aria-label="Layout">${opts.map(([k, l]) => `<button type="button" data-${key}="${k}" aria-pressed="${k === cur}">${l}</button>`).join("")}</span>`;

function progressHead() {
  const ph = $("#p-gantt").parentElement.querySelector(".ph");
  ph.innerHTML = `<b>Searches</b><span>${({ bars: "one bar per search, inside out; a tick per generation, length = time", rings: "the tree; each subportfolio's ring fills as its search runs", levels: "levels side by side, deepest first; each level waits for the one below" })[PV.mode]}</span>`
    + `<button class="act" type="button" id="replay">${PV.anim ? "Stop replay" : "Replay at 10×"}</button>`;   // rings chosen (round 12); bars and levels stay in the code for the record
}
progress = function () { progressHead(); progressChart(); runPanel(); };
function progressChart() { const el = $("#p-gantt"), W = el.clientWidth, H = el.clientHeight; el.innerHTML = PV.mode === "bars" ? pBars(W, H) : PV.mode === "rings" ? pRings(W, H) : pLevels(W, H); }
function progressTick() {   // a frame of the replay: redraw the chart, update the run panel's text in place (rebuilding it would eat clicks on Cancel)
  progressChart();
  const cur = SCHED.find((q) => stateOf(q) === "run"), live = PV.t != null && PV.t < T_END, set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("#st-bank", now() < DATA.bank_build_s ? "building…" : `${DATA.config.bank.toLocaleString("en-US")} paths in ${DATA.bank_build_s} s`);
  set("#st-search", cur ? `${cur.r.name}: generation ${Math.max(1, Math.ceil(fracOf(cur) * cur.g))} of ${cur.g}` : `${SCHED.filter((q) => q.g).length}, inside out, ${Math.round(d3.sum(SCHED, (q) => q.r.search.wall_s || 0))} s`);
  set("#st-time", `${clock(now())}${live ? ` of ${clock(T_END)}` : " in all"}`);
  $("#prog-sub").textContent = live ? `replay of the ${when(R0.finished).slice(11)} run at 10×` : `finished ${when(R0.finished)}`;
  const c = $("#cancel"); if (c) { c.disabled = !live; c.title = live ? "Stop the run" : "Nothing is running"; }
}
function pBars(W, H) {
  const m = { l: 150, r: 104, t: 26, b: 28 }, bank = DATA.bank_build_s, x = d3.scaleLinear().domain([0, T_END]).range([m.l, W - m.r]), rh = Math.min(52, (H - m.t - m.b) / (SCHED.length + 1)), t = now();
  let s = `<text class="lbl" x="${m.l - 10}" y="${m.t + rh / 2 + 4}" text-anchor="end">Scenario bank</text><rect x="${x(0)}" y="${m.t + 6}" width="${Math.max(0, x(Math.min(t, bank)) - x(0))}" height="${rh - 12}" fill="var(--frame-2)"/>${t >= bank ? `<text x="${x(bank) + 6}" y="${m.t + rh / 2 + 4}">${bank} s</text>` : ""}`;
  SCHED.forEach((sc, i) => { const y = m.t + (i + 1) * rh, c = colorOf(sc.r), st = stateOf(sc), f = fracOf(sc), x1 = x(sc.t0 + (sc.t1 - sc.t0) * f);
    s += `<text class="lbl" x="${m.l - 10}" y="${y + rh / 2 + 4}" text-anchor="end" style="${st === "wait" ? "fill:var(--mute)" : ""}">${esc(sc.r.name)}</text>`;
    if (sc.g === 0) { s += `<text x="${x(sc.t0) + 4}" y="${y + rh / 2 + 4}" class="mu">one member: 100%, no search</text>`; return; }
    s += `<rect x="${x(sc.t0)}" y="${y + 6}" width="${x(sc.t1) - x(sc.t0)}" height="${rh - 12}" fill="none" stroke="var(--frame)" stroke-dasharray="2 2"/><rect x="${x(sc.t0)}" y="${y + 6}" width="${Math.max(0, x1 - x(sc.t0))}" height="${rh - 12}" fill="color-mix(in oklab, ${c} 60%, var(--panel))"/>`;
    for (let k = 1; k < Math.floor(f * sc.g + 1e-9); k++) s += `<line x1="${x(sc.t0 + ((sc.t1 - sc.t0) * k) / sc.g)}" x2="${x(sc.t0 + ((sc.t1 - sc.t0) * k) / sc.g)}" y1="${y + 6}" y2="${y + rh - 6}" stroke="var(--panel)" stroke-width="0.8"/>`;
    s += `<text x="${x(sc.t1) + 6}" y="${y + rh / 2 + 4}" class="${st === "wait" ? "mu" : ""}">${st === "done" ? `${sc.g} gen, ${sc.search?.wall_s ?? sc.r.search.wall_s} s` : st === "run" ? `generation ${Math.max(1, Math.ceil(f * sc.g))} of ${sc.g}` : "waits"}</text>`; });
  if (PV.t != null) s += `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t - 6}" y2="${H - m.b}" stroke="var(--att)" stroke-width="1.5"/>`;
  x.ticks(6).forEach((v) => s += `<line x1="${x(v)}" x2="${x(v)}" y1="${m.t - 4}" y2="${H - m.b}" stroke="var(--frame)" stroke-dasharray="2 3"/><text x="${x(v)}" y="${H - m.b + 14}" text-anchor="middle">${clock(v)}</text>`);
  return svg(W, H, s);
}
function pRings(W, H) {   // the builder's radial tree: each subportfolio band is a progress ring
  const cx = W / 2, cy = H / 2 + 6, R = Math.min(W, H) / 2 - 50, root = d3.hierarchy(R0.rows[0], (r) => (r.kind === "group" ? kids(R0, r) : null)), leaves = root.leaves(), step = 2 * Math.PI / leaves.length, Hh = root.height;
  leaves.forEach((d, i) => { d.a = step * (i + 0.5); d.lo = d.hi = d.a; });
  root.eachAfter((d) => { if (d.children) { d.lo = d.children[0].lo; d.hi = d.children[d.children.length - 1].hi; d.a = (d.lo + d.hi) / 2; } });
  const rad = (k) => (k === 0 ? 0 : R * (0.26 + (0.62 * (k - 1)) / Math.max(1, Hh - 1))), P = (a, r) => [cx + r * Math.sin(a), cy - r * Math.cos(a)], by = new Map(SCHED.map((s) => [idOf(s.r), s]));
  let s = "";
  root.descendants().forEach((d) => { if (!d.depth) return; const r = d.data, c = colorOf(r), [x0, y0] = P(d.a, d.parent.depth ? rad(d.parent.depth) + 9 : 12), [x1, y1] = P(d.a, r.kind === "group" ? rad(d.depth) - 9 : R - 5);
    s += `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="color-mix(in oklab, ${c} 60%, var(--panel))" stroke-width="1.5"/>`; });   // the builder's branch tint
  root.descendants().forEach((d) => { const r = d.data; if (r.kind !== "group" || !d.depth) return; const c = colorOf(r), sc = by.get(idOf(r)), st = stateOf(sc), f = fracOf(sc), a0 = d.lo - step * 0.42, a1 = d.hi + step * 0.42, rr = rad(d.depth);
    const band = (b, e) => d3.arc().innerRadius(rr - 8).outerRadius(rr + 8).startAngle(b).endAngle(e)();
    // the builder's band: 30% of the group colour on the panel; still to search = an outline, searching = filling up to the magenta head
    s += `<path d="${band(a0, a1)}" transform="translate(${cx},${cy})" fill="${st === "one" || st === "done" ? `color-mix(in oklab, ${c} 30%, var(--panel))` : `color-mix(in oklab, ${c} 8%, var(--panel))`}" stroke="${st === "wait" ? `color-mix(in oklab, ${c} 55%, var(--frame-2))` : "var(--panel)"}" stroke-width="1.5" stroke-dasharray="${st === "wait" ? "3 3" : ""}"/>`;
    if (sc.g && st === "run") s += `<path d="${band(a0, a0 + (a1 - a0) * f)}" transform="translate(${cx},${cy})" fill="color-mix(in oklab, ${c} 30%, var(--panel))"/>`;
    if (st === "run") { const [px, py] = P(a0 + (a1 - a0) * f, rr); s += `<circle cx="${px}" cy="${py}" r="4" fill="var(--att)"/>`; }
    const rev = wrap2(d.a) > Math.PI / 2 && wrap2(d.a) < 1.5 * Math.PI, rt = rr + (rev ? 4 : -4), [x0, y0] = P(rev ? a1 : a0, rt), [x1, y1] = P(rev ? a0 : a1, rt), pid = "pr" + idOf(r).replace(/[^A-Za-z0-9]/g, "");
    if (rt * (a1 - a0) > r.name.length * 6.6) s += `<path id="${pid}" d="M${x0},${y0} A${rt},${rt} 0 ${a1 - a0 > Math.PI ? 1 : 0} ${rev ? 0 : 1} ${x1},${y1}" fill="none"/><text class="lbl" style="font-size:11px;paint-order:stroke;stroke:var(--panel);stroke-width:3px;${st === "wait" ? "fill:var(--mute)" : ""}"><textPath href="#${pid}" startOffset="50%" text-anchor="middle">${esc(r.name)}</textPath></text>`; });
  leaves.forEach((d) => { const r = d.data; if (r.kind !== "asset") return; const [x, y] = P(d.a, R), c = colorOf(r), [tx, ty] = P(d.a, R + 10); let deg = (d.a * 180) / Math.PI - 90; const flip = deg > 90 && deg < 270; if (flip) deg -= 180;
    s += `<circle cx="${x}" cy="${y}" r="3.5" fill="${c}"/><text x="${tx}" y="${ty}" transform="rotate(${deg} ${tx} ${ty})" text-anchor="${flip ? "end" : "start"}" dy="3.5" style="fill:${lit(c)}">${r.name}</text>`; });
  const top = by.get("Portfolio"), st = stateOf(top), cur = SCHED.find((q) => stateOf(q) === "run");
  s += `<circle cx="${cx}" cy="${cy}" r="11" fill="var(--panel)" stroke="${st === "done" ? "var(--ink)" : "var(--ink-2)"}" stroke-width="2.5"/><text class="lbl" x="${cx}" y="${cy + 30}" text-anchor="middle">${clock(now())}${cur ? `, ${esc(cur.r.name)}` : now() < DATA.bank_build_s ? ", building the bank" : st === "done" ? ", done" : ""}</text>`;
  return svg(W, H, s);
}
function pLevels(W, H) {   // one column per level, deepest first: a level's searches wait for the level below
  const depth = (r) => r.path.length, lv = [...new Set(SCHED.map((s) => depth(s.r)))].sort((a, b) => b - a), cw = (W - 24) / lv.length, ch = 64;
  let s = "";
  lv.forEach((L, i) => { const x0 = 12 + i * cw, list = SCHED.filter((q) => depth(q.r) === L);
    s += `<text class="lbl" x="${x0 + 6}" y="22">${L === 0 ? "The Portfolio" : `Level ${L + 1}`}</text><text x="${x0 + 6}" y="38" class="mu">${list.filter((q) => q.g).length} search${list.filter((q) => q.g).length === 1 ? "" : "es"}${list.some((q) => !q.g) ? `; ${list.filter((q) => !q.g).map((q) => q.r.name).join(", ")} has one member` : ""}</text>`;
    if (i < lv.length - 1) s += `<path d="M${x0 + cw - 12},${H / 2} l8,0 m-4,-4 l4,4 l-4,4" fill="none" stroke="var(--frame-2)" stroke-width="1.5"/>`;
    list.forEach((sc, j) => { const y = 52 + j * (ch + 10), c = colorOf(sc.r), st = stateOf(sc), f = fracOf(sc), w = cw - 28;
      s += `<rect x="${x0 + 4}" y="${y}" width="${w}" height="${ch}" rx="3" fill="var(--panel-2)" stroke="${st === "run" ? "var(--att)" : "var(--frame)"}"/><rect x="${x0 + 4}" y="${y}" width="3" height="${ch}" fill="${c}"/>`
        + `<text class="lbl" x="${x0 + 16}" y="${y + 20}" style="${st === "wait" ? "fill:var(--mute)" : ""}">${esc(sc.r.name)}</text><text x="${x0 + w - 4}" y="${y + 20}" text-anchor="end" class="${st === "wait" ? "mu" : ""}">${st === "one" ? "100%, no search" : st === "done" ? `${sc.g} gen, ${sc.r.search.wall_s} s` : st === "run" ? `gen ${Math.max(1, Math.ceil(f * sc.g))} of ${sc.g}` : "waits"}</text>`;
      if (sc.g) { const bw = w - 24; s += `<rect x="${x0 + 16}" y="${y + 36}" width="${bw}" height="10" rx="2" fill="var(--panel)" stroke="var(--frame)"/><rect x="${x0 + 16}" y="${y + 36}" width="${bw * f}" height="10" rx="2" fill="color-mix(in oklab, ${c} 65%, var(--panel))"/>`;
        for (let k = 1; k < sc.g; k++) s += `<line x1="${x0 + 16 + (bw * k) / sc.g}" x2="${x0 + 16 + (bw * k) / sc.g}" y1="${y + 36}" y2="${y + 46}" stroke="var(--panel)" stroke-width="1"/>`; } }); });
  return svg(W, H, s);
}
function runPanel() {
  const total = d3.sum(SCHED, (q) => q.r.search.wall_s || 0), cur = SCHED.find((q) => stateOf(q) === "run"), live = PV.t != null && PV.t < T_END;
  $("#prog-sub").textContent = live ? `replay of the ${when(R0.finished).slice(11)} run at 10×` : `finished ${when(R0.finished)}`;
  $("#p-run").innerHTML = `<div class="machines" role="group" aria-label="Where the next run goes">
      <button class="mach" type="button" data-m="laptop" aria-pressed="${MACH === "laptop"}"><b>This computer${LIVE.device ? `, ${esc(LIVE.device)}` : ""}</b><span>as many paths as fit: up to 2,000,000 on an NVIDIA GPU, 400,000 on a CPU; free</span></button>
      <button class="mach" type="button" data-m="a100" aria-pressed="${MACH === "a100"}"><b>Colab ${colabGPU()}</b><span>up to 30,000,000 paths kept on the rented GPU; about a minute to start; set it up and pick the GPU on the <a href="setup.html" style="color:inherit">setup screen</a></span></button></div>
    <ul class="stages"><li><b>Data and fits</b><span>reused from the snapshot of ${when(DATA.inputs_created)}</span></li>
      <li><b>Scenario bank</b><span id="st-bank">${now() < DATA.bank_build_s ? "building…" : `${DATA.config.bank.toLocaleString("en-US")} paths in ${DATA.bank_build_s} s`}</span></li>
      <li><b>Searches</b><span id="st-search">${cur ? `${esc(cur.r.name)}: generation ${Math.max(1, Math.ceil(fracOf(cur) * cur.g))} of ${cur.g}` : `${SCHED.filter((q) => q.g).length}, inside out, ${Math.round(total)} s`}</span></li>
      <li><b>Figures</b><span>on ${R0.validation_paths.toLocaleString("en-US")} paths no search saw</span></li><li><b>Time</b><span id="st-time">${clock(now())}${live ? ` of ${clock(T_END)}` : " in all"}</span></li></ul>
    <div class="runbtns"><button class="go" type="button" id="again">Run again</button><button class="stop" type="button" id="cancel"${live ? "" : " disabled"} title="${live ? "Stop the run" : "Nothing is running"}">Cancel</button></div>
    <p class="note">While a run is going, this panel and the chart move live and Cancel stops it; on Colab, Cancel always shuts the machine down. Runs continue in the background, one per machine.</p>`;
}
function replay() {
  if (PV.anim) { cancelAnimationFrame(PV.anim); PV.anim = null; PV.t = null; progress(); return; }
  PV.anim = -1;   // marks the replay as running before the first frame, so the header says Stop replay
  const t0 = performance.now(); PV.t = 0;
  const tick = (ts) => { PV.t = Math.min(T_END, ((ts - t0) / 1000) * 10); if (view === "progress") progressTick(); PV.anim = PV.t < T_END ? requestAnimationFrame(tick) : (PV.t = null, null); if (!PV.anim && view === "progress") progress(); };
  progress(); PV.anim = requestAnimationFrame(tick);
}

// ---- Compare, three takes ------------------------------------------------------------------------------
const _compare = compare;
compare = function () {
  const host = $("#p-ctab"), ph = host.parentElement.querySelector(".ph");
  ph.innerHTML = `<b>Change</b><span id="cmp-sub">${({ table: "this run against the baseline, signed, in points", bells: "effective weight, baseline (ring) to this run (dot), one scale", share: "each part's share of its parent: which level's decision moved", lanes: "weight and what it adds to expected return, baseline (ring) to this run (dot)", ribbons: "the whole portfolio, baseline on the left, this run on the right" })[CV.mode]}</span>` + segHTML("cv", [["bells", "Weight"], ["share", "Share of parent"]], CV.mode);   // the owner keeps both (round 12)
  _compare();   // what changed and the fans stay the same in every take
  ph.querySelector("span").textContent = ({ table: "this run against the baseline, signed, in points", bells: "effective weight, baseline (ring) to this run (dot), one scale", share: "each part's share of its parent: which level's decision moved", lanes: "weight and what it adds to expected return, baseline (ring) to this run (dot)", ribbons: "the whole portfolio, baseline on the left, this run on the right" })[CV.mode];
  if (CV.mode === "bells") host.innerHTML = cBells(host.clientWidth, host.clientHeight, ["eff"]);
  if (CV.mode === "share") host.innerHTML = cBells(host.clientWidth, host.clientHeight, ["share"]);
  if (CV.mode === "lanes") host.innerHTML = cBells(host.clientWidth, host.clientHeight, ["eff", "contrib"]);
  if (CV.mode === "ribbons") host.innerHTML = cRibbons(host.clientWidth, host.clientHeight);
};
// dumbbells: one lane per measure, baseline (ring) to this run (dot), the change in points at the lane's right edge
const LANES = {
  eff: { label: "Effective weight", get: (r) => r.effective, sqrt: true, fmt: (v) => p1(v) },
  share: { label: "Share of its parent", get: (r) => r.share, fmt: (v) => p1(v) },
  contrib: { label: "Adds to 12-week expected return, points", get: (r) => r.effective * r.metrics.er_12w, fmt: (v) => pct(v, 2, true), dp: 2 },
};
function cBells(W, H, keys) {
  const rows = R0.rows.filter((r) => r.path.length), top = 44, RH = Math.max(18, Math.min(27, (H - top - 120) / rows.length)), nameW = 150, laneW = (W - nameW - 10) / keys.length;
  let s = "";
  keys.forEach((k, li) => { const L = LANES[k], x0 = nameW + li * laneW + 8, x1 = x0 + laneW - 64, vals = rows.flatMap((a) => [L.get(a), L.get(M1.get(idOf(a)))]);
    const x = L.sqrt ? d3.scaleSqrt().domain([0, 1]).range([x0, x1]) : d3.scaleLinear().domain([Math.min(0, d3.min(vals)), d3.max(vals)]).nice().range([x0, x1]);
    const ticks = L.sqrt ? [0, 0.01, 0.05, 0.1, 0.25, 0.5, 1] : x.ticks(4);
    s += `<text class="lbl" x="${x0}" y="14" style="font-size:11.5px">${L.label}</text>` + ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 4}" y2="${top + rows.length * RH}" stroke="${t === 0 ? "var(--frame-2)" : "var(--frame)"}"/><text x="${x(t)}" y="${top - 9}" text-anchor="middle">${L.sqrt ? (t === 1 ? "100%" : Math.round(t * 100)) : (t * 100).toFixed(L.dp ? 1 : 0)}</text>`).join("");
    rows.forEach((a, i) => { const b = M1.get(idOf(a)), y = top + i * RH + RH / 2, c = colorOf(a), g = a.kind === "group", va = L.get(a), vb = L.get(b), d = vb - va, moved = Math.abs(d) > 5e-5;
      s += `<line x1="${x(va)}" x2="${x(vb)}" y1="${y}" y2="${y}" stroke="${moved ? (d > 0 ? "var(--up)" : "var(--down)") : "var(--frame-2)"}" stroke-width="${g ? 3 : 2}"/>`
        + `<circle cx="${x(va)}" cy="${y}" r="${g ? 4.5 : 3.5}" fill="var(--panel)" stroke="${c}" stroke-width="1.6"/><circle cx="${x(vb)}" cy="${y}" r="${g ? 4.5 : 3.5}" fill="${c}"/>`
        + `<text x="${x0 + laneW - 14}" y="${y + 4}" text-anchor="end" style="fill:${moved ? (d > 0 ? "var(--up)" : "var(--down)") : "var(--mute)"}">${moved ? (d > 0 ? "▲ +" : "▼ " + MINUS) + Math.abs(d * 100).toFixed(2) : "0.00"}</text>`; });
    if (li) s += `<line x1="${x0 - 8}" x2="${x0 - 8}" y1="4" y2="${top + rows.length * RH}" stroke="var(--frame-2)"/>`; });
  rows.forEach((a, i) => { const y = top + i * RH + RH / 2, id = idOf(a), g = a.kind === "group";
    s = `<rect class="hit" x="0" y="${y - RH / 2}" width="${W}" height="${RH}" fill="${id === sel ? "color-mix(in oklab, var(--att) 12%, transparent)" : "transparent"}" data-r="${esc(id)}"/>` + s
      + `<text x="${10 + 13 * (a.path.length - 1)}" y="${y + 4}" class="${g ? "lbl" : ""}" style="${g ? "font-size:12px" : `fill:${lit(colorOf(a))}`}">${esc(a.name)}</text>`; });
  const pa = R0.rows[0].metrics, pb = R1.rows[0].metrics, y0 = top + rows.length * RH + 30;
  const met = [["Expected", pa.er_12w, pb.er_12w, 2], ["CVaR", pa.cvar, pb.cvar, 1], ["CDaR", pa.cdar, pb.cdar, 1], ["UPI", pa.upi, pb.upi, 3, true]];
  s += `<text class="lbl" x="10" y="${y0 - 10}">The Portfolio</text>`;
  met.forEach(([k, a, b, dp, raw], i) => { const y = y0 + i * 20, lo = Math.min(a, b), hi = Math.max(a, b), pad = (hi - lo) * 1.5 + 1e-4, sx = d3.scaleLinear().domain([lo - pad, hi + pad]).range([nameW + 8, W - 96]), better = b > a;
    s += `<text x="10" y="${y + 4}">${k}</text><line x1="${sx(a)}" x2="${sx(b)}" y1="${y}" y2="${y}" stroke="${better ? "var(--up)" : "var(--down)"}" stroke-width="2"/><circle cx="${sx(a)}" cy="${y}" r="3.5" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"/><circle cx="${sx(b)}" cy="${y}" r="3.5" fill="var(--ink)"/>`
      + `<text x="${sx(a) + (a < b ? -6 : 6)}" y="${y + 4}" text-anchor="${a < b ? "end" : "start"}" class="mu">${raw ? num(a, dp) : pct(a, dp, true)}</text><text x="${sx(b) + (a < b ? 6 : -6)}" y="${y + 4}" text-anchor="${a < b ? "start" : "end"}">${raw ? num(b, dp) : pct(b, dp, true)}</text>`
      + `<text x="${W - 10}" y="${y + 4}" text-anchor="end" style="fill:${better ? "var(--up)" : "var(--down)"}">${b > a ? "▲ +" : "▼ " + MINUS}${raw ? Math.abs(b - a).toFixed(dp) : Math.abs((b - a) * 100).toFixed(dp)}</text>`; });
  return svg(W, Math.max(H, y0 + met.length * 20 + 10), s);
}
function cRibbons(W, H) {   // two stacked columns of the whole portfolio, the same asset joined by a ribbon
  const A = R0.rows.filter((r) => r.kind === "asset" && (r.effective > 1e-4 || M1.get(idOf(r)).effective > 1e-4)), m = { t: 30, b: 20 }, cw = 64, xl = 150, xr = W - 150 - cw, Hh = H - m.t - m.b, gap = 2;
  const stack = (run) => { let y = m.t; const M = byId(run), out = new Map(); A.forEach((r) => { const h = M.get(idOf(r)).effective * (Hh - gap * A.length); out.set(idOf(r), [y, y + h]); y += h + gap; }); return out; };
  const L = stack(R0), Rr = stack(R1);
  let s = `<text class="lbl" x="${xl + cw / 2}" y="18" text-anchor="middle">Baseline</text><text class="lbl" x="${xr + cw / 2}" y="18" text-anchor="middle">This run</text>`;
  A.forEach((r) => { const id = idOf(r), [a0, a1] = L.get(id), [b0, b1] = Rr.get(id), c = colorOf(r), on = id === sel, mx = (xl + cw + xr) / 2, d = M1.get(id).effective - r.effective;
    s += `<path class="hit" d="M${xl + cw},${a0} C${mx},${a0} ${mx},${b0} ${xr},${b0} L${xr},${b1} C${mx},${b1} ${mx},${a1} ${xl + cw},${a1} Z" fill="${c}" fill-opacity="${on ? 0.55 : 0.22}" data-r="${esc(id)}"/>`
      + `<rect x="${xl}" y="${a0}" width="${cw}" height="${Math.max(0.5, a1 - a0)}" fill="color-mix(in oklab, ${c} 62%, var(--panel))"/><rect x="${xr}" y="${b0}" width="${cw}" height="${Math.max(0.5, b1 - b0)}" fill="color-mix(in oklab, ${c} 62%, var(--panel))"/>`;
    if (a1 - a0 > 10) s += `<text x="${xl - 6}" y="${(a0 + a1) / 2 + 3.5}" text-anchor="end" style="fill:${lit(c)}">${r.name} ${p1(r.effective)}</text>`;
    if (b1 - b0 > 10) s += `<text x="${xr + cw + 6}" y="${(b0 + b1) / 2 + 3.5}" style="fill:${lit(c)}">${p1(M1.get(id).effective)} <tspan style="fill:${Math.abs(d) < 5e-5 ? "var(--mute)" : d > 0 ? "var(--up)" : "var(--down)"}">${Math.abs(d) < 5e-5 ? "" : (d > 0 ? "▲ +" : "▼ " + MINUS) + Math.abs(d * 100).toFixed(1)}</tspan></text>`; });
  return svg(W, H, s);
}

// ---- Diagnostics: readable labels, a legend on every chart, and "did each search settle?" ---------------------
const _diag = diag;
diag = function () {
  const set = (id, title, sub) => { const ph = $(id).parentElement.querySelector(".ph"); ph.innerHTML = `<b>${title}</b><span>${sub}</span>`; };
  set("#p-post", "Posterior vs simulated", "12-week mean per asset");
  set("#p-hist", "Did each search settle?", "a dot per generation; small dots at the end = settled");
  set("#p-sim", "Simulated vs history", "12-week returns per asset");
  set("#p-heston", "Volatility model", "Heston per asset");
  set("#p-betas", "Crash betas", "surprise-day β and how it was estimated");
  set("#p-jumps", "Jumps", "from the jump calibration");
  _diag();
  { $("#p-post").insertAdjacentHTML("beforeend", `<div class="legend lg-bottom"><span><i style="width:2px;height:11px;background:var(--ink)"></i>posterior, what the views and equilibrium imply</span><span><i style="width:8px;height:8px;border-radius:50%;background:var(--ink-2)"></i>simulated mean</span></div>`); }
  { // one row per search: a dot per generation, its area = how much that generation improved the best score; the
    // last five are bracketed, and the search stops once those five add less than 0.0002 together
    const el = $("#p-hist"), W = el.clientWidth, H = el.clientHeight, S = SCHED.filter((q) => q.g), TOL = DATA.config.tol, win = DATA.config.window;
    const maxG = d3.max(S, (q) => q.g), m = { l: 128, r: 150, t: 30, b: 46 }, rh = Math.min(40, (H - m.t - m.b) / S.length), x = d3.scaleLinear().domain([1, maxG]).range([m.l + 10, W - m.r]);
    const gainsAll = S.flatMap((q) => { const h = q.r.search.history; return h.slice(1).map((v, k) => Math.max(0, h[k] - v)); }), big = d3.max(gainsAll) || 1;
    const rad = d3.scaleSqrt().domain([0, big]).range([1.6, Math.min(13, rh / 2 - 2)]);
    let s = `<text x="${x(1)}" y="${m.t - 14}" text-anchor="middle" class="mu">gen 1</text><text x="${x(maxG)}" y="${m.t - 14}" text-anchor="middle" class="mu">gen ${maxG}</text>`;
    S.forEach((q, i) => { const h = q.r.search.history, y = m.t + i * rh + rh / 2, c = colorOf(q.r), last = h.length > win ? h[h.length - 1 - win] - h[h.length - 1] : h[0] - h[h.length - 1], ok = last < TOL;
      s += `<rect class="hit" x="0" y="${y - rh / 2}" width="${W}" height="${rh}" fill="transparent" data-tipx="${esc(`${q.r.name}: ${q.g} generations. The first ones improved its best score by ${(h[0] - h[Math.min(2, h.length - 1)]).toFixed(5)}; the last ${win} together by ${Math.max(0, last).toFixed(5)}${last < 0 ? " (fresh paths moved it back a little)" : ""}, under the 0.0002 that stops a search.`)}"/>`
        + `<text class="lbl" x="${m.l - 8}" y="${y + 4}" text-anchor="end" style="font-size:12px">${esc(q.r.name)}</text><line x1="${x(1)}" x2="${x(q.g)}" y1="${y}" y2="${y}" stroke="var(--frame-2)"/>`;
      const a = Math.max(1, q.g - win + 1); s += `<path d="M${x(a) - 9},${y - rh / 2 + 5} v-3 H${x(q.g) + 9} v3" fill="none" stroke="var(--ink-2)" stroke-width="1"/>`;
      h.forEach((v, k) => { const g = k === 0 ? 0 : Math.max(0, h[k - 1] - v); s += k === 0 ? `<circle cx="${x(1)}" cy="${y}" r="2.5" fill="var(--ink-2)"/>` : `<circle cx="${x(k + 1)}" cy="${y}" r="${rad(g)}" fill="${c}" fill-opacity="${k + 1 >= a ? 0.95 : 0.6}"/>`; });
      s += `<text x="${W - m.r + 14}" y="${y + 4}" style="fill:${ok ? "var(--ink)" : "var(--att)"}">${ok ? "settled" : "still improving"} <tspan class="mu">at gen ${q.g}</tspan></text>`; });
    el.innerHTML = svg(W, H - 40, s) + `<div class="legend lg-bottom"><span><i style="width:10px;height:10px;border-radius:50%;background:var(--ink-2)"></i>bigger dot = that generation improved the best score more</span><span><i style="width:16px;height:6px;border:1px solid var(--ink-2);border-bottom:0"></i>last 5: together under 0.0002, so it stopped</span></div>`; }
  { const el = $("#p-sim"); el.insertAdjacentHTML("beforeend", `<div class="legend lg-bottom"><span><i style="width:14px;height:9px;background:color-mix(in oklab, var(--ink-2) 40%, transparent)"></i>simulated, ${R0.validation_paths.toLocaleString("en-US")} paths</span><span><i style="width:16px;border-top:1.5px solid var(--ink)"></i>history: every 12-week window of the last 5 years</span></div>`); }
};
document.addEventListener("click", (e) => {
  const pv = e.target.closest("[data-pv]"); if (pv) { PV.mode = pv.dataset.pv; progress(); return; }
  const cv = e.target.closest("[data-cv]"); if (cv) { CV.mode = cv.dataset.cv; compare(); return; }
  if (e.target.closest("#replay")) { replay(); return; }
  if (e.target.closest("#cancel") && PV.anim) { cancelAnimationFrame(PV.anim); PV.anim = null; PV.t = null; $("#note").textContent = "Replay stopped. On a real run, Cancel stops the search and, on the A100, shuts the machine down."; progress(); }
});
// hash routes for the rating page: #progress-rings, #compare-ribbons and so on
{ const h = location.hash.slice(1), [v, mode] = h.split("-"); if (mode && v === "progress") PV.mode = mode; if (mode && v === "compare") CV.mode = mode;
  if (mode && (v === "progress" || v === "compare")) view = v; }
// the rating page switches screens by changing only the hash, which does not reload the page
addEventListener("hashchange", () => { const [v, mode] = location.hash.slice(1).split("-"); if (!["progress", "results", "builder", "compare", "diag"].includes(v)) return;
  if (mode && v === "progress") PV.mode = mode; if (mode && v === "compare") CV.mode = mode; view = v; draw(); });
