"""Roptimizer's server (#11), on port 8797 (MSO_PORT).

Run with the repo's venv: `.venv/bin/python -m app.server`. It serves the API under /api and the screens
under / (app/static). It never touches the GPU: every run is a child process on a lane (app/runner.py).
Every JSON response carries `as_of` (the day's market data) and `jump_version` (the newest version).
POST /api/shutdown is refused (409) while an A100 run is in progress, because a killed server could leave
a Colab VM billing.
"""
import asyncio
import contextlib
import json
import os
import queue

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mso import betas, colab, jumpdb
from mso import portfolio as pf
from mso.cache import DayCache

from . import setup
from .library import Conflict, Library, NotFound
from .runner import Runner

PORT = int(os.environ.get("MSO_PORT", 8797))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

lib = Library()
runner = Runner(lib)
_server = {}


@contextlib.asynccontextmanager
async def lifespan(_app):
    import threading
    threading.Thread(target=setup.probe_device, daemon=True).start()
    seeded = lib.seed_if_empty()
    rec = runner.recover()
    _server["startup"] = dict(seeded=seeded["id"] if seeded else None, **rec)
    print(f"[server] port {PORT}; seeded: {_server['startup']['seeded']}; interrupted runs: "
          f"{rec['interrupted']}; Colab sessions stopped: {rec['sessions_stopped']}", flush=True)
    yield


app = FastAPI(title="Roptimizer", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)


