// The library on the builder: the portfolio picker (where the prototype had its sample trees, same control) and
// Refresh data (#9: always available; it re-downloads the day's market data, then reloads with the new prices).
{ const ph = document.querySelector(".panel.tree .ph"), lab = document.createElement("label");
  lab.className = "preset";
  lab.innerHTML = `Portfolio <select id="preset">${LIBRARY.map((p) => `<option value="${esc(p.id)}"${p.id === PF.id ? " selected" : ""}>${esc(p.name)}</option>`).join("")}`
    + `<option value="__dup">Duplicate this portfolio…</option><option value="__new">New empty portfolio…</option><option value="__del">Delete this portfolio…</option></select>`;
  ph.insertBefore(lab, document.getElementById("foldall"));
  document.getElementById("preset").addEventListener("change", async (e) => {
    const v = e.target.value;
    if (v === "__del") {   // the portfolio goes; its runs stay in the run library
      if (LIBRARY.length < 2) { alert("This is the only portfolio in the library: create another one before deleting it."); e.target.value = PF.id; return; }
      if (!confirm(`Delete "${PF.name}"? Its saved runs stay in the run library. This cannot be undone.`)) { e.target.value = PF.id; return; }
      clearTimeout(saveTimer); DELETED = true;   // a late save would recreate it on the server
      const r = await fetch(`/api/portfolios/${PF.id}`, { method: "DELETE" });
      if (!r.ok) { alert(`Not deleted: ${(await r.json()).detail}`); e.target.value = PF.id; return; }
      API.store("mso.portfolio", ""); location.search = `?p=${LIBRARY.find((x) => x.id !== PF.id).id}`; return; }
    if (v === "__dup" || v === "__new") {
      const name = prompt(v === "__dup" ? "Name of the copy" : "Name of the new portfolio", v === "__dup" ? `${PF.name} (copy)` : "New portfolio");
      if (!name) { e.target.value = PF.id; return; }
      const r = v === "__dup"
        ? await fetch(`/api/portfolios/${PF.id}/duplicate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) })
        : await fetch("/api/portfolios", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, assets: {} }) });
      const d = await r.json(); location.search = `?p=${d.id}`; return; }
    location.search = `?p=${v}`;
  });
  const rb = document.createElement("button");
  rb.className = "q"; rb.id = "refresh"; rb.type = "button"; rb.textContent = "Refresh data";
  rb.title = `Market data of ${HIST.fetched}. Downloads the day's prices again, then reloads.`;
  document.getElementById("undo").before(rb);
  rb.addEventListener("click", async () => {
    rb.disabled = true; rb.textContent = "Refreshing…";
    try {
      await saveNow();
      const job = await (await fetch("/api/data/refresh", { method: "POST" })).json();
      for (let i = 0; i < 600; i++) {
        const j = await (await fetch(`/api/jobs/${job.id}`)).json();
        if (j.status === "done") { location.reload(); return; }
        if (j.status === "failed") throw new Error(j.error || "failed");
        await new Promise((r) => setTimeout(r, 500)); }
    } catch (err) { rb.disabled = false; rb.textContent = "Refresh data"; $("#note").textContent = `Refresh data failed: ${err.message}`; }
  });
}
