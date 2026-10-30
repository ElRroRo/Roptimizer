"""The v5.0 search: an own differential-evolution loop that scores every generation on a fresh bank draw.

Decided in #6 and #10, prototyped in benchmarks/prototypes/search_loop.py and tree_run.py:
- best1bin, population POP_PER_DIM x n, dithered F in [0.5, 1), CR 0.7, Latin-hypercube start;
- limits enforced by projecting every vector onto {lo <= w <= hi, sum w = 1}, never clipped afterwards;
- each generation draws one fresh subset of the bank; trials AND survivors are scored on it in one
  batched pass; a trial replaces its parent if better on that same draw; survivors keep a running mean;
- stop when the incumbent's running mean gains < tol over the last `window` generations, cap `maxgen`.

A search runs over the columns of a mixing matrix M (child -> asset, assets x children). A flat
portfolio is M = I; a subportfolio's parent sees each frozen child as one column. Scoring goes through
effective asset weights A = M @ W, because buy-and-hold is linear in the weights.
"""
import time
from dataclasses import dataclass

from mso.xp import cp
import numpy as np


class SearchInfeasible(ValueError):
    """No candidate is acceptable (every one rejected), so the search has no answer."""


@dataclass
class SearchConfig:
    pop_per_dim: int = 30
    cr: float = 0.7
    tol: float = 0.0002
    window: int = 5
    maxgen: int = 80
    draw: int = 1_000_000          # paths per generation's draw (3M on the A100, #5)
    trace: bool = False            # keep every generation's incumbent (for the stop-rule study)
    noise: int = 0                 # score the final incumbent on this many fresh draws (draw-to-draw noise)


@dataclass
class Objective:
    """What a candidate is scored on: -(UPI - hhi * sum A^2) + floor_weight * max(0, cvar_floor - CVaR)."""
    alpha: float                   # tail level for CVaR and CDaR
    cvar_floor: float
    rf_h: float                    # risk-free return over the horizon
    hhi: float = 0.20              # concentration penalty on effective weights (0 inside subportfolios, #10)
    floor_weight: float = 5.0      # soft CVaR floor: penalty per unit of breach
    hard_floor: bool = False       # hard floor: a candidate whose CVaR breaches the floor is rejected


def horizon_returns(drift_weekly, steps):
    """Posterior expected return of each asset over the horizon, from its weekly posterior drift."""
    return (1 + np.asarray(drift_weekly, dtype=float)) ** steps - 1


def draw(G, rng, m, limit=None):
    """`m` paths drawn with replacement from the first `limit` rows of the bank, as (steps, paths, assets)."""
    idx = cp.asarray(rng.integers(0, G.shape[0] if limit is None else limit, m))
    return cp.ascontiguousarray(G[idx].transpose(2, 0, 1))


def tails(Rt, A, alpha, cand_chunk=64):
    """CDaR and CVaR of every column of A (assets x candidates) on the paths Rt (steps x paths x assets).
    CDaR is the mean of the worst alpha share of per-path maximum drawdowns (#3)."""
    m, steps = Rt.shape[1], Rt.shape[0]
    k = int(np.floor(alpha * (m - 1))) + 1                         # count of paths at or below the percentile
    out = []
    Ag = cp.asarray(A, dtype=cp.float32)
    for c0 in range(0, A.shape[1], cand_chunk):
        w = Ag[:, c0:c0 + cand_chunk]
        runmax = cp.ones((m, w.shape[1]), dtype=cp.float32)
        dd = cp.zeros_like(runmax)
        for t in range(steps):
            x = 1 + Rt[t] @ w
            cp.maximum(runmax, x, out=runmax)
            cp.minimum(dd, x / runmax - 1, out=dd)
        term = x - 1
        cdar = cp.partition(dd, k - 1, axis=0)[:k].mean(axis=0)
        cvar = cp.partition(term, k - 1, axis=0)[:k].mean(axis=0)
        out.append(cp.asnumpy(cp.stack([cdar, cvar])))
    return np.concatenate(out, axis=1)


def score(Rt, A, er, obj):
    """Objective of every column of A; er is each candidate's expected return over the horizon."""
    cdar, cvar = tails(Rt, A, obj.alpha)
    upi = (er - obj.rf_h) / np.maximum(np.abs(cdar), 1e-10)
    f = -(upi - obj.hhi * (A ** 2).sum(axis=0)) + obj.floor_weight * np.maximum(0.0, obj.cvar_floor - cvar)
    if obj.hard_floor:
        f = np.where(cvar < obj.cvar_floor, 1e6, f)
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