@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    """The screens' files must never be served from the browser's cache after an update: the browser checks
    for a new version on every load (a 304 when nothing changed)."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def stamp():
    c = DayCache()
    try:
        v = jumpdb.load("latest")
        jv = dict(version=v["version"], age_days=v["age_days"], stale=v["stale"])
    except FileNotFoundError:
        jv = None
    return dict(as_of=dict(day=c.day, downloaded=c.downloaded_at(), series=len(c.index)), jump_version=jv)


def ok(body):
    if isinstance(body, dict):
        return JSONResponse({**body, **stamp()})
    return JSONResponse({"items": body, **stamp()})


def guard(fn):
    try:
        return fn()
    except NotFound as e:
        raise HTTPException(404, f"not found: {e}")
    except Conflict as e:
        raise HTTPException(409, str(e))
    except (ValueError, pf.PortfolioError) as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------ health, lanes, shutdown
@app.get("/api/health")
def health():
    return ok(dict(ok=True, lanes=runner.status(), startup=_server.get("startup")))


@app.get("/api/lanes")
def lanes():
    return ok(runner.status())


@app.post("/api/shutdown")
def shutdown():
    if runner.a100_busy():
        raise HTTPException(409, "an A100 run is in progress: cancel it first (stopping now could leave a Colab VM billing)")
    for lane in ("laptop", "data"):
        if runner.current[lane] is not None:
            raise HTTPException(409, f"a {lane} job is running: cancel it or wait for it")
    srv = _server.get("uvicorn")
    if srv:
        srv.should_exit = True
    return ok(dict(ok=True))


# ------------------------------------------------------------ portfolios
@app.get("/api/portfolios")
def portfolios():
    return ok(lib.portfolios())


@app.post("/api/portfolios")
def create_portfolio(p: dict = Body(...)):
    p = dict(p)
    p.pop("version", None)
    p.pop("id", None)
    if "tree" not in p:
        p = pf.new(p.get("name", "New portfolio"), p.get("assets", {}))
    return guard(lambda: ok(lib.save(p)))


@app.get("/api/portfolios/{pid}")
def get_portfolio(pid: str):
    return guard(lambda: ok(lib.get(pid)))


@app.put("/api/portfolios/{pid}")
def put_portfolio(pid: str, p: dict = Body(...)):
    """Save with the version the editor loaded; a stale save gets 409."""
    p = dict(p)
    p["id"] = pid
    return guard(lambda: ok(lib.save(p, expected_version=p.get("version"))))


@app.delete("/api/portfolios/{pid}")
def delete_portfolio(pid: str):
    return guard(lambda: (lib.delete(pid), ok(dict(ok=True)))[1])


@app.post("/api/portfolios/{pid}/duplicate")
def duplicate_portfolio(pid: str, body: dict = Body(default={})):
    return guard(lambda: ok(lib.duplicate(pid, body.get("name"))))


@app.post("/api/import/csv")
def import_csv(body: dict = Body(...)):
    """{"path": a CSV on this machine} or {"csv": the file's text, "name": ...}, in v4.1's format."""
    import tempfile
    if body.get("csv"):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(body["csv"])
            path = f.name
    else:
        path = body.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(400, "give a CSV path or its text")
    return guard(lambda: ok(lib.import_csv(path, body.get("name"))))


@app.post("/api/portfolios/{pid}/review")
def review(pid: str):
    """The pre-run review's data that needs no fits: blockers, each setting with its source, each child's
    possible share and each asset's possible effective weight under the limits, data time, jump version."""
    p = guard(lambda: lib.get(pid))
    return ok(dict(blockers=pf.blockers(p), settings={" / ".join(k): v for k, v in pf.resolve(p["tree"]).items()},
                   ranges=ranges(p), run=p.get("run")))


def ranges(p):
    """Share-of-parent range of every node, alone (its own limits) and with its siblings' limits, and the
    effective-weight range they imply."""
    out = {}

    def go(node, path, eff_lo, eff_hi):
        kids = node.get("children", [])
        lo = [pf.limit_value(c.get("limits"), "min") or 0.0 for c in kids]
        hi = [1.0 if pf.limit_value(c.get("limits"), "max") is None else pf.limit_value(c.get("limits"), "max") for c in kids]
        for i, c in enumerate(kids):
            s_lo = max(lo[i], 1.0 - (sum(hi) - hi[i]))
            s_hi = min(hi[i], 1.0 - (sum(lo) - lo[i]))
            name = c.get("name") or c["ticker"]
            e_lo, e_hi = eff_lo * max(s_lo, 0.0), eff_hi * min(s_hi, 1.0)
            pmn, pmx = pf.limit_value(c.get("portfolio_limits"), "min"), pf.limit_value(c.get("portfolio_limits"), "max")
            if pmn is not None:
                e_lo = max(e_lo, pmn)
            if pmx is not None:
                e_hi = min(e_hi, pmx)
            out[" / ".join(path + (name,))] = dict(own=[lo[i], hi[i]], with_siblings=[s_lo, s_hi], effective=[e_lo, e_hi])
            go(c, path + (name,), e_lo, e_hi)

    go(p["tree"], (p["tree"]["name"],), 1.0, 1.0)
    return out


# ------------------------------------------------------------ what the screens load
@app.get("/api/live")
def live(portfolio: str, extra: str = ""):
    """Everything the builder and review read for one portfolio: the portfolio, today's price of every asset
    (a ticker with no price is listed in `missing`: its card waits for Refresh data), 5 years of weekly
    history, crash/rally betas, and the latest finished run's summary. `extra` adds tickers being typed in."""
    from mso import history
    p = guard(lambda: lib.get(portfolio))
    T = list(dict.fromkeys(pf.tickers(p) + [t.strip().upper() for t in extra.split(",") if t.strip()]))
    c = DayCache()
    prices, missing = {}, {}
    for t in T:
        try:
            v, when = c.last_price(t)
            prices[t] = dict(price=v, time=when)
        except Exception as e:
            missing[t] = f"{type(e).__name__}: {e}"
    have = [t for t in T if t in prices]
    hist = history.build(have, c) if have else None
    try:
        bt = betas.ticker_table(have, jumpdb.load("latest"), c) if have else {}
    except FileNotFoundError:
        bt = {}
    last = None
    for r in lib.runs(portfolio):
        if r.get("status") == "done":
            res = lib.results(r["id"])
            root = res["rows"][0]
            last = dict(id=r["id"], ended=r.get("ended"), machine=r["machine"], gpu=res.get("gpu"),
                        bank=res["config"]["bank"], metrics=root["metrics"], objective=root["search"].get("incumbent"),
                        weights=res["weights"], inputs=res.get("inputs", {}).get("data_day"),
                        rows=[dict(path=x["path"], share=x["share"], effective=x["effective"],
                                   implied=x.get("implied_annual"), blended=x.get("blended_annual")) for x in res["rows"]])
            break
    try:
        rf = c.last_price("^TNX")[0] / 100            # today's risk-free rate, used when the portfolio sets none
    except Exception:
        rf = None
    return ok(dict(portfolio=p, prices=prices, missing=missing, hist=hist, betas=bt, last_run=last, rf=rf, device=setup.STATE["device"],
                   runs=lib.runs(portfolio)[:20]))


# ------------------------------------------------------------ market data and the jump database
@app.get("/api/prices")
def prices(tickers: str):
    """Last close and its time for each ticker, from the day's data (trade-as tickers get their own price, #8)."""
    c, out, missing = DayCache(), {}, {}
    for t in [x.strip().upper() for x in tickers.split(",") if x.strip()]:
        try:
            v, when = c.last_price(t)
            out[t] = dict(price=v, time=when)
        except Exception as e:
            missing[t] = f"{type(e).__name__}: {e}"
    return ok(dict(prices=out, missing=missing))


@app.get("/api/data/status")
def data_status():
    c = DayCache()
    return ok(dict(day=c.day, downloaded=c.downloaded_at(), series=len(c.index)))


@app.post("/api/data/refresh")
def data_refresh():
    return ok(runner.submit_data("refresh"))


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = runner.jobs.get(jid)
    if not j:
        raise HTTPException(404, jid)
    return ok(j.record)


@app.get("/api/jumpdb")
def jumpdb_list():
    out = []
    for n in jumpdb.versions():
        v = jumpdb.load(n)
        diag = json.load(open(os.path.join(v["path"], "diagnostics.json")))
        out.append(dict(version=n, age_days=v["age_days"], stale=v["stale"], pool_counts=diag.get("pool_counts"),
                        jump_config=v["jump_config"], hawkes_config=v["hawkes_config"], cojump_config=v["cojump_config"]))
    return ok(out)


@app.get("/api/jumpdb/pool")
def pool_get():
    return ok(dict(jumpdb.load_pool(), default=jumpdb.default_pool()["tickers"]))


@app.put("/api/jumpdb/pool")
def pool_put(body: dict = Body(...)):
    return guard(lambda: ok(jumpdb.save_pool(body.get("tickers", []))))


@app.post("/api/jumpdb/pool/reset")
def pool_reset():
    return ok(jumpdb.reset_pool())


@app.post("/api/jumpdb/recalibrate")
def recalibrate():
    return ok(runner.submit_data("recalibrate"))


@app.get("/api/jumpdb/{version}")
def jumpdb_get(version: str):
    try:
        v = jumpdb.load(version)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    files = {}
    for n in ("pool.json", "diagnostics.json", "lowess.json", "tickers.json"):
        p = os.path.join(v["path"], n)
        if os.path.exists(p):
            files[n.split(".")[0]] = json.load(open(p))
    return ok(dict(params={k: x for k, x in v.items() if k != "path"}, **files))


@app.get("/api/jumpdb/{version}/regime.png")
def regime_png(version: str):
    v = jumpdb.load(version)
    return FileResponse(os.path.join(v["path"], "regime.png"))


@app.get("/api/betas")
def betas_get(tickers: str, version: str = "latest"):
    """Crash/rally betas and co-jumps (computed on first use, which may download)."""
    T = [t.strip() for t in tickers.split(",") if t.strip()]
    return guard(lambda: ok(betas.ticker_table(T, jumpdb.load(version), DayCache())))


@app.put("/api/betas/{ticker}")
def betas_put(ticker: str, body: dict = Body(...)):
    """{"crash": x|null, "rally": x|null}; both null removes the manual betas."""
    return ok(betas.set_override(ticker, body.get("crash"), body.get("rally")))


# ------------------------------------------------------------ runs
@app.post("/api/runs")
def submit(body: dict = Body(...)):
    """{"portfolio_id", "machine": "laptop"|"a100", "options": {...}}. The portfolio is frozen now."""
    p = guard(lambda: lib.get(body["portfolio_id"]))
    found = pf.blockers(p)
    if found:
        raise HTTPException(400, dict(blockers=found))
    opts = dict(body.get("options") or {})
    if (p.get("run") or {}).get("bands") and "bands" not in opts:          # the Portfolio's sensitivity-band setting
        opts["bands"] = int(p["run"]["bands"])
    return guard(lambda: ok(runner.submit_run(p, body.get("machine", "a100"), opts)))


@app.get("/api/runs")
def runs(portfolio_id: str = None):
    return ok(lib.runs(portfolio_id))


@app.get("/api/runs/{rid}")
def run_get(rid: str):
    """The run's record, with the portfolio as it was frozen when the run was queued."""
    def body():
        r = lib.run(rid)
        pth = os.path.join(lib.run_dir(rid), "portfolio.json")
        if os.path.exists(pth):
            r = dict(r, portfolio=json.load(open(pth)))
        return ok(r)
    return guard(body)


@app.get("/api/runs/{rid}/results")
def run_results(rid: str):
    return guard(lambda: ok(lib.results(rid)))


@app.get("/api/runs/{rid}/model")
def run_model(rid: str):
    """The model behind a run, from its frozen inputs: Heston per asset (with fits at a bound and pooled
    fallbacks), jump, Hawkes and co-jump configs, jump betas, co-jump multipliers, the S&P volatility path,
    posterior returns and the risk-free rate (the Diagnostics tab)."""
    path = os.path.join(lib.run_dir(rid), "inputs.json")
    if not os.path.exists(path):
        raise HTTPException(404, f"{rid} has no frozen inputs")
    snap = json.load(open(path))
    kw = snap["run_optimization_kwargs"]
    sc = kw.get("sim_config", {})
    T = kw["tickers"]
    return ok(dict(tickers=T, heston=sc.get("heston_config"), jumps=kw.get("jump_config"), hawkes=sc.get("hawkes_config"),
                   cojump=sc.get("cojump_config"), jump_betas=sc.get("jump_betas"), cojump_mults=sc.get("cojump_mults"),
                   market_vol=sc.get("market_vol"), idio_jump_exclude=sc.get("idio_jump_exclude"),
                   posterior_annual=kw.get("posterior_annual"), rf=kw.get("rf_rate"), source=snap.get("source")))


@app.post("/api/runs/{rid}/cancel")
def run_cancel(rid: str):
    return guard(lambda: ok(runner.cancel(rid)))


@app.delete("/api/runs/{rid}")
def run_delete(rid: str):
    r = guard(lambda: lib.run(rid))
    if r["status"] in ("queued", "running", "waiting"):
        raise HTTPException(409, "cancel the run first")
    return guard(lambda: (lib.delete_run(rid), ok(dict(ok=True)))[1])


@app.get("/api/runs/{rid}/events")
async def run_events(rid: str, request: Request, since: int = 0):
    """Server-Sent Events: the run's events so far, then live ones until it ends."""
    guard(lambda: lib.run(rid))
    q = runner.subscribe(rid)

    async def gen():
        sent = since - 1
        try:
            for ev in lib.events(rid, since):
                sent = max(sent, ev.get("seq", sent))
                yield f"data: {json.dumps(ev)}\n\n"
            if lib.run(rid)["status"] not in ("queued", "running", "waiting"):
                return
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.get_running_loop().run_in_executor(None, q.get, True, 15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                if ev is None:
                    return
                if ev.get("seq", sent + 1) <= sent:          # already sent from the file
                    continue
                sent = ev.get("seq", sent)
                yield f"data: {json.dumps(ev, default=float)}\n\n"
        finally:
            runner.unsubscribe(rid, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/compare")
def compare(ids: str):
    """What changed between runs (inputs) and the change per row (results), against the first id."""
    rid = [i for i in ids.split(",") if i]
    if len(rid) < 2:
        raise HTTPException(400, "compare needs two or more run ids")
    base = guard(lambda: lib.results(rid[0]))
    out = []
    for r in rid[1:]:
        other = guard(lambda r=r: lib.results(r))
        out.append(dict(run=r, changed=what_changed(base, other), rows=row_changes(base, other)))
    return ok(dict(baseline=rid[0], against=out))


def _flat(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k.startswith("_") or k in ("version", "updated", "created", "id"):
                continue
            yield from _flat(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(o, list) and o and isinstance(o[0], dict) and ("name" in o[0] or "ticker" in o[0]):
        for v in o:
            yield from _flat(v, f"{prefix}[{v.get('name') or v.get('ticker')}]")
    else:
        yield prefix, o


def what_changed(a, b):
    out = []
    for label, x, y in (("data day", a["inputs"].get("data_day"), b["inputs"].get("data_day")),
                        ("jump version", a["inputs"].get("jump_version"), b["inputs"].get("jump_version")),
                        ("machine", a.get("machine"), b.get("machine")),
                        ("scenario count", a["config"].get("bank"), b["config"].get("bank"))):
        if x != y:
            out.append(dict(what=label, before=x, after=y))
    fa, fb = dict(_flat(a.get("portfolio", {}))), dict(_flat(b.get("portfolio", {})))
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            out.append(dict(what=k, before=fa.get(k), after=fb.get(k)))
    return out


def row_changes(a, b):
    rb = {tuple(r["path"]): r for r in b["rows"]}
    out = []
    for r in a["rows"]:
        o = rb.get(tuple(r["path"]))
        if o is None:
            continue
        d = dict(path=r["path"], share=[r["share"], o["share"]], effective=[r["effective"], o["effective"]])
        for k in ("er_12w", "cvar", "cdar", "upi", "vol_12w"):
            d[k] = [r["metrics"].get(k), o["metrics"].get(k)]
        out.append(d)
    return out


# ------------------------------------------------------------ exports (#8)
def _export_inputs(rid, budget):
    from . import exports
    rec, res = lib.run(rid), lib.results(rid)
    try:
        model = run_model(rid).body
        model = json.loads(model)
    except HTTPException:
        model = {}
    try:
        cur = lib.get(rec["portfolio_id"])                 # trade-as tickers as the portfolio has them now
        ta = {t: a.get("trade_as") for t, a in cur.get("assets", {}).items() if a.get("trade_as")}
    except NotFound:
        ta = {}
    c, prices = DayCache(), {}
    for t in {r["name"] for r in res["rows"] if r["kind"] == "asset"} | set(ta.values()):
        try:
            prices[t] = c.last_price(t)
        except Exception:
            prices[t] = (None, None)
    return rec, res, model, exports.shares(res, budget, ta, prices)


def _download(body, media, name):
    from fastapi.responses import Response
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/runs/{rid}/export.xlsx")
def export_xlsx(rid: str, budget: float = 100000):
    from . import exports
    rec, res, model, lines = guard(lambda: _export_inputs(rid, budget))
    return _download(exports.xlsx(res, rec, model, lines, budget),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"optimizer-{rid}.xlsx")


@app.get("/api/runs/{rid}/export.pdf")
def export_pdf(rid: str, budget: float = 100000):
    from . import exports
    rec, res, model, lines = guard(lambda: _export_inputs(rid, budget))
    prev = next((r for r in lib.runs(rec["portfolio_id"]) if r.get("status") == "done" and r["id"] < rid), None)
    changed = what_changed(lib.results(prev["id"]), res) if prev else None
    return _download(exports.pdf(res, rec, model, lines, budget, changed), "application/pdf", f"optimizer-{rid}.pdf")


@app.get("/api/runs/{rid}/builder.csv")
def export_csv(rid: str, budget: float = 100000):
    from . import exports
    rec, res, model, lines = guard(lambda: _export_inputs(rid, budget))
    return _download(exports.builder_csv(lines), "text/csv", f"builder-{rid}.csv")


# ------------------------------------------------------------ Colab
@app.get("/api/colab/usage")
def colab_usage():
    try:
        u = colab.usage()
    except colab.SignInNeeded as e:
        raise HTTPException(401, str(e))
    except colab.ColabError as e:
        raise HTTPException(502, str(e))
    return ok(dict(u, rate_cu_per_hour=colab.RATE_CU_PER_HOUR))


# ------------------------------------------------------------ chart modules
CHARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")


@app.get("/api/charts")
def charts():
    """Every chart module: a folder in app/charts with module.json (its name, title and the result fields it
    needs), panel.js (draws it in the room) and, optionally, export.py (renders it for the PDF and the pin)."""
    out = []
    for n in sorted(os.listdir(CHARTS)) if os.path.isdir(CHARTS) else []:
        mj = os.path.join(CHARTS, n, "module.json")
        if os.path.exists(mj) and os.path.exists(os.path.join(CHARTS, n, "panel.js")):
            m = json.load(open(mj))
            m.update(name=n, export=os.path.exists(os.path.join(CHARTS, n, "export.py")))
            out.append(m)
    return ok(out)


if os.path.isdir(CHARTS):
    app.mount("/charts", StaticFiles(directory=CHARTS), name="charts")


app.include_router(setup.router)


# ------------------------------------------------------------ extensions
# Optional add-ons: every module in app/extensions/ with a register(app, ctx) function. Each adds its own routes
# and may list ACTIONS, buttons the results screen shows beside the exports (GET /api/extensions). None ship with
# the tool; they connect it to things outside it.
EXTENSIONS, ACTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extensions"), []
if os.path.isdir(EXTENSIONS):
    import importlib
    for f in sorted(os.listdir(EXTENSIONS)):
        if f.endswith(".py") and not f.startswith("_"):
            mod = importlib.import_module(f".extensions.{f[:-3]}", __package__)
            mod.register(app, dict(lib=lib, ok=ok, guard=guard, port=PORT))
            ACTIONS.extend(getattr(mod, "ACTIONS", []))


@app.get("/api/extensions")
def extensions():
    """The extensions' buttons: {id, label, post (a URL with {run}), done (the note after it worked)}."""
    return ok(ACTIONS)


# ------------------------------------------------------------ the screens
if os.path.isdir(STATIC):
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    srv = uvicorn.Server(config)
    _server["uvicorn"] = srv
    srv.run()


if __name__ == "__main__":
    main()
