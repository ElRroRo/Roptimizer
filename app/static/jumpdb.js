// ---- Jump data. The pool is the real default from jump_paremeters.py; the parameters are the calibration inside the
// frozen reference inputs; the betas are the surprise-day study's. Only one version exists so far: the jump
// database (ticket #9) adds a dated version per recalibration, so this screen shows that one and says so.
const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const svg = (w, h, inner) => `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${inner}</svg>`;
const PALETTE = ["#e0af68", "#bb9af7", "#9ece6a", "#f7768e", "#7dcfff", "#ff9e64", "#73daca", "#7aa2f7"];
const ROWS = DATA.runs[0].rows, TOPS = ROWS.filter((r) => r.path.length === 1).map((r) => r.name);
const colorOf = (r) => PALETTE[TOPS.indexOf(r.path[1])] ?? "var(--ink-2)";
const HELD = ROWS.filter((r) => r.kind === "asset");
const VERSION = DATA.inputs_created.slice(0, 10), TODAY = DATA.created.slice(0, 10);
const ageDays = Math.round((new Date(TODAY) - new Date(VERSION)) / 864e5);
const tip = (e, html) => { const t = $("#tip"); if (!html) { t.style.display = "none"; return; } t.innerHTML = html; t.style.display = "block";
  t.style.left = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8) + "px"; t.style.top = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8) + "px"; };
$("#meta").textContent = `In use: version ${INUSE}${PINNED ? `, pinned for ${PF_.name}` : ", the newest"}, ${ageDays} day${ageDays === 1 ? "" : "s"} old${ageDays > 90 ? ": STALE, recalibrate" : ""}`;
$("#note").textContent = `Pool edits save as you make them and take effect at the next recalibration. Overrides apply to the ticker in every portfolio and survive recalibration. Betas for ${PF_.name}.`;

// ---- the pool: sectors as bars, the chosen sector's tickers as chips -------------------------------------------
const OUT = new Set(), ADDED = new Map();   // dropped tickers; added ticker -> sector
{ const now = new Set(POOLNOW.tickers), def = new Set(POOL_DEFAULT.flatMap((s) => s.tickers));
  def.forEach((t) => { if (!now.has(t)) OUT.add(t); });
  POOLNOW.tickers.forEach((t) => { if (!def.has(t)) ADDED.set(t, POOL_DEFAULT.length - 1); }); }
let poolTimer = null;
function savePool() { clearTimeout(poolTimer); poolTimer = setTimeout(async () => {
  const tickers = uniq().filter(([t]) => !OUT.has(t)).map(([t]) => t);
  const r = await fetch("/api/jumpdb/pool", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ tickers }) });
  $("#note").textContent = r.ok ? `Pool saved: ${tickers.length} tickers; it applies at the next recalibration.` : `Pool not saved: ${(await r.json()).detail}`; }, 500); }
