// ---- Results = the analysis room (round 5, accepted), now on the run's tree and the builder's colours. Same wall of
// linked panels; selecting a part anywhere lights it everywhere, and panels swap places by dragging their headers.
// New for results: the Tree panel's Inputs / Results toggle, and three panels that follow the selection (outcome fan,
// 12-week return, worst drawdown), picked into any slot from the panel's own menu.
const PANELS = {
  alloc: { title: "Allocation", sub: () => (ROOM.alloc === "treemap" ? "area = effective weight, framed by subportfolio" : "rings = levels of the tree"), draw: roomAlloc },
  tree: { title: "Tree", sub: () => (ROOM.tree === "results" ? "12-week figures on paths no search saw" : "returns % a year, uncertainty in points; bold = typed"), draw: roomTree },
  fan: { title: "Outcome fan", sub: () => "value of 1 over 12 weeks, 5–95th percentiles", draw: roomFan, follows: true },
  ret: { title: "12-week return", sub: () => "simulated distribution, VaR and CVaR at 5%", draw: roomRet, follows: true },
  wdd: { title: "Worst drawdown", sub: () => "per simulated path over 12 weeks, CDaR at 5%", draw: roomWdd, follows: true },
  corr: { title: "Correlation", sub: () => "weekly log returns, 5 years, pairwise overlap", draw: roomCorr },
  jump: { title: "Jump betas", sub: () => "crash β against rally β; hollow = fallback; size = weight", draw: roomJump },
  hdd: { title: "Drawdowns", sub: () => "fall from peak, weekly, 5 years; one scale in every cell", draw: roomHdd },
  views: { title: "Views", sub: () => "equilibrium (tick) and view (dot) with its uncertainty, % a year", draw: roomViews },
};
// chart modules (app/charts/<name>/panel.js) add themselves here; the built-in panels above are registered the same way
function registerPanel(key, def) { PANELS[key] = def; }
const ROOM = { slots: ["alloc", "fan", "jump", "tree", "ret", "views"], alloc: "treemap", tree: "results", max: false };
const ASSETS_R = () => R0.rows.filter((r) => r.kind === "asset");
const tkOf = (r) => r.name;
const selRow = () => M0.get(sel) || R0.rows[0];
const inSel = (r) => { const s = selRow(); return idOf(r) === idOf(s) || idOf(r).startsWith(idOf(s) + "/"); };   // a selected group lights its members
const lit = (c) => `color-mix(in oklab, ${c} 70%, white)`;

function roomBuild() {
  const host = $("#v-results");
  host.classList.toggle("max", ROOM.max);
  host.innerHTML = ROOM.slots.map((k, i) => { const P = PANELS[k];
    const seg = k === "alloc" ? `<span class="seg" role="group" aria-label="Allocation chart"><button type="button" data-am="treemap" aria-pressed="${ROOM.alloc === "treemap"}">Treemap</button><button type="button" data-am="sunburst" aria-pressed="${ROOM.alloc === "sunburst"}">Sunburst</button></span>`
      : k === "tree" ? `<span class="seg" role="group" aria-label="Tree columns"><button type="button" data-tm="inputs" aria-pressed="${ROOM.tree === "inputs"}">Inputs</button><button type="button" data-tm="results" aria-pressed="${ROOM.tree === "results"}">Results</button></span><button class="act" type="button" id="foldall" title="${FOLD.size ? "Open every subportfolio" : "Fold every subportfolio"}">${FOLD.size ? "Unfold" : "Fold all"}</button><button class="act" type="button" id="maxin" title="${ROOM.max ? "Back to the wall (Esc)" : "Fill the screen with the tree"}">${ROOM.max ? "Back" : "Expand"}</button>` : "";
    return `<section class="panel${ROOM.max && k !== "tree" ? " gone" : ""}${ROOM.max && k === "tree" ? " full" : ""}" data-slot="${i}" data-p="${k}"><div class="ph" data-drag="${i}"><b>${P.title}</b><span>${P.sub()}</span>${P.follows ? `<span class="for">${esc(selRow().name)}</span>` : ""}${seg}
      <button class="pick" type="button" data-menu="${i}" aria-haspopup="menu" aria-expanded="false" title="Show another panel in this slot">▾</button></div>
      <div class="pb${k === "tree" ? " scroll" : ""}" id="slot-${i}"></div></section>`; }).join("");
  ROOM.slots.forEach((k, i) => { if (!ROOM.max || k === "tree") PANELS[k].draw($("#slot-" + i)); });
}

