// Chart module "band" (app/charts/band): the sensitivity band (#6, #8) as a dot-and-range per child of the selected
// subportfolio: the dot is the share of the parent the run chose, the bar the 10th-90th percentile over K repeats.
registerPanel("band", {
  title: "Sensitivity band", sub: () => "share of the parent, 10th–90th percentile over the repeats", follows: true,
  draw(el) {
    const s = selRow(), g = s.kind === "group" ? s : M0.get(s.path.join("/")) || R0.rows[0];
    const ch = kids(R0, g), banded = ch.filter((r) => r.band);
    if (!banded.length) { el.innerHTML = `<p class="mu" style="padding:14px">No sensitivity band for ${esc(g.name)}: turn it on for the Portfolio in the builder (Sensitivity band, repeats) and run again.</p>`; return; }
    const W = el.clientWidth, H = el.clientHeight, m = { l: 120, r: 96, t: 24, b: 26 }, rh = Math.min(28, (H - m.t - m.b) / ch.length);
    const x = d3.scaleLinear().domain([0, Math.min(1, d3.max(ch, (r) => Math.max(r.share, r.band ? r.band.p90 : 0)) * 1.1 || 1)]).nice().range([m.l, W - m.r]);
    let out = `<text x="${m.l}" y="14" class="mu">${esc(g.name)}: K = ${banded[0].band.k} repeats</text>`;
    x.ticks(5).forEach((t) => (out += `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--frame)"/><text x="${x(t)}" y="${H - 8}" text-anchor="middle">${pct(t, 0)}</text>`));
    ch.forEach((r, i) => { const y = m.t + i * rh + rh / 2, c = chartColor(r);
      out += `<text class="lbl" x="${m.l - 8}" y="${y + 4}" text-anchor="end">${esc(r.name)}</text>`;
      if (r.band) out += `<line x1="${x(r.band.p10)}" x2="${x(r.band.p90)}" y1="${y}" y2="${y}" stroke="color-mix(in oklab, ${c} 55%, var(--panel))" stroke-width="6" stroke-linecap="round"/>`;
      out += `<circle cx="${x(r.share)}" cy="${y}" r="4" fill="${c}"/><text x="${W - m.r + 6}" y="${y + 4}">${pct(r.share, 1)}${r.band ? ` <tspan class="mu">± ${pts(r.band.sd)}</tspan>` : ""}</text>`; });
    el.innerHTML = svg(W, H, out);
  },
});
