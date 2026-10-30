// The model's prior on an asset's mean is N(equilibrium, τ·σ²), so an asset without a view is heard with sd √τ·σ.
// τ = 0.01 is the owner's setting; σ here is 5-year weekly volatility (the run itself uses its own forecast).
const TAU = 0.01;
function eqBand(n) { const s = typeof HIST !== "undefined" && HIST.series[n.t], eq = byTicker[n.t]?.eq; return s && eq != null ? { m: eq, sd: Math.sqrt(TAU) * s.vol } : null; }
// Shared by the round-6 builders: the hover readout (numbers live here and in the editor, not on the canvas),
// and the price cone: five years of weekly closes, then the view as a cone from the last close to the target.
function tipHTML(n) {
  if (n.kind === "group") { const gm = groupModel(n), L = limitLabel(n);
    return `<b>${esc(n.name)}</b> ${countAssets(n)} asset${countAssets(n) === 1 ? "" : "s"}${L ? `<br>${L}` : ""}<br>can take ${effText(n._eff)} of the portfolio${gm ? `<br>group view: model uses ${pct(gm.mean, 1, true)} ± ${pts(gm.sd)}` : ""}`; }
  const m = modelOf(n), T = target(n), eq = byTicker[n.t]?.eq;
  return `<code>${esc(n.t || "new asset")}</code> close ${priceOf(n) == null ? "none yet" : money(priceOf(n))}${T != null ? ` → target ${money(T)}` : ""}`
    + `<br>${m ? `model uses ${pct(m.mean, 1, true)} ± ${pts(m.sd)}` : n.vt ? `<span style="color:var(--att)">needs − / +</span>` : eqBand(n) ? `no view: equilibrium ${pct(eq, 1, true)} ± ${pts(eqBand(n).sd)}<br><span style="color:var(--mute)">± √τ·σ, τ = 0.01, σ from 5 years of weekly prices</span>` : `no view: equilibrium ${pct(eq, 1, true)}`}`
    + `<br>can take ${effText(n._eff)} of the portfolio`;
}
document.addEventListener("pointermove", (e) => {
  const t = document.getElementById("tip"); if (!t || e.target.closest?.("#rv")) return;   // the review wall runs its own readout
  const h = !drag?.on && !document.body.classList.contains("panning") && e.target.closest?.("#canvas [data-id], #canvas [data-gid]");
  if (!h) { t.style.display = "none"; return; }
  const n = find(h.dataset.id || h.dataset.gid); if (!n || n === ROOT) { t.style.display = "none"; return; }
  t.innerHTML = tipHTML(n); t.style.display = "block";
  const x = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8); t.style.left = x + "px"; t.style.top = e.clientY + 14 + "px";
});
// The cone: x = weeks from the last close (history to the left, the view's horizon to the right), y = price on a
// log scale so a +35% and a −20% look like what they are. Returns SVG content for a w × h box.
const HISTWEEKS = 104;
function cone(n, w, h, c, opts = {}) {
  const s = (typeof HIST !== "undefined" && HIST.series[n.t]) || null, P0 = priceOf(n);
  if (!s || P0 == null) { const fs = Math.max(11, Math.min(18, h / 4));   // a new ticker: the chart's frame, waiting for Refresh data
    return `<line x1="2" x2="${w - 2}" y1="${h - 4}" y2="${h - 4}" stroke="var(--frame-2)"/><line x1="${w * 0.67}" x2="${w * 0.67}" y1="4" y2="${h - 4}" stroke="var(--frame-2)"/>`
      + `<text class="mu" x="${w / 2}" y="${h / 2 + fs / 3}" text-anchor="middle" style="font-size:${fs}px">${P0 == null ? "prices arrive with Refresh data" : "no history yet"}</text>`; }
  const closes = s.close.slice(-HISTWEEKS), hw = (n.h / 12) * 52, T = target(n), dm = dollars(n, "um"), dp = dollars(n, "up");
  const lo = T != null && dm != null ? T - dm : null, hi = T != null && dp != null ? T + dp : null, E = eqBand(n);
  const at = (r) => P0 * Math.pow(Math.max(0.01, 1 + r), n.h / 12), eT = E && at(E.m), eLo = E && at(E.m - E.sd), eHi = E && at(E.m + E.sd);
  const vals = closes.concat([P0], [T, lo, hi, eT, eLo, eHi].filter((v) => v != null && v > 0));
  const y = d3.scaleLog().domain([d3.min(vals) * 0.96, d3.max(vals) * 1.04]).range([h - (opts.pb ?? 4), opts.pt ?? 4]);
  const x = d3.scaleLinear().domain([-closes.length, hw]).range([opts.pl ?? 2, w - (opts.pr ?? 2)]);
  let g = `<line x1="${x(0)}" x2="${x(0)}" y1="${opts.pt ?? 4}" y2="${h - (opts.pb ?? 4)}" stroke="var(--frame-2)"/>`;
  const line = d3.line().x((d, i) => x(i - closes.length + 1)).y((d) => y(d)).curve(d3.curveMonotoneX)(closes);
  g += `<path d="${line}" fill="none" stroke="color-mix(in oklab, ${c} 70%, var(--ink-2))" stroke-width="1.3"/>`;
  if (E) {   // equilibrium: what the model uses without a view; under a view it stays as a grey reference
    const ec = T != null ? "var(--ink-2)" : c;
    g += `<path d="M${x(0)},${y(P0)} L${x(hw)},${y(eHi)} L${x(hw)},${y(eLo)} Z" fill="color-mix(in oklab, ${ec} ${T != null ? 10 : 24}%, transparent)"/>`;
    g += `<line x1="${x(0)}" y1="${y(P0)}" x2="${x(hw)}" y2="${y(eT)}" stroke="${ec}" stroke-width="${T != null ? 1 : 1.6}" stroke-opacity="${T != null ? 0.6 : 1}"/><circle cx="${x(hw)}" cy="${y(eT)}" r="2.6" fill="var(--panel)" stroke="${ec}" stroke-width="1.3"/>`;
  }
  if (T != null) {
    if (lo != null && hi != null && lo > 0) g += `<path d="M${x(0)},${y(P0)} L${x(hw)},${y(hi)} L${x(hw)},${y(lo)} Z" fill="color-mix(in oklab, ${c} 26%, transparent)" stroke="none"/>`;
    g += `<line x1="${x(0)}" y1="${y(P0)}" x2="${x(hw)}" y2="${y(T)}" stroke="${c}" stroke-width="1.6"/><circle cx="${x(hw)}" cy="${y(T)}" r="3" fill="${c}"/>`;
    if (n.vt && (dm == null || dp == null)) g += `<circle cx="${x(hw)}" cy="${y(T)}" r="6" fill="none" stroke="var(--att)" stroke-width="1.5"/>`;
  }
  g += `<circle cx="${x(0)}" cy="${y(P0)}" r="2.5" fill="var(--ink)"/>`;
  return g;
}