// allocation: nested treemap or a sunburst with one ring per level
function roomAlloc(el) {
  const W = el.clientWidth - 8, H = el.clientHeight - 8, node = (r) => (r.kind === "asset" ? { r, value: r.effective } : { r, children: kids(R0, r).map(node) });
  const root = d3.hierarchy(node(R0.rows[0])).sum((d) => d.value || 0);
  let s = "";
  if (ROOM.alloc === "treemap") {
    d3.treemap().size([W, H]).paddingOuter(2).paddingTop((d) => (d.depth === 0 ? 0 : 16)).paddingInner(2).round(true)(root);
    root.descendants().forEach((d) => { if (!d.depth) return; const r = d.data.r, c = colorOf(r), w = d.x1 - d.x0, h = d.y1 - d.y0, id = idOf(r), on = id === sel;
      if (r.kind === "group") { s += `<rect x="${d.x0}" y="${d.y0}" width="${w}" height="${h}" rx="3" fill="none" stroke="${on ? "var(--att)" : `color-mix(in oklab, ${c} 45%, var(--frame-2))`}" stroke-width="${on ? 2 : 1}" data-r="${esc(id)}" class="hit"/>`;
        if (w > 40) s += `<text class="lbl" x="${d.x0 + 5}" y="${d.y0 + 12}" style="font-size:11px">${esc(r.name.length * 6.5 > w - 10 ? r.name.slice(0, Math.max(3, Math.floor((w - 10) / 6.5))) + "…" : r.name)} <tspan class="mu" style="font:400 10.5px var(--code)">${w > 120 ? p1(r.effective) : ""}</tspan></text>`; }
      else if (r.effective > 0) { s += `<rect x="${d.x0}" y="${d.y0}" width="${w}" height="${h}" rx="2" fill="color-mix(in oklab, ${c} ${inSel(r) && sel !== "Portfolio" ? 48 : 32}%, var(--panel))" stroke="${on ? "var(--att)" : "none"}" stroke-width="2" data-r="${esc(id)}" class="hit"/>`;
        if (w > 34 && h > 16) s += `<text x="${d.x0 + 4}" y="${d.y0 + 12}" style="font-weight:600;fill:${on ? "var(--att)" : lit(c)}">${esc(r.name)}</text>`;
        if (w > 34 && h > 30) s += `<text x="${d.x0 + 4}" y="${d.y0 + 25}">${p1(r.effective)}</text>`; } });
  } else {
    const R = Math.min(W, H) / 2 - 34, depth = root.height; d3.partition().size([2 * Math.PI, depth + 1])(root);
    const ring = (k) => R * (0.18 + 0.82 * (k - 1) / depth), arc = d3.arc().startAngle((d) => d.x0).endAngle((d) => d.x1).padAngle(0.004).innerRadius((d) => ring(d.depth)).outerRadius((d) => ring(d.depth + 1) - 2);
    s += `<g transform="translate(${W / 2},${H / 2})">`;
    root.descendants().forEach((d) => { if (!d.depth || d.x1 - d.x0 < 1e-4) return; const r = d.data.r, c = colorOf(r), on = idOf(r) === sel, leaf = r.kind === "asset";
      s += `<path class="hit" d="${arc(d)}" fill="color-mix(in oklab, ${c} ${leaf ? 72 : 30}%, var(--panel))" stroke="${on ? "var(--att)" : "var(--panel)"}" stroke-width="${on ? 2.5 : 1}" data-r="${esc(idOf(r))}"/>`;
      const a = (d.x0 + d.x1) / 2, rr = (ring(d.depth) + ring(d.depth + 1)) / 2, len = (d.x1 - d.x0) * rr;
      if (len > r.name.length * 6.4 + 6) { let deg = (a * 180) / Math.PI; const flip = deg > 90 && deg < 270; s += `<text x="${Math.sin(a) * rr}" y="${-Math.cos(a) * rr + 3.5}" text-anchor="middle" style="fill:${leaf ? "var(--bg)" : "var(--ink)"};font-weight:${leaf ? 600 : 500}">${esc(r.name)}</text>`; } });
    const s0 = selRow(); s += `<text class="lbl" y="-4" text-anchor="middle" style="font:500 13px var(--code);fill:var(--att)">${esc(s0.name)}</text><text y="12" text-anchor="middle">${p2(s0.effective)}</text></g>`;
  }
  el.innerHTML = `<div style="position:absolute;inset:4px">${svg(W, H, s)}</div>`;
}