def search(name, G, M, er_children, obj, cfg, seed, lo=None, hi=None, draw_limit=None, on_generation=None):
    """DE over the n columns of M. Returns the incumbent's child weights and the search's record.

    G: the device bank; er_children: each child's expected return over the horizon (a flat portfolio: each
    asset's; a parent: its children's implied returns, blended with any subportfolio view); draw_limit: draw
    only from the first rows (the rest is the validation slice);
    on_generation(g, incumbent, scored, s_per_gen, replaced, stop)."""
    er_children = np.asarray(er_children, dtype=float)
    n = M.shape[1]
    lo = np.zeros(n) if lo is None else np.asarray(lo, float)
    hi = np.ones(n) if hi is None else np.asarray(hi, float)
    if lo.sum() > 1 + 1e-12 or hi.sum() < 1 - 1e-12:
        raise ValueError(f"{name}: limits infeasible (mins {lo.sum():.0%}, maxes {hi.sum():.0%})")
    if cfg.maxgen < 1:
        raise ValueError(f"{name}: maxgen must be at least 1, got {cfg.maxgen}")
    rng = np.random.default_rng(seed)
    P = cfg.pop_per_dim * n
    # Latin hypercube in [0,1]^n, then repaired onto the feasible set
    lhs = (rng.permuted(np.tile(np.arange(P), (n, 1)), axis=1) + rng.random((n, P))) / P
    pop = project(lhs / lhs.sum(axis=0), lo, hi)

    def f(W, R):
        return score(R, M @ W, er_children @ W, obj)

    mean = f(pop, draw(G, rng, cfg.draw, draw_limit))
    cnt = np.ones(P)
    hist, t_gen, trace = [], [], []
    for g in range(1, cfg.maxgen + 1):
        t0 = time.perf_counter()
        best = pop[:, np.argmin(mean)]
        F = rng.uniform(0.5, 1.0)
        r = np.array([rng.choice(np.delete(np.arange(P), i), 2, replace=False) for i in range(P)])
        mutant = best[:, None] + F * (pop[:, r[:, 0]] - pop[:, r[:, 1]])
        cross = rng.random((n, P)) < cfg.cr
        cross[rng.integers(0, n, P), np.arange(P)] = True
        trial = project(np.clip(np.where(cross, mutant, pop), 0, None), lo, hi)
        both = f(np.concatenate([pop, trial], axis=1), draw(G, rng, cfg.draw, draw_limit))
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
        if cfg.trace:
            trace.append(pop[:, inc].tolist())
        t_gen.append(time.perf_counter() - t0)
        stop = g > cfg.window and hist[-1 - cfg.window] - hist[-1] < cfg.tol
        if on_generation:
            on_generation(g, hist[-1], int(cnt[inc]), t_gen[-1], int(win.sum()), stop)
        if stop:
            break
    if hist[-1] >= 1e5:
        # Every candidate rejected (a hard CVaR floor no mix meets): a search that ranks nothing is not an
        # answer. Report the best CVaR any member reaches, so the floor can be set to something possible.
        _, cvar = tails(draw(G, rng, cfg.draw, draw_limit), M @ pop, obj.alpha)
        raise SearchInfeasible(f"{name}: every candidate breaks the hard CVaR floor of {obj.cvar_floor:.1%}; "
                               f"the best CVaR in the final population is {float(cvar.max()):.1%}. Lower the "
                               f"floor or make it soft.")
    w = pop[:, inc]
    out = dict(weights=w.tolist(), generations=g, stopped="window" if stop else "cap",
               incumbent=hist[-1], incumbent_scored=int(cnt[inc]), history=hist,
               s_per_gen=round(float(np.mean(t_gen[1:] or t_gen)), 2), wall_s=round(float(np.sum(t_gen)), 1),
               within_limits=bool(np.all(w >= lo - 1e-9) and np.all(w <= hi + 1e-9)))
    if cfg.trace:
        out["trace"] = trace
    if cfg.noise:
        wk = w[:, None]
        vals = [float(f(wk, draw(G, rng, cfg.draw, draw_limit))[0]) for _ in range(cfg.noise)]
        out["noise"] = dict(draws=cfg.noise, paths=cfg.draw, values=vals, sd=float(np.std(vals, ddof=1)))
    return out