let SECTOR = 0;
const uniq = () => { const seen = new Set(), out = []; POOL_DEFAULT.forEach((s, i) => s.tickers.concat([...ADDED].filter(([, k]) => k === i).map(([t]) => t)).forEach((t) => { if (!seen.has(t)) { seen.add(t); out.push([t, i]); } })); return out; };
function pool(id = "#p-pool") {
  const all = uniq(), active = all.filter(([t]) => !OUT.has(t)), el = $(id), W = el.clientWidth, dupes = 407 - 406;
  el.parentElement.querySelector(".ph span").textContent = `${active.length} tickers${OUT.size ? `, ${OUT.size} dropped` : ""}${ADDED.size ? `, ${ADDED.size} added` : ""}; the systematic layer uses ${POOL_SYSTEMATIC}`;
  const counts = POOL_DEFAULT.map((s, i) => ({ s, i, n: all.filter(([t, k]) => k === i && !OUT.has(t)).length, out: all.filter(([t, k]) => k === i && OUT.has(t)).length }));
  const rh = 22, m = { l: 168, r: 40, t: 8 }, x = d3.scaleLinear().domain([0, d3.max(counts, (c) => c.n + c.out)]).range([m.l, W - m.r]), H = m.t + counts.length * rh + 6;
  let s = "";
  counts.forEach((c, j) => { const y = m.t + j * rh, on = c.i === SECTOR;
    s += `<rect class="hit" x="0" y="${y}" width="${W}" height="${rh}" fill="${on ? "color-mix(in oklab, var(--att) 13%, transparent)" : "transparent"}" data-sec="${c.i}" style="cursor:pointer"/>`
      + `<text class="lbl" x="${m.l - 8}" y="${y + 15}" text-anchor="end" style="font-size:12px;${on ? "fill:var(--att)" : ""}">${esc(c.s.name)}</text>`
      + `<rect x="${x(0)}" y="${y + 6}" width="${x(c.n) - x(0)}" height="10" rx="2" fill="color-mix(in oklab, var(--ink-2) ${on ? 55 : 32}%, var(--panel))"/>`
      + (c.out ? `<rect x="${x(c.n)}" y="${y + 6}" width="${x(c.n + c.out) - x(c.n)}" height="10" rx="2" fill="none" stroke="var(--frame-2)" stroke-dasharray="2 2"/>` : "")
      + `<text x="${x(c.n + c.out) + 6}" y="${y + 15}">${c.n}</text>`; });
  const sec = POOL_DEFAULT[SECTOR], mine = all.filter(([, k]) => k === SECTOR).map(([t]) => t), held = new Set(HELD.map((r) => r.name));
  el.innerHTML = svg(W, H, s) + `<div class="addrow"><b style="font-size:13px">${esc(sec.name)}</b><span class="mu">${mine.length - mine.filter((t) => OUT.has(t)).length} of ${mine.length}; × drops a ticker from the calibration${SECTOR === 5 || SECTOR === 6 ? "" : ""}</span>
      <span style="margin-left:auto;display:inline-flex;gap:6px;align-items:center"><label for="addt" class="mu">Add</label><input class="box small" id="addt" placeholder="ticker" autocomplete="off" spellcheck="false"></span></div>
    <div class="chips">${mine.map((t) => `<span class="chip${OUT.has(t) ? " out" : ""}${held.has(t) ? " held" : ""}" ${held.has(t) ? `title="You hold ${t}"` : ""}>${esc(t)}<button type="button" data-tog="${esc(t)}" aria-label="${OUT.has(t) ? "Put back" : "Drop"} ${esc(t)}">${OUT.has(t) ? "↺" : "×"}</button></span>`).join("")}</div>
    <p class="note">ROP is listed under both Industrials and Information Technology in the code, so the default is 406 tickers, not 407. Tickers you hold are outlined.</p>`;
}

// ---- versions: a timeline with the 90-day staleness line -----------------------------------------------------
function versions(id = "#p-ver") {
  const el = $(id), W = el.clientWidth, H = Math.max(100, el.clientHeight - 118), d0 = new Date(VERSION), d1 = new Date(d0.getTime() + 100 * 864e5);
  const x = d3.scaleTime().domain([new Date(d0.getTime() - 10 * 864e5), d1]).range([18, W - 18]), stale = new Date(d0.getTime() + 90 * 864e5), y = H / 2 + 6, today = new Date(TODAY);
  let s = `<rect x="${x(stale)}" y="${y - 26}" width="${x(d1) - x(stale)}" height="52" fill="color-mix(in oklab, var(--att) 8%, transparent)"/><text x="${x(d1) - 4}" y="${y - 30}" text-anchor="end" style="fill:color-mix(in oklab, var(--att) 76%, white)">stale after 90 days</text>`;
  s += `<line x1="18" x2="${W - 18}" y1="${y}" y2="${y}" stroke="var(--frame-2)"/>` + x.ticks(4).map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${y - 4}" y2="${y + 4}" stroke="var(--frame-2)"/><text x="${x(t)}" y="${y + 20}" text-anchor="middle">${d3.timeFormat("%d %b")(t)}</text>`).join("");
  s += `<line x1="${x(today)}" x2="${x(today)}" y1="${y - 22}" y2="${y + 8}" stroke="var(--ink-2)" stroke-dasharray="2 2"/><text x="${x(today) + 4}" y="${y - 14}">today</text>`;
  s += `<circle cx="${x(d0)}" cy="${y}" r="6" fill="var(--ink)" stroke="var(--panel)" stroke-width="2"/><text class="lbl" x="${x(d0)}" y="${y + 38}" text-anchor="middle" style="font-size:11.5px">${VERSION}</text>`;
  el.innerHTML = svg(W, H, s) + `<ul class="stages" style="padding-top:0">${JVERS.slice().reverse().map((v) => `<li><b>${v.version}</b><span>${v.version === INUSE ? "in use" : "stored"}${v.version === JVERS[JVERS.length - 1].version ? ", newest" : ""}; ${v.age_days} days old; ${v.pool_counts ? `${v.pool_counts.modelled} pool tickers modelled` : ""}</span></li>`).join("")}</ul>
    <div class="vbtns"><button class="go" type="button" data-recal>Recalibrate now</button><button type="button" id="pin">${PINNED ? "Unpin (use the newest)" : "Pin this version"}</button><span class="mu" style="align-self:center;font-size:12px">a recalibration takes about 66 s (measured)</span></div>`;
}

