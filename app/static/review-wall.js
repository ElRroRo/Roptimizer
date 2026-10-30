// ---- Review, layout W: the pre-flight room. A wall of linked panels in the analysis room's language: the tree as
// a small radial (the builder's bands), every weight range on one scale, the returns, the limits in words, the
// settings and their sources, and what stands between this tree and a run. Hover anything to light it everywhere;
// click to select it; a blocker takes you back to the builder on the thing to fix.
{
const wall = document.createElement("div"); wall.className = "rv"; wall.id = "rv";
wall.innerHTML = `
  <section class="panel p-tree"><div class="ph"><b>Tree</b><span>bands = subportfolios by level</span></div><div class="pb" id="rv-tree"></div></section>
  <section class="panel p-w"><div class="ph"><b>Weights</b><span>share of the whole portfolio; thin = no limit of its own, dashed = without its siblings' limits, [ ] = its own limit</span></div><div class="pb" id="rv-w"></div></section>
  <section class="panel p-r"><div class="ph"><b>Returns</b><span>equilibrium at equal weights until the first run</span></div><div class="pb" id="rv-r"></div></section>
  <section class="panel p-l"><div class="ph"><b>Limits</b><span>and what each one squeezes</span></div><div class="pb" id="rv-l"></div></section>
  <section class="panel p-s"><div class="ph"><b>Settings</b><span>values shown where they differ from the default</span></div><div class="pb" id="rv-s"></div></section>
  <section class="runbar" id="rv-bar"></section>`;
document.body.insertBefore(wall, $(".foot"));
const svgOpen = (W, H) => `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
const tint = (c, k) => `color-mix(in oklab, ${c} ${k}%, var(--panel))`;
const tk = (c) => `color-mix(in oklab, ${c} 70%, white)`;
let blockIds = new Set();

function drawRadial() {
  const el = $("#rv-tree"), W = el.clientWidth, H = el.clientHeight, cx = W / 2, cy = H / 2 + 4, R = Math.min(W, H) / 2 - 44;
  const root = d3.hierarchy(ROOT, (n) => (n.kind === "group" && n.children.length ? n.children : null)), leaves = root.leaves(), step = 2 * Math.PI / Math.max(1, leaves.length);
  const Hh = Math.max(1, d3.max(root.descendants(), (d) => (d.children || d.data.kind === "group" ? d.depth : 0))), rad = (k) => R * (0.3 + (0.56 * (k - 1)) / Math.max(1, Hh - 1));
  leaves.forEach((d, i) => { d.a = step * (i + 0.5); });
  root.eachAfter((d) => { if (d.children) { d.lo = d.children[0].lo ?? d.children[0].a; d.hi = d.children[d.children.length - 1].hi ?? d.children[d.children.length - 1].a; d.a = (d.lo + d.hi) / 2; } else { d.lo = d.hi = d.a; } });
  const P = (a, r) => [cx + r * Math.sin(a), cy - r * Math.cos(a)], lw = (n) => (0.8 + 4 * Math.sqrt(Math.max(0, Math.min(1, n._eff[1])))).toFixed(2);
  let s = svgOpen(W, H);
  root.descendants().forEach((d) => { if (d.data === ROOT) return; const n = d.data, c = colorOf(n), isG = n.kind === "group", r = isG ? rad(d.depth) : R, pr = d.parent.data === ROOT ? 0 : rad(d.parent.depth) + 5;
    const [x0, y0] = P(d.a, pr), [x1, y1] = P(d.a, isG ? r - 5 : r - 4);
    s += `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="${tint(c, 60)}" stroke-width="${lw(n)}" stroke-linecap="round" data-rid="${n.id}"/>`; });
  root.descendants().forEach((d) => { const n = d.data; if (n === ROOT || n.kind !== "group") return; const c = colorOf(n), r = rad(d.depth), blk = blockIds.has(n.id);
    const arc = d3.arc().innerRadius(r - 5).outerRadius(r + 5).startAngle(d.lo - step * 0.42).endAngle(d.hi + step * 0.42)();
    s += `<path class="hit rvband${n.id === sel ? " on" : ""}${blk ? " blk" : ""}${n.children.length ? "" : " empty"}" d="${arc}" transform="translate(${cx},${cy})" style="--c:${c}" data-rid="${n.id}"/>`; });
  leaves.forEach((d) => { const n = d.data; if (n.kind !== "asset") return; const c = colorOf(n), [x, y] = P(d.a, R), blk = blockIds.has(n.id), on = n.id === sel;
    let deg = (d.a * 180) / Math.PI - 90; const flip = deg > 90 && deg < 270; if (flip) deg -= 180;
    s += `<circle class="hit" cx="${x}" cy="${y}" r="${blk || on ? 5 : 3.6}" fill="${blk ? "var(--panel)" : c}" stroke="${blk ? "var(--att)" : on ? "var(--ink)" : "var(--panel)"}" stroke-width="${on || blk ? 2 : 1}" data-rid="${n.id}"/>`;
    const [tx, ty] = P(d.a, R + 9);
    s += `<text class="tk" x="${tx}" y="${ty}" transform="rotate(${deg} ${tx} ${ty})" text-anchor="${flip ? "end" : "start"}" dy="3.5" style="font-size:10.5px;fill:${blk ? "var(--att)" : tk(c)}" data-rid="${n.id}">${esc(n.t || "new")}</text>`; });
  s += `<circle class="hit" cx="${cx}" cy="${cy}" r="8" fill="var(--panel)" stroke="${sel === ROOT.id ? "var(--ink)" : "var(--ink-2)"}" stroke-width="${sel === ROOT.id ? 3 : 2}" data-rid="${ROOT.id}"/>`;
  el.innerHTML = s + "</svg>";
}

function drawWeights() {
  const el = $("#rv-w"), W = el.clientWidth, rows = nodesInOrder(), top = 34, RH = Math.max(18, Math.min(30, (el.clientHeight - top - 12) / Math.max(1, rows.length))), H = top + rows.length * RH + 10;
  const x = wscale(206, W - 96), indent = (n) => 14 + 14 * (depthOf(n) - 1);
  let s = svgOpen(W, H) + wAxis(x, top - 4, H - 6) + `<text class="ax" x="${W - 96}" y="${top - 18}" text-anchor="end">square-root scale</text>`;
  const rowOf = new Map(rows.map((n, i) => [n.id, i])), Y = (i) => top + i * RH;
  rows.forEach((n, i) => { s += `<rect class="hit wrow${n.id === sel ? " on" : ""}" x="0" y="${Y(i)}" width="${W}" height="${RH}" data-rid="${n.id}"/>`; });
  rows.forEach((n) => { if (n.kind !== "group" || !n.children.length) return; const last = (g) => (g.kind === "group" && g.children.length ? last(g.children[g.children.length - 1]) : g), i0 = rowOf.get(n.id), i1 = rowOf.get(last(n).id), gx = indent(n) + 3;
    s += `<line x1="${gx}" x2="${gx}" y1="${Y(i0) + RH - 3}" y2="${Y(i1) + RH / 2}" stroke="${tint(colorOf(n), 55)}" stroke-width="1.5"/>`; });
  rows.forEach((n, i) => { const c = colorOf(n), y = Y(i), isG = n.kind === "group", blk = blockIds.has(n.id), lx = indent(n) + (isG ? 0 : 6);
    if (!isG) { const p = parentOf(n); s += `<line x1="${indent(p) + 3}" x2="${lx - 2}" y1="${y + RH / 2}" y2="${y + RH / 2}" stroke="${tint(colorOf(p), 55)}" stroke-width="1.5"/>`; }
    s += isG ? `<text x="${lx}" y="${y + RH / 2 + 4}" style="font-weight:600;${blk ? "fill:var(--att)" : ""}">${esc(n.name)}${n.children.length ? "" : ` <tspan class="mu" style="font-weight:400">empty</tspan>`}</text>`
      : `<text class="tk" x="${lx}" y="${y + RH / 2 + 4}" style="fill:${blk ? "var(--att)" : tk(c)}">${esc(n.t || "new asset")}${n.exIdio ? ` <tspan class="mu" style="font-weight:400;font-family:var(--sans)">market jumps only</tspan>` : ""}</text>`;
    const h = isG ? 10 : 6; s += rail(n, x, y + (RH - h) / 2, h, isG ? tint(c, 62) : c, { quiet: true });
    if (!(isG && !n.children.length) && (bad(n) || !free(n) || ownEff(n)[0] < n._eff[0] - 1e-6 || ownEff(n)[1] > n._eff[1] + 1e-6)) s += `<text x="${W - 22}" y="${y + RH / 2 + 4}" text-anchor="end" class="rng${bad(n) ? " bad" : ""}">${bad(n) ? "nothing fits" : rangeText(n._eff)}</text>`; });   // numbers only where a limit shapes the range
  el.innerHTML = s + "</svg>";
}

function drawReturns() {
  const el = $("#rv-r"), W = el.clientWidth, gs = groupsInOrder(), Rs = new Map(gs.map((g) => [g.id, groupReturn(g)])), top = 30, legendH = 46;
  const RH = Math.max(22, Math.min(36, (el.clientHeight - top - legendH) / Math.max(1, gs.length))), H = top + gs.length * RH + 6, x = d3.scaleLinear().domain(retDomain([...Rs.values()])).range([160, W - 16]);
  let s = svgOpen(W, H);
  x.ticks(5).forEach((t) => s += `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 4}" y2="${H - 4}" stroke="${Math.abs(t) < 1e-9 ? "var(--frame-2)" : "var(--frame)"}"/><text class="ax" x="${x(t)}" y="${top - 9}" text-anchor="middle">${t > 0 ? "+" : t < 0 ? MINUS : ""}${Math.abs(Math.round(t * 100))}</text>`);
  s += `<text class="ax" x="${W - 16}" y="${top - 21}" text-anchor="end">% a year</text>`;
  gs.forEach((g, i) => { const y = top + i * RH, R = Rs.get(g.id), c = g === ROOT ? "var(--ink)" : colorOf(g), lx = 12 + 12 * depthOf(g);
    s += `<rect class="hit wrow${g.id === sel ? " on" : ""}" x="0" y="${y}" width="${W}" height="${RH}" data-rid="${g.id}"/>`;
    s += `<text x="${lx}" y="${y + RH / 2 + 4}" style="font-weight:${g === ROOT ? 700 : 600}">${esc(g.name)}</text>`;
    s += R ? retRow(R, x, y + RH / 2 - (R.vw ? 3 : 0), c) : `<text class="mu" x="${x.range()[0]}" y="${y + RH / 2 + 4}">${g.children.length ? "no prices yet" : "empty"}</text>`; });
  el.innerHTML = s + `</svg><div class="legend rvlegend">${retLegend(gs.some((g) => Rs.get(g.id)?.vw), gs.some((g) => Rs.get(g.id) && !Rs.get(g.id).ewOk), gs.some((g) => Rs.get(g.id)?.blend))}</div>`;
}

