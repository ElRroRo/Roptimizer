"""Prototype of the v5.0 search loop (ticket #10), on the frozen reference inputs, laptop GPU.

- own DE loop (best1bin, popsize 30, dithered F in [0.5, 1), CR 0.7, Latin-hypercube start)
- limits enforced by repairing every vector onto {lo <= w <= hi, sum w = 1} (Euclidean projection)
- each generation: one fresh subset of the bank; trials AND survivors scored on it in one batched pass;
  a trial replaces its parent if better on that same draw; survivors keep a running mean of their scores
- stop: incumbent running mean improves < TOL over the last WINDOW generations; cap MAXGEN
- a tree level is scored on the asset bank through effective weights (buy-and-hold is linear)

Usage: python de_proto.py <out.json> <tests...>   tests: check flat limits tree
"""
import json
import sys
import time

sys.path.insert(0, "benchmarks")
sys.path.insert(0, ".")
import cupy as cp
import numpy as np

import bench
from mso import sim as E  # the simulator is patched where metrics calls it
from load_snapshot import load

OUT = sys.argv[1]
TESTS = sys.argv[2:]
BANK, SUB, SCORE_PATHS, SCORE_REPS = 2_000_000, 1_000_000, 1_000_000, 6
import os
POP_PER_DIM, CR, TOL = 30, 0.7, 0.0002
WINDOW = int(os.environ.get('DE_WINDOW', 5))
MAXGEN = int(os.environ.get('DE_MAXGEN', 80))
HHI = float(os.environ.get('DE_HHI', 0.20))
FLOOR_W = 5.0

snap, kw = load("benchmarks/reference/inputs.json")
T = list(kw["tickers"])
N, S = len(T), len(kw["forecasted_matrices"])
ALPHA, FLOOR = kw["alpha_cdar"], kw["cvar_floor"]
ER = (1 + np.asarray(kw["drift"], dtype=float)) ** S - 1          # posterior 12-week return per asset
RF = (1 + kw["rf_rate"]) ** (S / 52) - 1
RESULTS = dict(config=dict(hhi=HHI, bank=BANK, subset=SUB, pop_per_dim=POP_PER_DIM, cr=CR, window=WINDOW, tol=TOL,
                           maxgen=MAXGEN, score_paths=SCORE_PATHS, score_reps=SCORE_REPS,
                           gpu=cp.cuda.runtime.getDeviceProperties(0)["name"].decode()))


def save():
    json.dump(RESULTS, open(OUT, "w"), indent=1)


# ---------- bank ----------
cp.random.seed(4242)
t0 = time.perf_counter()
host = bench.bank(kw, BANK, 500_000, keep=True)
G = cp.asarray(host)                                              # (paths, assets, steps) on the GPU
del host
RESULTS["bank_build_s"] = round(time.perf_counter() - t0, 1)
cp.get_default_memory_pool().free_all_blocks()


def draw(rng, m=SUB):
    idx = cp.asarray(rng.integers(0, BANK, m))
    return cp.ascontiguousarray(G[idx].transpose(2, 0, 1))         # (steps, paths, assets)


def score(Rt, W, er, cand_chunk=64):
    """Objective for every column of W (assets x candidates) on the drawn paths Rt (steps x paths x assets).
    er: 12-week expected return per candidate (computed outside, so tree levels can pass their own)."""
    m = Rt.shape[1]
    k = int(np.floor(ALPHA * (m - 1))) + 1                         # count of paths at or below the percentile
    out = []
    Wg = cp.asarray(W, dtype=cp.float32)
    for c0 in range(0, W.shape[1], cand_chunk):
        w = Wg[:, c0:c0 + cand_chunk]
        runmax = cp.ones((m, w.shape[1]), dtype=cp.float32)
        dd = cp.zeros_like(runmax)
        for t in range(S):
            x = 1 + Rt[t] @ w
            cp.maximum(runmax, x, out=runmax)
            cp.minimum(dd, x / runmax - 1, out=dd)
        term = x - 1
        cdar = cp.partition(dd, k - 1, axis=0)[:k].mean(axis=0)
        cvar = cp.partition(term, k - 1, axis=0)[:k].mean(axis=0)
        out.append(cp.stack([cdar, cvar]).get())
    cdar, cvar = np.concatenate(out, axis=1)
    hhi = (W ** 2).sum(axis=0)
    upi = (er - RF) / np.maximum(np.abs(cdar), 1e-10)
    f = -(upi - HHI * hhi) + FLOOR_W * np.maximum(0.0, FLOOR - cvar)
    return np.where(cdar < 0, f, 1e6)


