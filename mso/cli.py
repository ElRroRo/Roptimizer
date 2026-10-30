"""`python -m mso run`: one optimizer run from the command line, the twin of the Run button on the screens.

inputs (a frozen snapshot, a portfolio JSON or a v4.1 CSV, built live) -> scenario bank -> the tree,
searched in post-order on 90% of the bank -> metrics per row on the held-out 10% -> optionally an
independent re-score of the Portfolio by fresh simulation (the regression check against
benchmarks/reference/answer.json).
--machine laptop runs here; --machine a100 freezes the inputs here, packs the run (mso/job.py) and runs it
with `colab run` (mso/colab.py); --machine local is what the packed job runs on the VM.
Progress is printed twice: a human line, and an `@@MSO {json}` event (mso/events.py).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

REFERENCE_OBJECTIVE = -0.08833      # benchmarks/reference/answer.json, re-scored at 10M paths (SD 0.00004)
REGRESSION_TOLERANCE = 0.0003       # a flat run worse than the reference by more than this fails (spec section 6)


PROFILES = {   # bank and draw sizes per machine (#5): the laptop holds about 2M paths at 16 assets
    "laptop": dict(cap=2_000_000, draw=1_000_000, chunk=500_000),
    "a100": dict(cap=30_000_000, draw=3_000_000, chunk=4_000_000),
    "cpu": dict(cap=400_000, draw=200_000, chunk=100_000),     # no NVIDIA GPU (mso/xp.py): NumPy on the CPU
}


def _parser():
    ap = argparse.ArgumentParser(prog="python -m mso")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="optimize a portfolio")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot", help="frozen inputs (benchmarks/snapshot.py or a run's inputs.json)")
    src.add_argument("--portfolio", help="a portfolio JSON, built live (downloads and fits)")
    src.add_argument("--csv", help="a v4.1 portfolio CSV, imported flat and built live")
    r.add_argument("--tree", help="with --snapshot: a portfolio JSON whose tree to run (default: flat)")
    r.add_argument("--machine", choices=["laptop", "a100", "local"], default="laptop")
    r.add_argument("--profile", choices=list(PROFILES), default=None, help="bank sizing (default: the machine's)")
    r.add_argument("--out", required=True, help="results JSON")
    r.add_argument("--bank", type=int, default=0, help="scenario paths (default: as many as fit, up to the profile's cap)")
    r.add_argument("--chunk", type=int, default=0, help="paths simulated per bank chunk")
    r.add_argument("--validation", type=float, default=0.10, help="share of the bank held out for metrics")
    r.add_argument("--draw", type=int, default=0, help="paths per generation's draw")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="set a search setting on every subportfolio (e.g. tol=0, maxgen=80); for tests")
    r.add_argument("--hhi", type=float, default=None, help="concentration penalty at the Portfolio")
    r.add_argument("--bands", type=int, default=0, help="sensitivity band: K repeats per search (0 = off)")
    r.add_argument("--trace", action="store_true", help="score every generation's incumbent on the held-out paths")
    r.add_argument("--noise", type=int, default=0, help="score each answer on K fresh draws (draw-to-draw noise)")
    r.add_argument("--seed", type=int, default=20261029)
    r.add_argument("--rescore-paths", type=int, default=0, help="paths per fresh-simulation re-score of the Portfolio")
    r.add_argument("--rescore-reps", type=int, default=5)
    r.add_argument("--quick", action="store_true", help="with --csv/--portfolio: lightweight jump configs")
    r.add_argument("--jump-version", default="latest", help="with --csv/--portfolio: the jump database version")
    r.add_argument("--rf", type=float, default=None, help="with --csv/--portfolio: risk-free rate by hand")
    r.add_argument("--colab-gpu", default="A100", choices=["T4", "L4", "A100", "H100"],
                   help="with --machine a100: the Colab GPU to rent (T4 is in Colab's free tier)")
    r.add_argument("--run-id", default=None, help="names the Colab session mso-<run id>")
    r.add_argument("--save-inputs", default=None, help="write the frozen inputs here (the run folder's inputs.json)")

    j = sub.add_parser("jumpdb", help="the jump database")
    j.add_argument("action", choices=["list", "recalibrate", "pool-reset", "show"])
    j.add_argument("version", nargs="?", default="latest")

    d = sub.add_parser("data", help="the day-keyed market-data cache")
    d.add_argument("action", choices=["status", "refresh"])

    b = sub.add_parser("betas", help="per-asset crash/rally betas and co-jumps under a jump version")
    b.add_argument("tickers", nargs="+")
    b.add_argument("--version", default="latest")
    b.add_argument("--set-crash", type=float, default=None, help="manual crash beta for a single ticker")
    b.add_argument("--set-rally", type=float, default=None, help="manual rally beta for a single ticker")
    b.add_argument("--clear", action="store_true", help="remove the ticker's manual betas")
    return ap


def _say(msg):
    print(f"[mso] {msg}", flush=True)


def _inputs(a):
    """(inputs, source record, portfolio) from --snapshot [--tree] / --portfolio / --csv."""
    from mso import frozen
    from mso import portfolio as pf
    if a.snapshot:
        snap, inputs = frozen.load(a.snapshot)
        source = {k: v for k, v in snap.items() if k != "run_optimization_kwargs"}
        source["snapshot"] = a.snapshot
        if a.tree:
            with open(a.tree) as f:
                port = json.load(f)
        else:
            T = list(inputs["tickers"])
            port = pf.new("Portfolio (flat, frozen inputs)", {t: {"equilibrium": 0.0, "view": None} for t in T})
        return inputs, source, port
    from mso.pipeline import build_inputs, load_portfolio
    port = load_portfolio(a.portfolio or a.csv)
    inputs, record = build_inputs(port, quick=a.quick, jump_version=a.jump_version, rf_rate=a.rf)
    inputs["drift"] = np.asarray(inputs["drift"], dtype=float)
    return inputs, dict(source=a.portfolio or a.csv, quick=a.quick, **record), port


def _apply_sets(port, sets, hhi):
    from mso import portfolio as pf
    vals = {}
    for kv in sets:
        k, v = kv.split("=", 1)
        if k not in pf.DEFAULTS:
            sys.exit(f"--set {k}: not a setting ({', '.join(pf.DEFAULTS)})")
        vals[k] = v if k == "floor_strictness" else float(v)
    for node, _, _ in pf.walk(port["tree"]):
        if node["kind"] == "group":
            node.setdefault("settings", {}).update(vals)
    if hhi is not None:
        port["tree"].setdefault("settings", {})["concentration"] = hhi
    return vals


def run(a):
    if a.machine == "a100":
        return run_a100(a)
    os.environ.setdefault("MPLBACKEND", "Agg")
    from mso.xp import cp
    from mso import bank, events, metrics, search, tree

    t_run = time.perf_counter()
    from mso.xp import GPU
    prof_name = a.profile or ("a100" if a.machine == "a100" else "laptop" if GPU else "cpu")
    prof = PROFILES[prof_name]
    gpu = cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
    events.emit("start", machine=a.machine, gpu=gpu, seed=a.seed)
    _say(f"{a.machine} run on {gpu}, seed {a.seed}")

    events.emit("stage", stage="inputs")
    inputs, source, port = _inputs(a)
    if a.save_inputs:
        from mso import frozen
        frozen.save(a.save_inputs, inputs, source=source)
    sets = _apply_sets(port, a.set, a.hhi)
    T = list(inputs["tickers"])
    N, S = len(T), len(inputs["forecasted_matrices"])
    er = search.horizon_returns(inputs["drift"], S)
    rf_h = (1 + inputs["rf_rate"]) ** (S / 52) - 1

    draw, chunk = a.draw or prof["draw"], a.chunk or prof["chunk"]
    if a.bank:
        paths = a.bank
    else:
        paths, chunk, d = bank.plan(N, S, prof["cap"], draw, chunk)
        if paths < prof["cap"] or d < draw:
            _say(f"sized to the GPU for {N} assets: a {paths:,}-path bank, {d:,}-path draws, chunks of {chunk:,}")
        if not a.draw:
            draw = d
    train = int(paths * (1 - a.validation))
    events.emit("stage", stage="bank", paths=paths)
    t0 = time.perf_counter()
    G = bank.build(inputs, paths, min(chunk, paths), a.seed,
                   progress=lambda d, n, s: events.emit("bank", done=d, total=n, s=round(s, 1)))
    bank_s = time.perf_counter() - t0
    _say(f"bank: {paths:,} paths x {N} assets x {S} weeks in {bank_s:.1f} s "
         f"({train:,} searched, {paths - train:,} held out)")

    def on_event(kind, **kw):
        events.emit(kind, **kw)
        if kind == "generation" and (kw["gen"] % 5 == 0 or kw["stop"]):
            _say(f"[{kw['search']}] gen {kw['gen']:>2}  incumbent {kw['incumbent']:+.5f} (scored {kw['scored']}x)  "
                 f"{kw['s']:.1f} s/gen  replaced {kw['replaced']}")
        elif kind == "search_done":
            _say(f"[{kw['search']}] stopped ({kw['stopped']}) at generation {kw['generations']}")

    events.emit("stage", stage="search")
    res = tree.run(G, inputs, port, train, S, a.seed, draw=draw, bands=a.bands, on_event=on_event, rf_h=rf_h,
                   trace=a.trace, noise=a.noise)
    root = res["rows"][0]
    _say(f"tree searched: {res['searches']} searches in {res['wall_s']:.0f} s; Portfolio incumbent "
         f"{root['search'].get('incumbent', float('nan')):+.5f}")

    events.emit("stage", stage="metrics")
    VAL = cp.ascontiguousarray(G[train:].transpose(2, 0, 1))
    del G                                             # the figures need only the held-out tenth: free the bank first
    import gc
    gc.collect()                                      # the tree's recursive closures hold the bank in a cycle
    cp.get_default_memory_pool().free_all_blocks()
    tree.metrics(VAL, res, er, float(root["search"]["settings"]["tail"]["value"]), rf_h)
    del VAL
    cp.get_default_memory_pool().free_all_blocks()

    w = np.array([res["effective"][t] for t in T])
    result = dict(created=datetime.now().isoformat(timespec="seconds"), machine=a.machine, gpu=gpu, seed=a.seed,
                  inputs=source, tickers=T, er_12w=dict(zip(T, er.tolist())), rf_12w=rf_h, portfolio=port,
                  config=dict(bank=paths, chunk=chunk, train=train, draw=draw, validation=a.validation,
                              bands=a.bands, set=sets, profile=prof_name),
                  bank_s=round(bank_s, 1), weights=res["effective"], rows=res["rows"],
                  searches=res["searches"], search_s=res["wall_s"])

    if a.rescore_paths:
        events.emit("stage", stage="rescore", paths=a.rescore_paths, reps=a.rescore_reps)
        hhi = float(root["search"]["settings"]["concentration"]["value"])
        vals = []
        for i in range(a.rescore_reps):
            cp.get_default_memory_pool().free_all_blocks()
            vals.append(float(metrics.portfolio_cdar_objective(
                w, inputs["forecasted_matrices"], inputs["initial_prices"], inputs["drift"], inputs["rf_rate"],
                a.rescore_paths, inputs["jump_config"], inputs["alpha_cdar"], inputs["cvar_floor"],
                0.015, 0.005, hhi, inputs["sim_config"])))
            _say(f"re-score {i + 1}/{a.rescore_reps}: fresh simulation of {a.rescore_paths:,} paths, f={vals[-1]:+.5f}")
        m = float(np.mean(vals))
        se = float(np.std(vals, ddof=1) / np.sqrt(len(vals))) if len(vals) > 1 else None
        result["rescore"] = dict(paths_each=a.rescore_paths, reps=a.rescore_reps, values=vals, mean=m, se=se,
                                 reference=REFERENCE_OBJECTIVE, tolerance=REGRESSION_TOLERANCE,
                                 passes=bool(m <= REFERENCE_OBJECTIVE + REGRESSION_TOLERANCE))
        _say(f"re-scored objective {m:+.5f}" + (f" (SE {se:.5f})" if se is not None else "") +
             f" vs reference {REFERENCE_OBJECTIVE:+.5f}: {'PASS' if result['rescore']['passes'] else 'FAIL'}")

    result["wall_s"] = round(time.perf_counter() - t_run, 1)
    with open(a.out, "w") as f:
        json.dump(result, f, indent=1, default=float)
    events.emit("done", out=a.out, wall_s=result["wall_s"], objective=root["search"].get("incumbent"))
    _say(f"done in {result['wall_s']:.0f} s; results in {a.out}")
    _say("weights: " + ", ".join(f"{t} {x:.1%}" for t, x in sorted(res["effective"].items(), key=lambda x: -x[1])
                                if x >= 0.0005))
    return result


def run_a100(a):
    """Freeze the inputs here, pack the run, run it on a Colab GPU (--colab-gpu, A100 by default) and keep its
    result and stdout. The bank is sized to the rented GPU's memory (bank.plan), up to the a100 profile's cap."""
    import tempfile
    import uuid
    from mso import colab, frozen, job
    run_id = a.run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    session = colab.SESSION_PREFIX + run_id
    from mso import events
    events.emit("stage", stage="inputs")
    inputs, source, port = _inputs(a)
    work = tempfile.mkdtemp(prefix=f"mso-{run_id}-")
    inp, tre, script = (os.path.join(work, n) for n in ("inputs.json", "portfolio.json", "job.py"))
    frozen.save(inp, inputs, source=source)
    if a.save_inputs:
        frozen.save(a.save_inputs, inputs, source=source)
    with open(tre, "w") as f:
        json.dump(port, f)
    args = ["run", "--snapshot", "inputs.json", "--tree", "portfolio.json", "--machine", "local", "--profile", "a100",
            "--out", "result.json", "--seed", str(a.seed), "--validation", str(a.validation)]
    for flag in ("bank", "chunk", "draw", "bands", "noise", "rescore_paths", "rescore_reps"):
        v = getattr(a, flag)
        if v:
            args += ["--" + flag.replace("_", "-"), str(v)]
    if a.trace:
        args.append("--trace")
    for kv in a.set:
        args += ["--set", kv]
    if a.hhi is not None:
        args += ["--hhi", str(a.hhi)]
    size = job.build(script, {"inputs.json": inp, "portfolio.json": tre}, args)
    events.emit("stage", stage="packed", session=session, payload_kib=round(size / 1024))
    before = colab.usage()
    gpu = a.colab_gpu
    rate = colab.RATE_CU_PER_HOUR if gpu == "A100" else None      # only the A100's rate has been measured
    events.emit("colab", balance_before=before["balance"], rate=rate, gpu=gpu)
    _say(f"Colab {gpu} job {session}: payload {size / 1024:.0f} KiB; balance {before['balance']:.2f} CU"
         + (f" (plain A100 bills {rate} CU/h)" if rate else ""))
    t0 = time.time()
    try:
        code, out = colab.run(script, session, on_line=lambda l: print(l, flush=True), gpu=gpu,
                              on_wait=lambda n, d: _say(f"waiting for a Colab {gpu} (attempt {n}, retrying in {d} s)"))
    finally:
        stopped, others = colab.sweep([session])          # its own session only, if still running
        if stopped:
            _say(f"stopped its session {session}, still running after the job")
        if others:
            _say(f"other mso sessions are running (not this run's, left alone): {', '.join(others)}")
    wall = time.time() - t0
    after = colab.usage()
    for _ in range(2):                    # Colab updates the balance late: give it a little time
        if after["balance"] != before["balance"]:
            break
        time.sleep(20)
        after = colab.usage()
    with open(os.path.splitext(a.out)[0] + ".colab.log", "w") as f:
        f.write(out)
    result = job.extract(out)
    if result is None:
        sys.exit(f"the Colab {gpu} job ended without a result (exit {code}): see {os.path.splitext(a.out)[0]}.colab.log")
    result["colab"] = dict(session=session, gpu=gpu, exit=code, wall_s=round(wall, 1), balance_before=before["balance"],
                           balance_after=after["balance"],
                           # An unchanged balance means Colab has not booked the job yet, never "0 CU used".
                           cu_measured=(round(before["balance"] - after["balance"], 2)
                                        if after["balance"] != before["balance"] else None),
                           cu_note=(None if after["balance"] != before["balance"] else
                                    "Colab had not updated the balance yet; see cu_at_rate"),
                           cu_at_rate=round(wall / 3600 * rate, 2) if rate else None)
    result["inputs"] = source
    with open(a.out, "w") as f:
        json.dump(result, f, indent=1, default=float)
    cu = result["colab"]
    _say(f"Colab {gpu} job done in {wall:.0f} s: " + (f"{cu['cu_measured']} CU measured ({before['balance']:.2f} -> "
         f"{after['balance']:.2f})" if cu["cu_measured"] is not None else "balance not updated by Colab yet"
         + (f"; {cu['cu_at_rate']} CU at {rate} CU/h" if rate else "")) + f"; results in {a.out}")
    return result


def jumpdb_cmd(a):
    from mso import jumpdb
    if a.action == "list":
        names = jumpdb.versions()
        if not names:
            _say("no versions stored; run: python -m mso jumpdb recalibrate")
        for n in names:
            v = jumpdb.load(n)
            d = json.load(open(os.path.join(v["path"], "diagnostics.json")))
            _say(f"{n}  {v['age_days']:>4} days{'  STALE' if v['stale'] else ''}  pool {d['pool_counts']}  "
                 f"systematic lambda {v['jump_config']['systematic']['lambda']:.4f}  co-jump {v['cojump_config']['var_jump_mult']:.2f}")
    elif a.action == "show":
        print(json.dumps({k: v for k, v in jumpdb.load(a.version).items() if k != "path"}, indent=1))
    elif a.action == "pool-reset":
        p = jumpdb.reset_pool()
        _say(f"pool reset to the default {len(p['tickers'])} tickers")
    elif a.action == "recalibrate":
        os.environ.setdefault("MPLBACKEND", "Agg")
        t0 = time.perf_counter()
        name = jumpdb.recalibrate()
        _say(f"stored jump database version {name} in {time.perf_counter() - t0:.0f} s")


def data_cmd(a):
    from mso.cache import DayCache
    c = DayCache()
    if a.action == "refresh":
        c.refresh()
        _say(f"day cache {c.day} cleared: every series downloads again on next use")
    else:
        _say(f"day cache {c.day}: {len(c.index)} series, first downloaded {c.downloaded_at()}")


def betas_cmd(a):
    from mso import betas, jumpdb
    from mso.cache import DayCache
    if a.clear or a.set_crash is not None or a.set_rally is not None:
        if len(a.tickers) != 1:
            sys.exit("manual betas are set one ticker at a time")
        o = betas.load_overrides().get(a.tickers[0], {})
        crash = None if a.clear else (a.set_crash if a.set_crash is not None else o.get("crash"))
        rally = None if a.clear else (a.set_rally if a.set_rally is not None else o.get("rally"))
        betas.set_override(a.tickers[0], crash, rally)
    betas.print_table(betas.ticker_table(a.tickers, jumpdb.load(a.version), DayCache()))


def main(argv=None):
    a = _parser().parse_args(argv)
    {"run": run, "jumpdb": jumpdb_cmd, "data": data_cmd, "betas": betas_cmd}[a.cmd](a)


if __name__ == "__main__":
    main()
