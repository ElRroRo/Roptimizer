// Live progress (#8, #12): while this page's run is going, the rings follow its events (/api/runs/<id>/events)
// instead of replaying a finished record. A search's ring fills by generations done over its cap: where it will
// stop is not known in advance. Cancel cancels the run (on the A100 it also shuts the machine down); the machine
// buttons choose where the NEXT run goes; Run again goes back to the review. A finished run reloads as results.
MACH = API.store("mso.machine") || "laptop";
const LIVEP = (() => {
  const rec = LIVE.run, active = rec && ["queued", "running", "waiting"].includes(rec.status);
  return { active, rec, t0: rec && rec.started ? Date.parse(rec.started) / 1000 : Date.now() / 1000, note: null, bank: null };
})();

if (LIVEP.active) {
  const S = [];
  const post = (r) => { kids(R0, r).forEach(post); if (r.kind === "group") S.push(r); };
  post(R0.rows[0]);
  SCHED = S.map((r) => ({ r, t0: Infinity, t1: Infinity, g: r.search.generations, maxg: r.search.generations, gen: 0, live: "wait" }));
  T_END = 1e9;
  now = () => Date.now() / 1000 - LIVEP.t0;
  stateOf = (s) => (s.g === 0 && LIVEP.bank && LIVEP.bank.done >= LIVEP.bank.total ? "one" : s.live);
  fracOf = (s) => { const st = stateOf(s); return st === "done" || st === "one" ? 1 : st === "run" ? Math.min(1, s.gen / Math.max(1, s.maxg)) : 0; };
  PV.t = 0;
  const byPath = (name) => SCHED.find((q) => idOf(q.r) === name.split(" / ").join("/"));
  const src = new EventSource(`/api/runs/${encodeURIComponent(LIVEP.rec.id)}/events`);
  src.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "started") LIVEP.t0 = e.t;
    else if (e.type === "bank") { LIVEP.bank = e; DATA.config.bank = e.total; R0.validation_paths = e.total - Math.floor(e.total * 0.9);
      if (e.done >= e.total) DATA.bank_build_s = e.s; }
    else if (e.type === "search_start") { const q = byPath(e.search); if (q) { q.live = "run"; q.gen = 0; q.t0 = now(); } }
    else if (e.type === "generation") { const q = byPath(e.search); if (q) { q.live = "run"; q.gen = e.gen; } }
    else if (e.type === "search_done") { const q = byPath(e.search); if (q) { q.live = "done"; q.g = q.maxg = e.generations; q.t1 = now(); } }
    else if (e.type === "waiting") LIVEP.note = e.text;
    else if (e.type === "colab") LIVEP.note = `Colab ${e.gpu || "A100"}: balance ${e.balance_before.toFixed(2)} CU at the start${e.rate ? `, ${e.rate} CU an hour` : ""}`;
    else if (e.type === "stage" && e.stage === "packed") LIVEP.note = `inputs frozen and packed; starting the ${machName(LIVEP.rec)}`;
    else if (e.type === "end") {
      src.close();
      if (e.status === "done") { history.replaceState(null, "", "#results"); location.reload(); return; }   // a hash change alone would not reload
      LIVEP.active = false; LIVEP.note = `${e.status}${e.error ? ": " + e.error : ""}`; PV.t = null;
    }
    if (view === "progress") progressTick();
  };
  setInterval(() => { if (LIVEP.active && view === "progress") progressTick(); }, 1000);
  // the header: no replay while a run is live
  const _head = progressHead;
  progressHead = function () { _head(); const r = $("#replay"); if (r) r.remove(); };
  const _tick = progressTick;
  progressTick = function () {
    _tick();
    const sub = $("#prog-sub");
    if (sub) sub.textContent = LIVEP.active ? `live: ${machName(LIVEP.rec)}, ${clock(now())}${LIVEP.note ? `; ${LIVEP.note}` : ""}`
      : LIVEP.note || "";
    const bank = $("#st-bank");
    if (bank && LIVEP.bank) bank.textContent = LIVEP.bank.done >= LIVEP.bank.total ? `${LIVEP.bank.total.toLocaleString("en-US")} paths in ${LIVEP.bank.s} s`
      : `building: ${LIVEP.bank.done.toLocaleString("en-US")} of ${LIVEP.bank.total.toLocaleString("en-US")} paths`;
    const c = $("#cancel"); if (c) { c.disabled = !LIVEP.active; c.title = LIVEP.active ? "Stop the run" : "Nothing is running"; }
    const t = $("#st-time"); if (t) t.textContent = `${clock(now())} so far`;
    const fig = [...document.querySelectorAll("#p-run .stages li")].find((li) => li.querySelector("b")?.textContent === "Figures");
    if (fig) fig.querySelector("span").textContent = R0.validation_paths ? `on ${R0.validation_paths.toLocaleString("en-US")} paths no search sees` : "on the tenth of the bank no search sees";
  };
  const _panel = runPanel;
  runPanel = function () { _panel(); progressTick(); };
}

document.addEventListener("click", async (e) => {
  const m = e.target.closest("[data-m]"); if (m) API.store("mso.machine", m.dataset.m);
  if (e.target.closest("#again")) { e.stopImmediatePropagation(); location.href = `builder.html?p=${encodeURIComponent(LIVE.portfolio.id)}#review`; return; }
  if (e.target.closest("#cancel") && LIVEP.active) {
    const c = $("#cancel"); c.disabled = true; c.textContent = "Cancelling…";
    try { const r = await fetch(`/api/runs/${encodeURIComponent(LIVEP.rec.id)}/cancel`, { method: "POST" }); if (!r.ok) throw new Error((await r.json()).detail); }
    catch (err) { $("#note").textContent = `Cancel failed: ${err.message}`; c.disabled = false; c.textContent = "Cancel"; }
  }
}, true);