// the tree: inputs (as before the run) or results (the run's figures), one row per part, folding by subportfolio
function roomTree(el) {
  const rows = visible(R0), res = ROOM.tree === "results", wide = el.clientWidth > 720;   // in a wall slot the tree keeps the columns that matter; Expand shows them all
  const C = res ? (wide ? ["share", "eff", "er", "vol", "cvar", "cdar", "upi", "sharpe", "sortino"] : ["eff", "er", "cdar", "upi"]) : (wide ? ["eq", "view", "target", "pm", "eff"] : ["eq", "view", "pm", "eff"]);
  const H = { share: "Share<small>of parent</small>", eff: "Effective<small>of portfolio</small>", er: "Expected<small>12 weeks</small>", vol: "Vol", cvar: "CVaR<small>5%</small>", cdar: "CDaR<small>5%</small>", upi: "UPI", sharpe: "Sharpe<small>annualized</small>", sortino: "Sortino<small>annualized</small>", eq: "Equil.", view: "View", target: "Target $", pm: "−/+" };
  const head = `<th class="l">Part</th>` + C.map((k) => `<th>${H[k]}</th>`).join("");
  const body = rows.map((r) => { const id = idOf(r), c = colorOf(r), g = r.kind === "group", d = r.path.length, b = bindText(R0, r), S = r.search, m = r.metrics, a = byTicker[r.name];
    const name = g ? `<button class="fold" type="button" data-fold="${esc(id)}" aria-expanded="${!FOLD.has(id)}" aria-label="Fold ${esc(r.name)}">${FOLD.has(id) ? "▸" : "▾"}</button>${esc(r.name)}` : `<span class="tk">${esc(r.name)}</span>`;
    const det = res && wide && g && S && S.generations ? `<button class="srch" type="button" data-det="${esc(id)}" aria-expanded="${OPEN.has(id)}" title="Show its search">${S.generations} gen ${OPEN.has(id) ? "▾" : "▸"}</button>` : "";
    const lim = wide && r.limits && (r.limits.min != null || r.limits.max != null) ? `<span class="limt">${r.limits.min != null && r.limits.max != null ? `${p01(r.limits.min).replace("%", "")}–${p01(r.limits.max)}` : r.limits.min != null ? `≥ ${p01(r.limits.min)}` : `≤ ${p01(r.limits.max)}`}</span>` : "";
    const V = { share: () => `<span class="sh">${d ? `<i class="bar" style="--c:${c};width:${Math.max(1, 30 * r.share)}px;opacity:${g ? 0.7 : 1}"></i>` + p1(r.share) : ""}</span>`, eff: () => p2(r.effective),
      er: () => pct(m.er_12w, 2, true), vol: () => p1(m.vol_12w), cvar: () => p1(m.cvar), cdar: () => p1(m.cdar), upi: () => (m.upi == null ? "—" : num(m.upi, 3)),
      sharpe: () => num(m.sharpe_ann, 2), sortino: () => num(m.sortino_ann, 2),
      eq: () => (g ? "" : pts(a.eq)), view: () => (g ? "" : a.view == null ? `<span class="mu">—</span>` : `<b class="typed">${pts(a.view)}</b>`), target: () => (g || a.view == null ? "" : money(targetFromReturn(a, a.view))),
      pm: () => (g ? "" : a.sdMinus == null ? `<span class="mu">—</span>` : `${MINUS}${pts(a.sdMinus)} / +${pts(a.sdPlus)}`) };
    const cells = C.map((k) => `<td>${V[k]()}</td>`).join("");
    let s = `<tr data-r="${esc(id)}" class="${g ? "g d" + d : ""}${id === sel ? " on" : ""}"><td class="l nm" style="--c:${c};padding-left:${6 + 13 * d}px">${name}${lim}${det}${b ? `<span class="bind">${wide ? b : b.replace("at its ", "")}</span>` : ""}</td>${cells}</tr>`;   // in a wall slot: limits and searches show when the panel is expanded
    if (res && OPEN.has(id) && S) s += `<tr class="det"><td colspan="${C.length + 1}">${searchLine(r)}</td></tr>`;
    return s; }).join("");
  el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  const on = el.querySelector("tr.on"); if (on && (on.offsetTop < el.scrollTop + 30 || on.offsetTop > el.scrollTop + el.clientHeight - 30)) el.scrollTop = on.offsetTop - el.clientHeight / 2;   // scroll the panel, never the page
}
const chartColor = (r) => (colorOf(r) === "var(--ink-2)" ? "#c0caf5" : colorOf(r));
function roomFan(el) { const r = selRow(); el.innerHTML = fanSvg("fan", [{ r, c: chartColor(r) }], el.clientWidth, el.clientHeight); }
function roomRet(el) { const r = selRow(), m = r.metrics; el.innerHTML = histSvg(r.ret_hist, { tail: m.var, lines: [{ v: m.sim_mean_12w, label: "mean" }, { v: m.var, label: "VaR" }, { v: m.cvar, label: "CVaR", k: "dash" }] }, chartColor(r), el.clientWidth, el.clientHeight); }
function roomWdd(el) { const r = selRow(); el.innerHTML = histSvg(r.dd_hist, { lines: [{ v: r.metrics.cdar, label: "CDaR", k: "dash" }] }, chartColor(r), el.clientWidth, el.clientHeight); }