// ---- jump sizes: the fitted generalized Pareto tails, beyond the threshold -----------------------------------
function sizes(id = "#p-size") {
  const el = $(id), W = el.clientWidth, H = el.clientHeight - 62, J = DATA.jumps, thr = J.systematic.threshold, MAX = 8;   // the engine clips shocks at 8σ
  const pdf = (z, shape, scale) => { const u = z - thr; if (u < 0) return 0; return shape < 1e-6 ? Math.exp(-u / scale) / scale : (1 / scale) * Math.pow(1 + (shape * u) / scale, -1 / shape - 1); };
  const zs = d3.range(thr, MAX + 1e-9, 0.05), curves = [["systematic", "crash", "var(--down)", false], ["systematic", "rally", "var(--up)", false], ["idiosyncratic", "crash", "var(--down)", true], ["idiosyncratic", "rally", "var(--up)", true]];
  const m = { l: 40, r: 12, t: 12, b: 26 }, x = d3.scaleLinear().domain([thr, MAX]).range([m.l, W - m.r]);
  // log scale: the tails are what differ, and a linear axis squashes them onto the floor
  const ymax = d3.max(curves, ([L, k]) => pdf(thr, J[L][k + "_shape"], J[L][k + "_scale"])), y = d3.scaleLog().domain([1e-3, ymax * 1.2]).range([H - m.b, m.t]).clamp(true);
  let s = x.ticks(5).map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--frame)"/><text x="${x(t)}" y="${H - 8}" text-anchor="middle">${t}σ</text>`).join("")
    + [1e-3, 1e-2, 1e-1, 1].filter((v) => v <= ymax * 1.2).map((v) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--frame)" stroke-dasharray="2 3"/><text x="${m.l - 4}" y="${y(v) + 3.5}" text-anchor="end">${v}</text>`).join("");
  curves.forEach(([L, k, c, dash]) => { const sh = J[L][k + "_shape"], sc = J[L][k + "_scale"];
    s += `<path d="${d3.line().defined((z) => pdf(z, sh, sc) >= 1e-3).x((z) => x(z)).y((z) => y(pdf(z, sh, sc)))(zs)}" fill="none" stroke="${c}" stroke-width="2"${dash ? ' stroke-dasharray="5 3"' : ""}/>`;
  });
  el.innerHTML = svg(W, H, s) + `<div class="legend"><span><i style="width:16px;border-top:2px solid var(--down)"></i>crash, market</span><span><i style="width:16px;border-top:2px solid var(--up)"></i>rally, market</span><span><i style="width:16px;border-top:2px dashed var(--down)"></i>crash, single stock</span><span><i style="width:16px;border-top:2px dashed var(--up)"></i>rally, single stock</span><span>density, log scale</span></div>`
    + `<p class="note" style="margin-top:2px">A jump beyond 3σ happens about ${(J.systematic.lambda * 52).toFixed(2)} times a year for the market and ${(J.idiosyncratic.lambda * 52).toFixed(2)} for a single stock; ${Math.round(J.systematic.prob_crash * 100)}% and ${Math.round(J.idiosyncratic.prob_crash * 100)}% of them are crashes.</p>`;
}

// ---- betas: each held asset's surprise-day betas, with a manual override ---------------------------------------
const OV = {};   // manual betas, stored per ticker on the server (library/beta_overrides.json)
Object.entries(LIVE.betas || {}).forEach(([t, b]) => { if (b.crash_source === "manual") OV[t + ":crash"] = b.crash_beta; if (b.rally_source === "manual") OV[t + ":rally"] = b.rally_beta; });
function betas() {
  const srcOf = (t, side) => { const b = (LIVE.betas || {})[t] || {}; return b[side + "_source"] === "manual" ? (b[side + "_days"] >= DIRECT_MIN ? "direct" : "fallback") : (b[side + "_source"] || "fallback"); };
  const src = (n, k) => { const [t, side] = k.split(":"); if (OV[k] != null) return "manual"; const v = srcOf(t, side); return v === "direct" ? "direct" : v === "normal" ? "normal β" : v === "LOWESS" ? "LOWESS" : "fallback"; };
  $("#p-betas").innerHTML = `<table><thead><tr><th class="l">Asset</th><th>Crash β</th><th>Surprise days</th><th class="l">From</th><th>Override</th><th>Rally β</th><th>Surprise days</th><th class="l">From</th><th>Override</th></tr></thead><tbody>${HELD.map((r) => { const b = BETAS[r.name], kc = r.name + ":crash", kr = r.name + ":rally";
    return `<tr><td class="l nm" style="--c:${colorOf(r)}"><span class="tk" style="color:color-mix(in oklab, ${colorOf(r)} 70%, white)">${r.name}</span></td>
      <td>${OV[kc] != null ? `<span class="mu" style="text-decoration:line-through">${num(b.crash)}</span>` : num(b.crash)}</td><td>${b.crashN}</td><td class="l"><span class="src ${src(b.crashN, kc)}">${src(b.crashN, kc)}</span></td><td><input class="ov${OV[kc] != null ? " typed" : ""}" data-ov="${kc}" value="${OV[kc] ?? ""}" placeholder="—" aria-label="Override ${r.name} crash beta" autocomplete="off"></td>
      <td>${OV[kr] != null ? `<span class="mu" style="text-decoration:line-through">${num(b.rally)}</span>` : num(b.rally)}</td><td>${b.rallyN}</td><td class="l"><span class="src ${src(b.rallyN, kr)}">${src(b.rallyN, kr)}</span></td><td><input class="ov${OV[kr] != null ? " typed" : ""}" data-ov="${kr}" value="${OV[kr] ?? ""}" placeholder="—" aria-label="Override ${r.name} rally beta" autocomplete="off"></td></tr>`; }).join("")}</tbody></table>
    <p class="note">Direct: estimated from ${DIRECT_MIN} or more surprise days. Fallback: too few days, so the study's fallback is used. Only ${VINFO.lowess && VINFO.lowess.surprise_days ? VINFO.lowess.surprise_days.rally : 60} surprise rally days exist since 1928 (${VINFO.lowess && VINFO.lowess.surprise_days ? VINFO.lowess.surprise_days.crash : 172} crash days), which is why most rally betas fall back: stocks to the LOWESS curve, the rest to their normal β.</p>`;
}