function drawLimits() {
  const notes = limitNotes();
  $("#rv-l").innerHTML = notes.length ? `<ul class="rvlim">${notes.map((x) => `<li${x.b ? ' class="b"' : ""} data-rids="${x.ids.join(" ")}" style="--c:${find(x.id) === ROOT ? "var(--ink-2)" : colorOf(find(x.id))}">${esc(x.text)}</li>`).join("")}</ul>`
    : `<p class="rvnote" style="padding:10px 12px">No limits anywhere: each part can take 0% to 100% of its parent.</p>`;
}

function drawSettings() {
  const gs = groupsInOrder(), head = SETTINGS.map((S) => `<span class="sh">${SHORT[S.k]}</span>`).join(""), defs = SETTINGS.map((S) => `<span class="sd">${DEFAULT_INSIDE(S)}</span>`).join("");
  const cell = (g, S) => { const r = resolve(g, S.k), v = fmtSet(S, r.v), kind = r.src === "set here" ? "h" : r.src === "default" ? "d" : "f";
    const show = v !== DEFAULT_INSIDE(S);   // a value is written only where it differs from the default, whatever its source
    return `<span class="sc ${kind}" data-tipx="${esc(`${S.label} in ${g.name}: ${S.k === "strict" ? S.opts.find((o) => o[0] === r.v)[1] : v}, ${r.src}`)}"><i></i>${show ? v : ""}</span>`; };
  $("#rv-s").innerHTML = `<div class="sgrid"><span class="sn"></span>${head}<span class="sn mu">default</span>${defs}`
    + gs.map((g) => `<span class="sn" data-rid="${g.id}" style="padding-left:${8 + 12 * depthOf(g)}px;--c:${g === ROOT ? "var(--ink-2)" : colorOf(g)}">${esc(g.name)}</span>${SETTINGS.map((S) => cell(g, S)).join("")}`).join("")
    + `</div><div class="legend rvlegend"><span><i class="sg d"></i>default</span><span><i class="sg h"></i>set here</span><span><i class="sg f"></i>from a parent</span></div>`;
}

