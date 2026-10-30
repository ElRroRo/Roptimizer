// The jump-data wall's live data (#9, #12): the version in use (this portfolio's pinned one, else the newest), its
// calibrated parameters, the editable pool against the default, and the held assets from the portfolio.
const JVERS = API.get("/api/jumpdb").items;
if (!JVERS.length) throw new Error("the jump database has no version yet: run python -m mso jumpdb recalibrate");
const PF_ = LIVE.portfolio, PINNED = PF_.run && PF_.run.jump_version && PF_.run.jump_version !== "latest" ? PF_.run.jump_version : null;
const INUSE = PINNED || JVERS[JVERS.length - 1].version;
const VINFO = API.get(`/api/jumpdb/${encodeURIComponent(INUSE)}`);
const POOLNOW = API.get("/api/jumpdb/pool");
const DATA = (() => {
  const rows = LIVE.last_run ? LIVE.last_run.rows.map((r) => ({ name: r.path[r.path.length - 1], path: r.path.slice(0, -1), effective: r.effective,
    kind: (PF_.assets[r.path[r.path.length - 1]] && r.path.length > 1) ? "asset" : "group" })) : [];
  if (!rows.length) {   // no run yet: the tree as it stands
    const walk = (n, path) => { const name = n.kind === "asset" ? n.ticker : n.name; rows.push({ name, path, kind: n.kind, effective: null });
      (n.children || []).forEach((c) => walk(c, [...path, name])); };
    walk(PF_.tree, []); }
  return { created: new Date().toISOString(), inputs_created: INUSE, runs: [{ rows }], jumps: VINFO.params.jump_config };
})();