let draw = () => { pool(); versions(); sizes(); betas(); };   // jumpdb-alt.js replaces it with one draw per layout
document.addEventListener("click", (e) => {
  const sct = e.target.closest("[data-sec]"); if (sct) { SECTOR = Number(sct.dataset.sec); draw(); return; }
  const tg = e.target.closest("[data-tog]"); if (tg) { const t = tg.dataset.tog; OUT.has(t) ? OUT.delete(t) : OUT.add(t); draw(); savePool(); return; }
  if (e.target.closest("#reset")) { OUT.clear(); ADDED.clear(); draw(); savePool(); $("#note").textContent = "Pool back to the 406-ticker default."; return; }
  if (e.target.closest("#recal, [data-recal]")) { recalibrate(); return; }
  if (e.target.closest("#pin")) { pin(); }
});
document.addEventListener("change", (e) => {
  if (e.target.id === "addt") { const t = e.target.value.trim().toUpperCase(); if (/^[A-Z0-9.^=-]{1,12}$/.test(t)) { if (!uniq().some(([u]) => u === t)) ADDED.set(t, SECTOR); OUT.delete(t); savePool(); } draw(); $("#addt")?.focus(); return; }
  const o = e.target.dataset?.ov; if (o) { const v = parseFloat(String(e.target.value).replace(/[−–]/g, "-")); if (Number.isFinite(v)) OV[o] = v; else delete OV[o]; draw(); saveOverride(o.split(":")[0]); }
});
addEventListener("resize", () => draw());

// ---- the wiring: overrides, recalibration and pinning go to the server -----------------------------------------
async function saveOverride(t) {
  const r = await fetch(`/api/betas/${encodeURIComponent(t)}`, { method: "PUT", headers: { "content-type": "application/json" },
    body: JSON.stringify({ crash: OV[t + ":crash"] ?? null, rally: OV[t + ":rally"] ?? null }) });
  $("#note").textContent = r.ok ? `${t}: manual betas saved; every portfolio's next run uses them.` : `${t}: not saved.`;
}
async function recalibrate() {
  const b = document.querySelector("[data-recal]"); if (b) { b.disabled = true; b.textContent = "Recalibrating…"; }
  const job = await (await fetch("/api/jumpdb/recalibrate", { method: "POST" })).json(); const t0 = Date.now();
  for (;;) { await new Promise((r) => setTimeout(r, 2000)); const j = await (await fetch(`/api/jobs/${job.id}`)).json();
    $("#note").textContent = `Recalibrating the pool: ${Math.round((Date.now() - t0) / 1000)} s (about 66 s plus downloads).`;
    if (j.status === "done") { $("#note").textContent = j.message || "Recalibrated."; setTimeout(() => location.reload(), 1200); return; }
    if (j.status === "failed") { $("#note").textContent = `Recalibration failed: ${j.message || j.error}`; if (b) { b.disabled = false; b.textContent = "Recalibrate now"; } return; } }
}
async function pin() {
  const p = API.get(`/api/portfolios/${PF_.id}`); delete p.as_of; delete p.jump_version;
  p.run = { ...(p.run || {}), jump_version: PINNED ? "latest" : INUSE };
  const r = await fetch(`/api/portfolios/${PF_.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(p) });
  if (r.ok) location.reload(); else $("#note").textContent = `Not pinned: ${(await r.json()).detail}`;
}