function drawBar() {
  const { blocks, notes } = issues(), sr = searches(), one = groupsInOrder().filter((g) => g !== ROOT && g.children.length === 1).length;
  $("#rv-bar").innerHTML = `<div class="verdict${blocks.length ? " no" : ""}">${blocks.length ? `<b>${MARK.no}Blocked</b><span>${blocks.length} thing${blocks.length === 1 ? "" : "s"} to fix in the builder; click one to go there</span>` : `<b>${MARK.ok}Feasible</b><span>every limit can be met at once</span>`}</div>`
    + (blocks.length || notes.length ? `<ul class="iss">${blocks.concat(notes).map((x) => `<li data-cid="${x.id}" data-rids="${x.id}"><span class="${x.b ? "b" : "n"}">${x.b ? "Blocks" : "Note"}</span>${esc(x.text)}</li>`).join("")}</ul>`
      : `<p class="srch"><b>${sr.length}</b> search${sr.length === 1 ? "" : "es"}${one ? `; ${one} subportfolio${one === 1 ? "" : "s"} with one member take${one === 1 ? "s" : ""} 100% with no search` : ""}. Each search picks the mix inside one subportfolio, from the inside out.</p>`)
    + `<p class="rwt">${runWideText()}</p>`;
}

RV.draw = () => { blockIds = new Set(issues().blocks.map((b) => b.id)); drawRadial(); drawWeights(); drawReturns(); drawLimits(); drawSettings(); drawBar(); };
{ const ro = new ResizeObserver(() => { if (REVIEW) RV.draw(); }); ["#rv-tree", "#rv-w", "#rv-r"].forEach((q) => ro.observe($(q))); }

// linking: hover lights the same part in every panel; click selects it
const lit = (ids) => { wall.classList.toggle("lit", !!ids); wall.querySelectorAll("[data-rid]").forEach((e) => e.classList.toggle("hl", !!ids && ids.includes(e.dataset.rid))); };
wall.addEventListener("pointerover", (e) => { const t = e.target.closest("[data-rid], [data-rids]"); lit(t ? (t.dataset.rids || t.dataset.rid).split(" ") : null); });
wall.addEventListener("pointerleave", () => { lit(null); rvTip(null); });
wall.addEventListener("pointermove", (e) => { const t = e.target.closest("[data-tipx], [data-rid]"); if (!t) return rvTip(e);
  if (t.dataset.tipx) return rvTip(e, esc(t.dataset.tipx)); const n = find(t.dataset.rid); rvTip(e, n && n !== ROOT ? reviewTip(n) : n ? `<b>${esc(ROOT.name)}</b><br>${retText(ROOT)}` : null); });
wall.addEventListener("click", (e) => { const c = e.target.closest("[data-cid]"); if (c) return closeReview(c.dataset.cid);
  const t = e.target.closest("[data-rid]"); if (t) { sel = t.dataset.rid; RV.draw(); lit(null); } });
}
