// Loads the page's real data from the optimizer's API before the screens' scripts run. Synchronous on purpose:
// the accepted designs read their data at load time (they were built on files), so the data must exist first.
// ?p=<portfolio id> picks the portfolio (else the last one used, else the first in the library);
// ?run=<run id> also loads that run (the progress and results views).
(function () {
  const q = new URLSearchParams(location.search);
  function get(url) {
    const x = new XMLHttpRequest();
    x.open("GET", url, false);
    x.send();
    if (x.status >= 400) throw new Error(`${url}: ${x.status} ${x.responseText.slice(0, 300)}`);
    return JSON.parse(x.responseText);
  }
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } };
  window.API = { get, store };
  // where runs go: this computer, or a Colab GPU chosen on the setup screen (A100 unless set)
  window.colabGPU = () => store("mso.colab_gpu") || "A100";
  window.machName = (rec) => (rec && rec.machine === "a100" ? `Colab ${(rec.settings && rec.settings.gpu) || "A100"}` : "this computer");
  let run = null, results = null;
  if (q.get("run")) {
    run = get(`/api/runs/${encodeURIComponent(q.get("run"))}`);
    if (run.status === "done") results = get(`/api/runs/${encodeURIComponent(run.id)}/results`);
  }
  let pid = q.get("p") || (run && run.portfolio_id) || store("mso.portfolio");
  const list = get("/api/portfolios").items;
  if (!pid || !list.some((x) => x.id === pid)) pid = list.length ? list[0].id : null;
  if (!pid) throw new Error("the library has no portfolio");
  store("mso.portfolio", pid);
  window.LIBRARY = list;
  window.LIVE = get(`/api/live?portfolio=${encodeURIComponent(pid)}`);
  window.LIVE.run = run;
  window.LIVE.results = results;
  window.HIST = LIVE.hist || { fetched: "n/a", tickers: [], series: {}, corr: [], overlap: [] };
})();
