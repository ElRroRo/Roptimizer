"""A real tree run for the results-screen prototypes (ticket #12), with the #10 search loop on the laptop GPU.

Two runs of the same tree on one bank, differing in one limit (Alternatives at most 15% of the Portfolio,
then 25%; it binds in the first run), so the compare view has a genuine "what changed". Everything the results screens draw comes from
here: weights, per-row metrics, search histories, binding limits, outcome fans and distributions.

- bank: 2M paths of the frozen reference inputs; searches draw from the first 90%, metrics use the last 10%
  (the validation slice of #10), so no row is scored on the paths it was chosen on
- post-order: each subportfolio is searched over its children's frozen mixes; one member = 100%, no search
- concentration penalty 0.20 at the Portfolio on effective weights, off inside (#10); CVaR floor soft, 5 × breach

Usage: python benchmarks/prototypes/tree_run.py <out.json>
"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, "benchmarks")
sys.path.insert(0, ".")
import cupy as cp
import numpy as np

import bench
from load_snapshot import load

OUT = sys.argv[1]
BANK, SUB = 2_000_000, 1_000_000
TRAIN = int(BANK * 0.9)
POP_PER_DIM, CR, TOL, WINDOW, MAXGEN = 30, 0.7, 0.0002, 5, 80
FLOOR_W, HHI_TOP = 5.0, 0.20
QS = [0.05, 0.25, 0.5, 0.75, 0.95]

snap, kw = load("benchmarks/reference/inputs.json")
T = list(kw["tickers"])
N, S = len(T), len(kw["forecasted_matrices"])
ALPHA, FLOOR = kw["alpha_cdar"], kw["cvar_floor"]
ER = (1 + np.asarray(kw["drift"], dtype=float)) ** S - 1
RF = (1 + kw["rf_rate"]) ** (S / 52) - 1
bench.RESULTS = {}
RESULTS = dict(created=datetime.now().isoformat(timespec="seconds"), inputs_created=snap["created"],
               gpu=cp.cuda.runtime.getDeviceProperties(0)["name"].decode(),
               config=dict(bank=BANK, train=TRAIN, subset=SUB, pop_per_dim=POP_PER_DIM, cr=CR, tol=TOL, window=WINDOW,
                           maxgen=MAXGEN, hhi_top=HHI_TOP, hhi_inside=0.0, cvar_floor=FLOOR, floor_weight=FLOOR_W,
                           alpha=ALPHA, horizon_weeks=S, rf_12w=RF),
               tickers=T, er_12w=dict(zip(T, ER.tolist())), runs=[])


def save():
    json.dump(RESULTS, open(OUT, "w"), indent=1)


def G_(name, children, mn=None, mx=None):
    return dict(kind="group", name=name, children=children, min=mn, max=mx)


def A_(t, mn=None, mx=None):
    return dict(kind="asset", name=t, min=mn, max=mx)


def reference_tree(mf_max, alt_max=0.15):
    return G_("Portfolio", [
        G_("Equities", [G_("Technology", [A_(t) for t in ["NVDA", "META", "GOOGL", "ADBE"]]),
                        G_("Financials", [A_(t) for t in ["JPM", "NRIM", "SPGI"]]),
                        G_("Other equities", [A_(t) for t in ["FERG", "MNTS"]])]),
        G_("Alternatives", [G_("Crypto", [A_("BTC=F")]),
                            G_("Managed futures", [A_("DBMF"), A_("CTA", mn=0.25), A_("WTMF")], mx=mf_max)], mn=0.05, mx=alt_max),
        G_("Rates & index", [A_(t) for t in ["TLT", "IBHK", "SPY"]])])


# ---------- bank ----------
cp.random.seed(4242)
t0 = time.perf_counter()
host = bench.bank(kw, BANK, 500_000, keep=True)
G = cp.asarray(host)
del host
cp.get_default_memory_pool().free_all_blocks()
RESULTS["bank_build_s"] = round(time.perf_counter() - t0, 1)
VAL = cp.ascontiguousarray(G[TRAIN:].transpose(2, 0, 1))          # (steps, paths, assets), never searched on


def draw(rng, m=SUB):
    idx = cp.asarray(rng.integers(0, TRAIN, m))
    return cp.ascontiguousarray(G[idx].transpose(2, 0, 1))


def tails(Rt, W, cand_chunk=64):
    """CDaR and CVaR of each column of W on paths Rt."""
    m = Rt.shape[1]
    k = int(np.floor(ALPHA * (m - 1))) + 1
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
        out.append(cp.stack([cp.partition(dd, k - 1, axis=0)[:k].mean(axis=0), cp.partition(term, k - 1, axis=0)[:k].mean(axis=0)]).get())
    return np.concatenate(out, axis=1)


def score(Rt, A, er, hhi_w):
    cdar, cvar = tails(Rt, A)
    upi = (er - RF) / np.maximum(np.abs(cdar), 1e-10)
    f = -(upi - hhi_w * (A ** 2).sum(axis=0)) + FLOOR_W * np.maximum(0.0, FLOOR - cvar)
    return np.where(cdar < 0, f, 1e6)


def project(v, lo, hi, iters=60):
    a = (v - hi[:, None]).min(axis=0) - 1.0
    b = (v - lo[:, None]).max(axis=0) + 1.0
    for _ in range(iters):
        mid = (a + b) / 2
        s = np.clip(v - mid, lo[:, None], hi[:, None]).sum(axis=0)
        a = np.where(s > 1, mid, a)
        b = np.where(s > 1, b, mid)
    return np.clip(v - (a + b) / 2, lo[:, None], hi[:, None])


def search(name, M, lo, hi, hhi_w, seed):
    """DE over the columns of M (child -> asset mixing matrix, N x n)."""
    n = M.shape[1]
    if lo.sum() > 1 + 1e-12 or hi.sum() < 1 - 1e-12:
        raise ValueError(f"{name}: limits infeasible (mins {lo.sum():.0%}, maxes {hi.sum():.0%})")
    rng = np.random.default_rng(seed)
    P = POP_PER_DIM * n
    lhs = (rng.permuted(np.tile(np.arange(P), (n, 1)), axis=1) + rng.random((n, P))) / P
    pop = project(lhs / lhs.sum(axis=0), lo, hi)
    f = lambda W, R: score(R, M @ W, ER @ (M @ W), hhi_w)
    mean = f(pop, draw(rng))
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
        both = f(np.concatenate([pop, trial], axis=1), draw(rng))
        old, new = both[:P], both[P:]
        mean = (mean * cnt + old) / (cnt + 1)
        cnt += 1
        win = new < old
        pop[:, win] = trial[:, win]
        mean[win], cnt[win] = new[win], 1
        seasoned = np.where(cnt >= 2, mean, np.inf)
        inc = int(np.argmin(seasoned)) if np.isfinite(seasoned).any() else int(np.argmin(mean))
        hist.append(float(mean[inc]))
        t_gen.append(time.perf_counter() - t0)
        stop = g > WINDOW and hist[-1 - WINDOW] - hist[-1] < TOL
        if g % 5 == 0 or stop:
            print(f"[{name}] gen {g:>2}  incumbent {hist[-1]:+.5f}  {t_gen[-1]:.1f} s/gen", flush=True)
        if stop:
            break
    w = pop[:, inc]
    return dict(weights=w.tolist(), generations=g, stopped="window" if g < MAXGEN else "cap", history=hist,
                s_per_gen=round(float(np.mean(t_gen[1:] or t_gen)), 2), wall_s=round(float(np.sum(t_gen)), 1))


def run_tree(tree, label, seed0):
    rows, t_run = [], time.perf_counter()

    def walk(node, depth, seed):
        """Returns this node's mix over the assets (N,), searching inside it first (post-order)."""
        if node["kind"] == "asset":
            v = np.zeros(N)
            v[T.index(node["name"])] = 1.0
            node["_mix"] = v
            return v
        mixes = [walk(c, depth + 1, seed * 7 + i + 1) for i, c in enumerate(node["children"])]
        M = np.column_stack(mixes)
        lo = np.array([c["min"] or 0.0 for c in node["children"]])
        hi = np.array([1.0 if c["max"] is None else c["max"] for c in node["children"]])
        if len(mixes) == 1:
            w, rec = np.ones(1), dict(generations=0, stopped="one member", history=[], s_per_gen=0, wall_s=0)
        else:
            rec = search(node["name"], M, lo, hi, HHI_TOP if depth == 0 else 0.0, seed)
            w = np.asarray(rec["weights"])
        rec["binding"] = [dict(child=c["name"], at=("min" if abs(wi - l) < 1e-6 and l > 0 else "max"), limit=float(l if abs(wi - l) < 1e-6 and l > 0 else h))
                          for c, wi, l, h in zip(node["children"], w, lo, hi) if (abs(wi - l) < 1e-6 and l > 0) or (abs(wi - h) < 1e-6 and h < 1)]
        for c, wi in zip(node["children"], w):
            c["_share"] = float(wi)
        node["_search"] = rec
        node["_mix"] = M @ w
        return node["_mix"]

    walk(tree, 0, seed0)
    tree["_share"] = 1.0

    out = []

    def collect(node, eff, path):
        e = eff * node["_share"]
        out.append(dict(name=node["name"], kind=node["kind"], path=path, share=node["_share"], effective=float(e),
                        limits=dict(min=node.get("min"), max=node.get("max")), mix=node["_mix"].tolist(),
                        search={k: v for k, v in node.get("_search", {}).items() if k != "weights"} if node["kind"] == "group" else None))
        for c in node.get("children", []):
            collect(c, e, path + [node["name"]])

    collect(tree, 1.0, [])
    eff = tree["_mix"]
    # metrics, fans and distributions on the validation slice
    W = np.column_stack([r["mix"] for r in out])
    cdar, cvar = tails(VAL, W)
    Wg = cp.asarray(W, dtype=cp.float32)
    vals = cp.einsum("spa,ar->spr", VAL, Wg) + 1                        # (steps, paths, rows) value paths
    runmax = cp.ones(vals.shape[1:], dtype=vals.dtype)
    mdd = cp.zeros_like(runmax)                                          # per-path worst drawdown
    for t in range(S):
        cp.maximum(runmax, vals[t], out=runmax)
        cp.minimum(mdd, vals[t] / runmax - 1, out=mdd)
    term = vals[-1] - 1
    fan = cp.quantile(vals, cp.asarray(QS, dtype=cp.float32), axis=1).get()   # (q, steps, rows)
    for j, r in enumerate(out):
        tr, dd = term[:, j], mdd[:, j]
        er = float(ER @ np.asarray(r["mix"]))
        k = int(np.floor(ALPHA * (tr.size - 1))) + 1
        var = float(cp.sort(tr)[k - 1])
        r["metrics"] = dict(er_12w=er, sim_mean_12w=float(tr.mean()), vol_12w=float(tr.std()), var=var, cvar=float(cvar[j]),
                            cdar=float(cdar[j]), upi=(er - RF) / abs(float(cdar[j])) if cdar[j] < 0 else None)
        r["fan"] = {str(q): [1.0] + fan[i, :, j].tolist() for i, q in enumerate(QS)}
        lo_, hi_ = float(cp.quantile(tr, 0.001)), float(cp.quantile(tr, 0.999))
        h, edges = cp.histogram(tr, bins=60, range=(lo_, hi_))
        r["ret_hist"] = dict(edges=edges.get().tolist(), counts=h.get().tolist())
        lo_ = float(cp.quantile(dd, 0.001))
        h, edges = cp.histogram(dd, bins=60, range=(lo_, 0.0))
        r["dd_hist"] = dict(edges=edges.get().tolist(), counts=h.get().tolist())
        del r["mix"]
    del vals, runmax, mdd, term
    cp.get_default_memory_pool().free_all_blocks()
    return dict(label=label, finished=datetime.now().isoformat(timespec="seconds"), wall_s=round(time.perf_counter() - t_run, 1),
                effective=dict(zip(T, eff.tolist())), rows=out, validation_paths=BANK - TRAIN)


RESULTS["runs"].append(run_tree(reference_tree(0.30), "Reference tree: Alternatives at most 15% of the Portfolio", 11))
save()
RESULTS["runs"].append(run_tree(reference_tree(0.30, alt_max=0.25), "Alternatives at most 25% of the Portfolio", 11))
save()
print("done", flush=True)