def project(v, lo, hi, iters=60):
    """Euclidean projection of each column of v onto {lo <= w <= hi, sum w = 1} (bisection on the shift)."""
    a = (v - hi[:, None]).min(axis=0) - 1.0
    b = (v - lo[:, None]).max(axis=0) + 1.0
    for _ in range(iters):
        mid = (a + b) / 2
        s = np.clip(v - mid, lo[:, None], hi[:, None]).sum(axis=0)
        a = np.where(s > 1, mid, a)
        b = np.where(s > 1, b, mid)
    return np.clip(v - (a + b) / 2, lo[:, None], hi[:, None])


def search(name, n, er_fn, to_assets, lo=None, hi=None, seed=0):
    """DE over n children. er_fn(W_children) -> expected return per candidate; to_assets maps child weights
    (n x c) to effective asset weights (N x c) for scoring on the bank."""
    lo = np.zeros(n) if lo is None else np.asarray(lo, float)
    hi = np.ones(n) if hi is None else np.asarray(hi, float)
    if lo.sum() > 1 + 1e-12 or hi.sum() < 1 - 1e-12:
        raise ValueError(f"{name}: limits infeasible (mins {lo.sum():.0%}, maxes {hi.sum():.0%})")
    rng = np.random.default_rng(seed)
    P = POP_PER_DIM * n
    # Latin hypercube in [0,1]^n, then repaired onto the feasible set
    lhs = (rng.permuted(np.tile(np.arange(P), (n, 1)), axis=1) + rng.random((n, P))) / P
    pop = project(lhs / lhs.sum(axis=0), lo, hi)
    f = lambda W, R: score(R, to_assets(W), er_fn(W))
    R = draw(rng)
    mean = f(pop, R)
    cnt = np.ones(P)
    hist, t_gen = [], []
    for g in range(1, MAXGEN + 1):
        t0 = time.perf_counter()
        best = pop[:, np.argmin(mean)]
        F = rng.uniform(0.5, 1.0)
        r = np.array([rng.choice(np.delete(np.arange(P), i), 2, replace=False) for i in range(P)])
        mutant = best[:, None] + F * (pop[:, r[:, 0]] - pop[:, r[:, 1]])
        cross = rng.random((n, P)) < CR
        cross[rng.integers(0, n, P), np.arange(P)] = True
        trial = project(np.clip(np.where(cross, mutant, pop), 0, None), lo, hi)
        R = draw(rng)
        both = f(np.concatenate([pop, trial], axis=1), R)
        old, new = both[:P], both[P:]
        mean = (mean * cnt + old) / (cnt + 1)
        cnt += 1
        win = new < old                                            # paired on the same draw
        pop[:, win] = trial[:, win]
        mean[win], cnt[win] = new[win], 1
        # incumbent: best running mean among members scored at least twice (a one-draw score is not trusted)
        seasoned = np.where(cnt >= 2, mean, np.inf)
        inc = int(np.argmin(seasoned)) if np.isfinite(seasoned).any() else int(np.argmin(mean))
        hist.append(float(mean[inc]))
        t_gen.append(time.perf_counter() - t0)
        stop = g > WINDOW and hist[-1 - WINDOW] - hist[-1] < TOL
        if g % 5 == 0 or stop:
            print(f"[{name}] gen {g:>2}  incumbent {hist[-1]:+.5f} (scored {int(cnt[inc])}x)  "
                  f"{t_gen[-1]:.1f} s/gen  replaced {int(win.sum())}/{P}", flush=True)
        if stop:
            break
    w = pop[:, inc]
    return dict(weights=w.tolist(), generations=g, stopped="window" if g < MAXGEN else "cap",
                incumbent=hist[-1], incumbent_scored=int(cnt[inc]), history=hist,
                s_per_gen=round(float(np.mean(t_gen[1:])), 2), wall_s=round(float(np.sum(t_gen)), 1),
                min_w=float(w.min()), max_w=float(w.max()), sum_w=float(w.sum()),
                within_limits=bool(np.all(w >= lo - 1e-9) and np.all(w <= hi + 1e-9)))


def fresh(w_assets):
    """Honest score: fresh simulation with the real engine, independent of the bank."""
    cp.get_default_memory_pool().free_all_blocks()
    vals = [bench.objective(np.asarray(w_assets), kw, SCORE_PATHS) for _ in range(SCORE_REPS)]
    return dict(mean=float(np.mean(vals)), sd=float(np.std(vals, ddof=1)))


flat_er = lambda W: ER @ W
ident = lambda W: W