// the room's inputs panels, on the run's tree
function roomCorr(el) {
  const W = el.clientWidth, H = el.clientHeight, A = ASSETS_R(), T = A.map(tkOf), n = T.length, pad = 46, sz = Math.min(W - pad - 8, H - pad - 8), c = sz / n;
  const css = getComputedStyle(document.documentElement), col = d3.scaleLinear().domain([-1, 0, 1]).range([css.getPropertyValue("--down").trim(), css.getPropertyValue("--panel-2").trim(), "#7dcfff"]).interpolate(d3.interpolateLab);
  let s = `<g transform="translate(${pad},${pad})">`;
  T.forEach((a, i) => T.forEach((b, j) => { const v = corr(a, b), on = inSel(A[i]) || inSel(A[j]);
    s += `<rect class="hit" x="${j * c}" y="${i * c}" width="${c - 1}" height="${c - 1}" fill="${v == null ? "var(--panel)" : i === j ? "var(--panel-2)" : col(v)}" stroke="${on && sel !== "Portfolio" ? "var(--att)" : "none"}" stroke-width="1" data-tipx="${esc(`${a} with ${b}: ρ ${v == null ? "n/a" : num(v)} over ${overlap(a, b)} weeks`)}"/>`; }));
  A.forEach((r, i) => { const st = inSel(r) && sel !== "Portfolio" ? "fill:var(--att)" : `fill:${lit(colorOf(r))}`; s += `<text x="-4" y="${i * c + c / 2 + 3.5}" text-anchor="end" style="${st}">${r.name}</text><text transform="translate(${i * c + c / 2 + 3.5},-4) rotate(-90)" style="${st}">${r.name}</text>`; });
  let k = 0; TOPS.forEach((g) => { k += A.filter((r) => r.path[1] === g).length; if (k < n) s += `<line x1="${k * c - 0.5}" x2="${k * c - 0.5}" y1="0" y2="${sz}" stroke="var(--bg)" stroke-width="2"/><line y1="${k * c - 0.5}" y2="${k * c - 0.5}" x1="0" x2="${sz}" stroke="var(--bg)" stroke-width="2"/>`; });
  el.innerHTML = svg(W, H, s + "</g>");
}
function roomJump(el) {
  const W = el.clientWidth, H = el.clientHeight, m = { l: 40, r: 14, t: 12, b: 32 };
  const x = d3.scaleLinear().domain([-0.5, 2.2]).range([m.l, W - m.r]), y = d3.scaleLinear().domain([-0.5, 2.4]).range([H - m.b, m.t]);
  let s = "";
  x.ticks(5).forEach((t) => s += `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--frame)"/><text x="${x(t)}" y="${H - m.b + 13}" text-anchor="middle">${num(t, 1)}</text>`);
  y.ticks(5).forEach((t) => s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="var(--frame)"/><text x="${m.l - 5}" y="${y(t) + 3.5}" text-anchor="end">${num(t, 1)}</text>`);
  s += `<line x1="${x(-0.5)}" y1="${y(-0.5)}" x2="${x(2.2)}" y2="${y(2.2)}" stroke="var(--frame-2)" stroke-dasharray="1 4"/><text x="${(m.l + W - m.r) / 2}" y="${H - 4}" text-anchor="middle">crash β</text><text transform="translate(11,${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle">rally β</text>`;
  const P = ASSETS_R().sort((p, q) => q.effective - p.effective).map((r) => { const b = BETAS[r.name]; return { r, b, rad: 3 + Math.sqrt(r.effective) * 18, cx: x(b.crash), cy: y(b.rally) }; });
  const placed = P.map((p) => ({ x0: p.cx - p.rad, x1: p.cx + p.rad, y0: p.cy - p.rad, y1: p.cy + p.rad })), hit = (q) => placed.some((o) => q.x0 < o.x1 && q.x1 > o.x0 && q.y0 < o.y1 && q.y1 > o.y0);
  P.forEach((p) => { const fb = p.b.crashN < DIRECT_MIN || p.b.rallyN < DIRECT_MIN, c = colorOf(p.r), on = inSel(p.r) && sel !== "Portfolio";
    s += `<circle class="hit" cx="${p.cx}" cy="${p.cy}" r="${p.rad}" fill="${fb ? "transparent" : c}" stroke="${on ? "var(--att)" : c}" stroke-width="${on ? 2.5 : 1.5}" data-r="${esc(idOf(p.r))}"/>`; });
  P.forEach((p) => { const tw = p.r.name.length * 6.6 + 2, on = inSel(p.r) && sel !== "Portfolio";
    for (const [lx, ly, an] of [[p.cx + p.rad + 3, p.cy + 3.5, "start"], [p.cx - p.rad - 3, p.cy + 3.5, "end"], [p.cx, p.cy - p.rad - 4, "middle"], [p.cx, p.cy + p.rad + 11, "middle"]]) {
      const x0 = an === "start" ? lx : an === "end" ? lx - tw : lx - tw / 2, q = { x0, x1: x0 + tw, y0: ly - 9, y1: ly + 2 };
      if (!hit(q)) { placed.push(q); s += `<text x="${lx}" y="${ly}" text-anchor="${an}" style="${on ? "fill:var(--att)" : ""}">${p.r.name}</text>`; break; } } });
  el.innerHTML = svg(W, H, s);
}
function roomHdd(el) {
  const A = ASSETS_R(), lo = d3.min(A, (r) => HIST.series[r.name].maxdd ?? d3.min(HIST.series[r.name].dd));
  el.innerHTML = `<div class="mult">${A.map((r) => { const h = HIST.series[r.name], dd = h.dd, x = d3.scaleLinear().domain([0, dd.length - 1]).range([0, 100]), y = d3.scaleLinear().domain([lo, 0]).range([100, 0]), on = inSel(r) && sel !== "Portfolio";
    return `<div data-r="${esc(idOf(r))}" class="${on ? "on" : ""}"><code style="color:${lit(colorOf(r))}">${r.name}</code><span class="v">${pct(d3.min(dd), 1)}</span><svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="${d3.area().x((d, i) => x(i)).y0(0).y1((d) => y(d))(dd)}" fill="color-mix(in oklab, ${colorOf(r)} 60%, transparent)"/></svg></div>`; }).join("")}</div>`;
}
function roomViews(el) {
  const W = el.clientWidth, H = el.clientHeight, A = ASSETS_R(), m = { l: 52, r: 44, t: 8, b: 22 }, rh = (H - m.t - m.b) / A.length, x = d3.scaleLinear().domain([-0.6, 1.6]).range([m.l, W - m.r]).clamp(true);
  let s = "";
  [-0.5, 0, 0.5, 1, 1.5].forEach((t) => s += `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="${t === 0 ? "var(--frame-2)" : "var(--frame)"}"/><text x="${x(t)}" y="${H - 6}" text-anchor="middle">${t > 0 ? "+" : t < 0 ? MINUS : ""}${Math.abs(t * 100)}</text>`);
  A.forEach((r, i) => { const a = byTicker[r.name], y = m.t + i * rh + rh / 2, c = colorOf(r), on = inSel(r) && sel !== "Portfolio";
    s += `<rect class="hit" x="0" y="${y - rh / 2}" width="${W}" height="${rh}" fill="${on ? "color-mix(in oklab, var(--att) 10%, transparent)" : "transparent"}" data-r="${esc(idOf(r))}"/><text x="${m.l - 6}" y="${y + 3.5}" text-anchor="end" style="fill:${on ? "var(--att)" : lit(c)}">${r.name}</text>`;
    if (a.view != null) { s += `<line x1="${x(a.view - a.sdMinus)}" x2="${x(a.view + a.sdPlus)}" y1="${y}" y2="${y}" stroke="${c}" stroke-opacity="0.45" stroke-width="4"/><circle cx="${x(a.view)}" cy="${y}" r="4" fill="${c}"/>`; if (a.view > 1.6) s += `<text x="${W - m.r + 9}" y="${y + 3.5}">${pts(a.view, 0)}</text>`; }
    s += `<line x1="${x(a.eq)}" x2="${x(a.eq)}" y1="${y - 6}" y2="${y + 6}" stroke="var(--ink)" stroke-width="1.5"/>`; });
  el.innerHTML = svg(W, H, s);
}

// room wiring: mode toggles, the slot menu, panel drag, expand
document.addEventListener("click", (e) => {
  if (view !== "results") return;
  const am = e.target.closest("[data-am]"); if (am) { ROOM.alloc = am.dataset.am; roomBuild(); return; }
  const tm = e.target.closest("[data-tm]"); if (tm) { ROOM.tree = tm.dataset.tm; roomBuild(); return; }
  if (e.target.closest("#foldall")) { if (FOLD.size) FOLD.clear(); else R0.rows.forEach((r) => { if (r.kind === "group" && r.path.length) FOLD.add(idOf(r)); }); roomBuild(); return; }
  if (e.target.closest("#maxin")) { ROOM.max = !ROOM.max; roomBuild(); }
}, true);
// the slot menu: every panel, with the ones already on the wall marked in the accent; picking one of those swaps the two
function closeMenu() { $("#pmenu")?.remove(); $$("[data-menu]").forEach((b) => b.setAttribute("aria-expanded", "false")); }
function openMenu(btn) {
  closeMenu(); const i = Number(btn.dataset.menu), r = btn.getBoundingClientRect();
  const m = Object.assign(document.createElement("div"), { id: "pmenu", className: "pmenu" }); m.setAttribute("role", "menu");
  m.innerHTML = Object.entries(PANELS).map(([k, p]) => { const at = ROOM.slots.indexOf(k), here = at === i, on = at >= 0;
    return `<button type="button" role="menuitem" data-put="${k}" data-slot-i="${i}" class="${on ? "on" : ""}${here ? " here" : ""}"><i aria-hidden="true"></i>${p.title}<small>${here ? "in this slot" : on ? "on the wall: swaps" : ""}</small></button>`; }).join("");
  document.body.appendChild(m); m.style.top = r.bottom + 4 + "px"; m.style.left = Math.min(innerWidth - m.offsetWidth - 8, r.right - m.offsetWidth) + "px";
  btn.setAttribute("aria-expanded", "true"); m.querySelector("button.here, button")?.focus();
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-menu]"); if (b) { b.getAttribute("aria-expanded") === "true" ? closeMenu() : openMenu(b); return; }
  const it = e.target.closest("[data-put]"); if (it) { const i = Number(it.dataset.slotI), k = it.dataset.put, j = ROOM.slots.indexOf(k); if (j >= 0) ROOM.slots[j] = ROOM.slots[i]; ROOM.slots[i] = k; closeMenu(); roomBuild(); return; }
  if (!e.target.closest("#pmenu")) closeMenu();
});
document.addEventListener("keydown", (e) => { if (!$("#pmenu")) return; const items = $$("#pmenu button"), k = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.stopImmediatePropagation(); closeMenu(); } else if (e.key === "ArrowDown") { e.preventDefault(); items[(k + 1) % items.length].focus(); } else if (e.key === "ArrowUp") { e.preventDefault(); items[(k - 1 + items.length) % items.length].focus(); } }, true);
document.addEventListener("keydown", (e) => { if (view === "results" && e.key === "Escape" && ROOM.max) { ROOM.max = false; roomBuild(); } });
let pdrag = null;
document.addEventListener("pointerdown", (e) => { const h = e.target.closest?.("#v-results .ph"); if (!h || e.button !== 0 || e.target.closest("button, select, label")) return; closeMenu(); pdrag = { from: Number(h.dataset.drag), x: e.clientX, y: e.clientY }; e.preventDefault(); });
document.addEventListener("pointermove", (e) => { if (!pdrag) return; if (!pdrag.on && Math.hypot(e.clientX - pdrag.x, e.clientY - pdrag.y) < 5) return; pdrag.on = true; document.body.classList.add("dragging");
  $$("#v-results .panel").forEach((p) => p.classList.remove("drop")); const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("#v-results .panel"); pdrag.to = over && Number(over.dataset.slot) !== pdrag.from ? Number(over.dataset.slot) : null; over?.classList.toggle("drop", pdrag.to != null); });
document.addEventListener("pointerup", () => { if (!pdrag) return; const d = pdrag; pdrag = null; document.body.classList.remove("dragging"); if (d.on && d.to != null) { const s = ROOM.slots; [s[d.from], s[d.to]] = [s[d.to], s[d.from]]; } if (d.on) roomBuild(); });
