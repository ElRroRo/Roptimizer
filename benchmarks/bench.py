"""Benchmark the engine on this machine, and optionally produce the reference answer.

Every number printed here is measured on the machine running it. Stages:
  hardware  GPU name and memory, CuPy/CUDA versions
  bank      build a scenario bank of --bank-paths in chunks of --bank-chunk with the Heston-Bates
            simulator in full-path mode (the per-asset path array the bank keeps is materialised on the
            GPU), and time a device-to-host copy of a block the size of each chunk's asset paths
  eval      time one objective evaluation (the optimizer's unit of work) at --eval-paths
  optimize  the full differential-evolution run at production settings, then re-score the winning
            weights with --score-paths paths to pin the reference objective precisely

Results print as JSON between BENCH-JSON markers after every stage, so a job cut short keeps what it
measured.

Usage: python benchmarks/bench.py --snapshot benchmarks/reference/inputs.json [--bank-paths N ...]
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("MPLBACKEND", "Agg")

import cupy as cp
import numpy as np

from mso import legacy, metrics, sim
from load_snapshot import load

RESULTS = {}


def emit(stage):
    RESULTS["completed_stages"] = RESULTS.get("completed_stages", []) + [stage]
    print("BENCH-JSON-BEGIN\n" + json.dumps(RESULTS, default=float) + "\nBENCH-JSON-END", flush=True)


def gib(n_bytes):
    return round(n_bytes / 2**30, 2)


def hardware():
    props = cp.cuda.runtime.getDeviceProperties(0)
    free, total = cp.cuda.runtime.memGetInfo()
    try:
        smi = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:  # nvidia-smi missing is reported, not fatal
        smi = f"nvidia-smi failed: {e}"
    RESULTS["hardware"] = dict(gpu=props["name"].decode(), gpu_total_gib=gib(total), gpu_free_gib=gib(free),
                               nvidia_smi=smi, cupy=cp.__version__,
                               cuda_runtime=cp.cuda.runtime.runtimeGetVersion(),
                               host_cpus=os.cpu_count())
    print(f"[hardware] {RESULTS['hardware']}", flush=True)


def sim_kwargs(kw):
    return dict(initial_prices=kw["initial_prices"], forecasted_matrices=kw["forecasted_matrices"],
                drift=kw["drift"], jump_config=kw["jump_config"], **kw["sim_config"])


def bank(kw, total, chunk, keep):
    """Build the bank chunk by chunk. With keep=True the real per-asset cumulative-return paths are
    copied to host memory in path-major layout (paths x assets x steps), so a random subset of paths is
    a gather of contiguous rows."""
    n_assets, n_steps = len(kw["tickers"]), len(kw["forecasted_matrices"])
    w = np.ones(n_assets) / n_assets
    pool = cp.get_default_memory_pool()
    sk = sim_kwargs(kw)
    rest = {k: v for k, v in sk.items() if k not in ("initial_prices", "forecasted_matrices", "drift", "jump_config")}
    host_bank = np.empty((total, n_assets, n_steps), dtype=np.float32) if keep else None

    # The full-path engine forms each asset's cumulative return since t=0 (assets x steps x paths) and
    # hands it to cp.tensordot to make the portfolio path. Catch that array: it is exactly what a bank stores.
    caught = {}
    real_tensordot = cp.tensordot

    def spy(a, b, axes=2):
        if getattr(b, "ndim", 0) == 3:
            caught["cum"] = b
        return real_tensordot(a, b, axes)

    sim_s, copy_s, sizes, peak = [], [], [], 0
    done = 0
    t_all = time.perf_counter()
    cp.tensordot = spy
    try:
        while done < total:
            m = min(chunk, total - done)
            pool.free_all_blocks()
            t0 = time.perf_counter()
            out = sim.monte_carlo_simulation(sk["initial_prices"], sk["forecasted_matrices"], m, sk["drift"], w,
                                           sk["jump_config"], return_paths=True, **rest)
            cp.cuda.Device().synchronize()
            sim_s.append(time.perf_counter() - t0)
            sizes.append(m)
            peak = max(peak, pool.total_bytes())
            del out
            cum = caught.pop("cum")
            if cum.shape != (n_assets, n_steps, m):
                raise RuntimeError(f"caught array has shape {cum.shape}, expected {(n_assets, n_steps, m)}")
            t0 = time.perf_counter()
            block = cp.ascontiguousarray(cum.transpose(2, 0, 1))
            if keep:
                block.get(out=host_bank[done:done + m])
            else:
                cp.asnumpy(block)
            cp.cuda.Device().synchronize()
            copy_s.append(time.perf_counter() - t0)
            del cum, block
            done += m
            print(f"[bank] {done:>11,} / {total:,} paths  chunk {sim_s[-1]:.1f} s sim + {copy_s[-1]:.2f} s copy",
                  flush=True)
    finally:
        cp.tensordot = real_tensordot
    wall = time.perf_counter() - t_all
    RESULTS["bank"] = dict(paths=total, chunk=chunk, assets=n_assets, steps=n_steps, kept_on_host=keep,
                           wall_s=round(wall, 1), sim_s=round(sum(sim_s), 1), copy_s=round(sum(copy_s), 2),
                           first_chunk_s=round(sim_s[0], 2),
                           # steady state: the first chunk also compiles kernels, so it is left out when there are others
                           s_per_million_paths=round(sum(sim_s[1:] or sim_s) / (sum(sizes[1:] or sizes) / 1e6), 3),
                           peak_gpu_pool_gib=gib(peak),
                           bank_bytes_gib=gib(n_steps * n_assets * total * 4),
                           note="sim = full-path Heston-Bates simulation per chunk; copy = the chunk's real "
                                "per-asset paths, transposed to path-major and copied to host")
    if keep:
        term = host_bank[:, :, -1].mean(axis=0)
        post = [(1 + d) ** n_steps - 1 for d in kw["drift"]]
        se = host_bank[:, :, -1].std(axis=0) / np.sqrt(total)
        RESULTS["bank"]["check_terminal_mean_vs_posterior_se"] = {
            t: round(float((m - p) / s), 2) for t, m, p, s in zip(kw["tickers"], term, post, se)}
        print(f"[bank] per-asset {n_steps}-week mean vs posterior, in standard errors: "
              f"{RESULTS['bank']['check_terminal_mean_vs_posterior_se']}", flush=True)
    emit("bank")
    return host_bank


def bank_evals(kw, host_bank, paths, reps):
    """Score candidates from the stored bank instead of re-simulating: each evaluation draws a random
    subset of `paths` paths and runs the unchanged objective on it (the simulator call is swapped for a
    lookup). Values are printed beside the simulate-every-time values for the same weights."""
    total, n, s = host_bank.shape
    cp.get_default_memory_pool().free_all_blocks()   # cached blocks from earlier stages count as used
    free, _ = cp.cuda.runtime.memGetInfo()
    # the bank, one gathered subset, the portfolio paths and the drawdown scratch (~3 x paths x steps)
    need = host_bank.nbytes + paths * n * s * 4 + 3 * paths * (s + 1) * 4 + 2**29
    res = dict(bank_paths=total, paths=paths, reps=reps)
    rng = np.random.default_rng(11)

    # Cost if the bank does not fit on the GPU: gather a subset on the host and upload it.
    t0 = time.perf_counter()
    idx = np.sort(rng.integers(0, total, paths))
    sub = cp.asarray(host_bank[idx])
    cp.cuda.Device().synchronize()
    res["host_subset_upload_s"] = round(time.perf_counter() - t0, 3)
    del sub
    cp.get_default_memory_pool().free_all_blocks()

    if need > free:
        res["gpu_resident"] = f"skipped: bank needs ~{gib(need)} GiB, {gib(free)} GiB free"
        RESULTS["bank_eval"] = res
        emit("bank_eval")
        return
    t0 = time.perf_counter()
    g = cp.asarray(host_bank)
    cp.cuda.Device().synchronize()
    res["bank_upload_s"] = round(time.perf_counter() - t0, 2)
    p0 = cp.asarray(np.asarray(kw["initial_prices"], dtype=np.float32))

    def from_bank(initial_prices, forecasted_matrices, num_simulations, drift, weights, jump_config,
                  return_paths=False, **_):
        w = cp.asarray(np.asarray(weights, dtype=np.float32))
        pick = cp.random.randint(0, total, int(num_simulations))
        cum = g[pick]                                             # (paths, assets, steps)
        v0 = cp.dot(p0, w)
        out = cp.empty((int(num_simulations), s + 1), dtype=cp.float32)
        out[:, 0] = v0
        out[:, 1:] = v0 * (1 + cp.tensordot(cum, w, axes=([1], [0])))  # same buy-and-hold formula as the engine
        return out, None, None, None

    real = sim.monte_carlo_simulation
    sim.monte_carlo_simulation = from_bank
    weights = eval_weights(n, reps)
    times, values = [], []
    try:
        for w in weights:
            t0 = time.perf_counter()
            values.append(objective(w, kw, paths))
            times.append(time.perf_counter() - t0)
            print(f"[bank_eval] {paths:,} of {total:,} paths  {times[-1]:.3f} s  f={values[-1]:+.5f}", flush=True)
    finally:
        sim.monte_carlo_simulation = real
    res.update(gpu_resident=True, first_s=round(times[0], 3), mean_s=round(float(np.mean(times[1:] or times)), 4),
               values=values, simulated_values=RESULTS.get("eval", {}).get("values"))
    RESULTS["bank_eval"] = res
    del g
    cp.get_default_memory_pool().free_all_blocks()
    emit("bank_eval")


def eval_weights(n, reps):
    rng = np.random.default_rng(7)
    return [np.ones(n) / n] + [rng.dirichlet(np.ones(n)) for _ in range(reps - 1)]


def evals(kw, paths, reps):
    weights = eval_weights(len(kw["tickers"]), reps)
    times, values = [], []
    for w in weights:
        t0 = time.perf_counter()
        f = objective(w, kw, paths)
        times.append(time.perf_counter() - t0)
        values.append(f)
        print(f"[eval] {paths:,} paths  {times[-1]:.2f} s  f={f:+.5f}", flush=True)
    # The first call compiles kernels and builds the jump-compensator grid: report it apart.
    RESULTS["eval"] = dict(paths=paths, reps=reps, first_s=round(times[0], 2),
                           mean_s=round(float(np.mean(times[1:] or times)), 3),
                           sd_s=round(float(np.std(times[1:] or times)), 3), values=values,
                           peak_gpu_pool_gib=gib(cp.get_default_memory_pool().total_bytes()))
    emit("eval")


def objective(w, kw, paths):
    return metrics.portfolio_cdar_objective(w, kw["forecasted_matrices"], kw["initial_prices"], kw["drift"],
                                      kw["rf_rate"], paths, kw["jump_config"], kw["alpha_cdar"], kw["cvar_floor"],
                                      0.015, 0.005, 0.2, kw["sim_config"])


def optimize(kw, sims, iters, popsize, score_paths, score_reps, seed):
    np.random.seed(seed)       # DE draws its initial population from NumPy's global generator
    cp.random.seed(seed)       # the simulator draws from CuPy's
    real = metrics.portfolio_cdar_objective
    log = dict(n=0, best=np.inf, t0=time.perf_counter())

    def counted(*a, **k):
        f = real(*a, **k)
        log["n"] += 1
        log["best"] = min(log["best"], f)
        if log["n"] % 100 == 0:
            el = time.perf_counter() - log["t0"]
            print(f"[optimize] {log['n']:>6} evaluations  {el / 60:6.1f} min  best f={log['best']:+.5f}", flush=True)
        return f

    metrics.portfolio_cdar_objective = counted
    try:
        t0 = time.perf_counter()
        w, ret, sd, cvar, starr, paths, raw, cdar = legacy.run_optimization(
            num_simulations_for_cvar=sims, n_iterations=iters, popsize=popsize, **legacy.legacy_kwargs(kw))
        wall = time.perf_counter() - t0
    finally:
        metrics.portfolio_cdar_objective = real
    del paths, raw
    RESULTS["optimize"] = dict(sims=sims, iters=iters, popsize=popsize, seed=seed, evaluations=log["n"],
                               wall_s=round(wall, 1), s_per_eval=round(wall / max(log["n"], 1), 3),
                               weights={t: round(float(x), 6) for t, x in zip(kw["tickers"], w)},
                               expected_return_12w=float(ret), volatility_12w=float(sd), cvar_12w=float(cvar),
                               cdar_12w=float(cdar), starr_12w=float(starr))
    emit("optimize")

    scores = []
    for i in range(score_reps):
        cp.get_default_memory_pool().free_all_blocks()
        scores.append(objective(w, kw, score_paths))
        print(f"[score] reference weights at {score_paths:,} paths: f={scores[-1]:+.6f}", flush=True)
    RESULTS["optimize"]["score"] = dict(paths=score_paths, reps=score_reps, values=scores,
                                        mean=float(np.mean(scores)), sd=float(np.std(scores, ddof=1)) if score_reps > 1 else None)
    emit("score")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--bank-paths", type=int, default=0)
    ap.add_argument("--bank-chunk", type=int, default=1_000_000)
    ap.add_argument("--eval-paths", type=int, default=0)
    ap.add_argument("--eval-reps", type=int, default=5)
    ap.add_argument("--bank-eval-paths", type=int, default=0, help="score from the stored bank (needs --bank-paths)")
    ap.add_argument("--optimize", action="store_true")
    ap.add_argument("--sims", type=int, default=3_000_000)
    ap.add_argument("--iters", type=int, default=15)
    ap.add_argument("--popsize", type=int, default=30)
    ap.add_argument("--score-paths", type=int, default=10_000_000)
    ap.add_argument("--score-reps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261027)
    a = ap.parse_args()

    snap, kw = load(a.snapshot)
    RESULTS["snapshot"] = dict(created=snap["created"], last_return_week=snap.get("last_return_week"),
                               assets=len(kw["tickers"]))
    hardware()
    emit("hardware")
    host_bank = bank(kw, a.bank_paths, a.bank_chunk, keep=bool(a.bank_eval_paths)) if a.bank_paths else None
    if a.eval_paths:
        evals(kw, a.eval_paths, a.eval_reps)
    if a.bank_eval_paths:
        bank_evals(kw, host_bank, a.bank_eval_paths, a.eval_reps)
        del host_bank
    if a.optimize:
        optimize(kw, a.sims, a.iters, a.popsize, a.score_paths, a.score_reps, a.seed)


if __name__ == "__main__":
    main()