if "check" in TESTS:
    # batched scorer vs the engine's own objective on the very same paths
    rng = np.random.default_rng(5)
    idx = cp.asarray(rng.integers(0, BANK, SUB))
    sub = G[idx]
    Rt = cp.ascontiguousarray(sub.transpose(2, 0, 1))
    W = np.column_stack([np.ones(N) / N] + [rng.dirichlet(np.ones(N)) for _ in range(5)])
    mine = score(Rt, W, flat_er(W))

    def fixed(initial_prices, forecasted_matrices, num_simulations, drift, weights, jump_config, return_paths=False, **_):
        w = cp.asarray(np.asarray(weights, dtype=np.float32))
        out = cp.empty((SUB, S + 1), dtype=cp.float32)
        out[:, 0] = 1
        out[:, 1:] = 1 + cp.tensordot(sub, w, axes=([1], [0]))
        return out, None, None, None

    real = E.monte_carlo_simulation
    E.monte_carlo_simulation = fixed
    try:
        theirs = [bench.objective(W[:, j], kw, SUB) for j in range(W.shape[1])]
    finally:
        E.monte_carlo_simulation = real
    RESULTS["check"] = dict(batched=mine.tolist(), engine=theirs, max_abs_diff=float(np.max(np.abs(mine - theirs))))
    print("[check] max |batched - engine| =", RESULTS["check"]["max_abs_diff"], flush=True)
    del sub, Rt
    save()

if "flat" in TESTS:
    RESULTS["flat"] = {}
    ref = json.load(open("benchmarks/reference/answer.json"))
    rw = ref.get("weights")
    rw = np.array([rw[t] for t in T]) if isinstance(rw, dict) else np.asarray(rw)
    RESULTS["reference_fresh"] = fresh(rw / rw.sum())
    print("[reference] fresh", RESULTS["reference_fresh"], flush=True)
    save()
    for seed in (301, 302):
        r = search(f"flat-{seed}", N, flat_er, ident, seed=seed)
        RESULTS["flat"][seed] = r
        save()
        r["fresh"] = fresh(r["weights"])
        RESULTS["flat"][seed] = r
        print(f"[flat-{seed}] fresh {r['fresh']}  gens {r['generations']}", flush=True)
        save()

if "limits" in TESTS:
    lo, hi = np.zeros(N), np.ones(N)
    hi[T.index("BTC=F")] = 0.15
    lo[T.index("CTA")] = 0.15
    r = search("limits", N, flat_er, ident, lo, hi, seed=303)
    r["fresh"] = fresh(r["weights"])
    r["limits"] = {"BTC=F max": 0.15, "CTA min": 0.15}
    RESULTS["limits"] = r
    print(f"[limits] BTC {r['weights'][T.index('BTC=F')]:.4f} CTA {r['weights'][T.index('CTA')]:.4f} fresh {r['fresh']}", flush=True)
    save()

if "tree" in TESTS:
    groups = {"Stocks": "NVDA MNTS META JPM GOOGL FERG ADBE NRIM SPGI".split(),
              "Managed futures": "DBMF CTA WTMF".split()}
    frozen, tree = {}, {}
    HHI_TOP = HHI
    HHI = float(os.environ.get('DE_HHI_INNER', HHI_TOP))
    RESULTS["config"]["hhi_inner"] = HHI
    for gname, members in groups.items():
        ix = [T.index(x) for x in members]

        def to_assets(W, ix=ix):
            A = np.zeros((N, W.shape[1]))
            A[ix] = W
            return A
        r = search(gname, len(ix), lambda W, ix=ix: ER[ix] @ W, to_assets, seed=310 + len(ix))
        frozen[gname] = (ix, np.asarray(r["weights"]))
        tree[gname] = r
        save()
    HHI = HHI_TOP
    # top level: the two frozen subportfolios plus the remaining assets as children
    rest = [i for i in range(N) if not any(i in ix for ix, _ in frozen.values())]
    M = np.zeros((N, len(frozen) + len(rest)))                      # child -> asset mixing matrix
    for j, (ix, w) in enumerate(frozen.values()):
        M[ix, j] = w
    for j, i in enumerate(rest):
        M[i, len(frozen) + j] = 1
    names = list(frozen) + [T[i] for i in rest]
    r = search("Portfolio", M.shape[1], lambda W: ER @ (M @ W), lambda W: M @ W, seed=320)
    eff = M @ np.asarray(r["weights"])
    r["children"] = names
    r["effective"] = dict(zip(T, eff.tolist()))
    r["fresh"] = fresh(eff)
    tree["Portfolio"] = r
    RESULTS["tree"] = tree
    print(f"[tree] fresh {r['fresh']}", flush=True)
    save()

print("done", flush=True)
