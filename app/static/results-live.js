// The run behind results.html, in the shape the accepted screens read (they were built on tree_run.py's file):
// DATA = {created, inputs_created, gpu, config, tickers, er_12w, bank_build_s, runs: [this run, the one to compare]}.
// A finished run comes from its results.json; a run still going is drawn from its frozen tree (no figures yet).
// Row paths here exclude the row itself (the Portfolio's path is []), as in the prototypes.
const limNum = (L, side) => (L && L[side] && L[side].on && L[side].value != null ? L[side].value : null);

// A run made before the ratios were reported (2026-10-30) still has what Sharpe and STARR need, exactly; the
// ratios that need the paths themselves (Sortino, Omega, Martin...) stay empty until it is run again.
function withRatios(m, rf) {
  if (!m || m.sharpe !== undefined || rf == null) return m;
  const ex = m.er_12w - rf, sharpe = m.vol_12w > 0 ? ex / m.vol_12w : null;
  return { ...m, sharpe, sharpe_ann: sharpe == null ? null : sharpe * Math.sqrt(52 / 12), starr: m.cvar < 0 ? ex / -m.cvar : null, partial: true };
}

function adaptRun(res, rec) {
  const rows = res.rows.map((r) => ({
    name: r.name, kind: r.kind, path: r.path.slice(0, -1), share: r.share, effective: r.effective,
    limits: { min: limNum(r.limits, "min"), max: limNum(r.limits, "max") },
    search: r.search ? { ...r.search, wall_s: r.search.wall_s ?? 0 } : undefined,
    metrics: withRatios(r.metrics, res.rf_12w), fan: r.fan, ret_hist: r.ret_hist, dd_hist: r.dd_hist, band: r.band,
    implied: r.implied_annual, blended: r.blended_annual, view: r.view }));
  const label = `${rec.portfolio_name || "Run"}, ${machName(rec)}`;
  return { id: rec.id, label, finished: rec.ended || res.created, wall_s: res.wall_s ?? rec.wall_s ?? 0, effective: res.weights,
    validation_paths: res.config.bank - res.config.train, rows, machine: rec.machine, record: rec, res };
}

function skeletonRun(rec) {   // a run that has not finished: its frozen tree, with no figures
  const P = rec.portfolio, rows = [];
  const walk = (n, path) => {
    const name = n.kind === "asset" ? n.ticker : n.name;
    const kids = n.children || [], fixed = kids.length > 1 && kids.every((c) => limNum(c.limits, "min") != null && limNum(c.limits, "min") === limNum(c.limits, "max"));
    rows.push({ name, kind: n.kind, path, share: null, effective: null, limits: { min: limNum(n.limits, "min"), max: limNum(n.limits, "max") },
      search: n.kind === "group" ? { generations: kids.length > 1 && !fixed ? ((n.settings || {}).maxgen || 80) : 0, wall_s: 0, history: [], binding: [] } : undefined,
      metrics: {} });
    kids.forEach((c) => walk(c, [...path, name]));
  };
  walk(P.tree, []);
  return { id: rec.id, label: `${rec.portfolio_name}, ${machName(rec)} (${rec.status})`,
    finished: rec.queued, wall_s: 0, effective: {}, validation_paths: 0, rows, machine: rec.machine, record: rec, skeleton: true };
}

const DATA = (() => {
  const rec = LIVE.run, res = LIVE.results;
  if (!rec) throw new Error("results.html needs ?run=<run id>");
  const R0 = res ? adaptRun(res, rec) : skeletonRun(rec);
  // Compare (#8): with ?base=<run id> the page holds [baseline, this run] in the accepted code's order (the first run
  // is the baseline); without it, the latest other finished run of this portfolio is held for Compare's menu.
  const q = new URLSearchParams(location.search);
  const others = (LIVE.runs || []).filter((r) => r.status === "done" && r.id !== rec.id);
  let runs = [R0, R0];
  if (q.get("base") && res) {
    const b = API.get(`/api/runs/${encodeURIComponent(q.get("base"))}`);
    runs = [adaptRun(API.get(`/api/runs/${encodeURIComponent(b.id)}/results`), b), R0];
  }
  const cfg = res ? res.config : { bank: 0, train: 0 };
  let model = { heston: {}, jumps: null };
  if (res) { try { model = API.get(`/api/runs/${encodeURIComponent(rec.id)}/model`); } catch { /* a run without frozen inputs */ } }
  return {
    created: res ? res.created : rec.queued, inputs_created: res ? (res.inputs.data_downloaded || res.inputs.created || res.created) : rec.queued,
    gpu: res ? res.gpu : (rec.machine === "a100" ? machName(rec) : LIVE.device || "this computer"),
    config: { ...cfg, subset: cfg.draw, horizon_weeks: 12, rf_12w: res ? res.rf_12w : null,
      // the stop rule as the Portfolio's search used it (each search records its own in its settings)
      window: res ? +((res.rows[0].search.settings || {}).window || {}).value || 5 : 5,
      tol: res ? +((res.rows[0].search.settings || {}).tol || {}).value || 0.0002 : 0.0002 },
    tickers: res ? res.tickers : [], er_12w: res ? res.er_12w : {}, bank_build_s: res ? res.bank_s : 0,
    runs, live: !res, compareBase: q.get("base"), others, thisRun: R0, heston: model.heston || {}, jumps: model.jumps, model,
  };
})();
