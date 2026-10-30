"""The scenario bank: every asset's cumulative-return paths, simulated once per run and held on the GPU.

Layout is path-major, (paths, assets, steps), float32, so a random subset of paths is a gather of rows.
Chunks are simulated with the Heston-Bates engine and written straight into one preallocated device
array, never routed through host memory (#5: host gathers are slower than simulating fresh).
A portfolio's value path in a scenario is 1 + cum @ w (buy-and-hold since t=0).
"""
import time

from mso.xp import cp
import numpy as np

from mso import sim

BYTES_PER_VALUE = 4


def sim_kwargs(inputs):
    """The simulator's keyword arguments from an inputs dict (run_optimization's arguments)."""
    return dict(initial_prices=inputs["initial_prices"], forecasted_matrices=inputs["forecasted_matrices"],
                drift=inputs["drift"], jump_config=inputs["jump_config"], **inputs["sim_config"])


def bank_bytes(paths, assets, steps):
    return paths * assets * steps * BYTES_PER_VALUE


SIM_BYTES_PER_PATH_ASSET = 312   # simulator peak while building a chunk: 4M paths x 16 assets took 18.6 GiB (#10)
SCORE_CANDIDATES = 64            # candidates scored at once (search.tails): two float32 buffers of draw x 64 each


def plan(assets, steps, cap, draw, chunk, free=None):
    """(bank paths, chunk paths, draw paths) that fit the GPU through both phases of a run:
      build   the preallocated bank plus one chunk being simulated (SIM_BYTES_PER_PATH_ASSET each path-asset);
      search  the bank plus one draw, gathered and transposed (two copies), plus the scoring scratch.
    The chunk is never given more than the search will need anyway, and the draw halves until the bank is at
    least twice the draw. 2026-10-29: 25 assets with 4M-path chunks ran out of memory on the A100 (the old rule
    sized the bank alone)."""
    if free is None:
        cp.get_default_memory_pool().free_all_blocks()
        free, _ = cp.cuda.runtime.memGetInfo()
    per_path = assets * steps * BYTES_PER_VALUE
    margin = min(2**30, 0.1 * free)
    d = draw
    while d >= 100_000:
        search_need = 2 * d * per_path + 2 * d * SCORE_CANDIDATES * BYTES_PER_VALUE
        c = int(min(chunk, max(search_need / (assets * SIM_BYTES_PER_PATH_ASSET), 100_000)) // 100_000 * 100_000)
        need = max(search_need, c * assets * SIM_BYTES_PER_PATH_ASSET)
        n = int(max(free - margin - need, 0) / per_path) // 100_000 * 100_000
        if n >= 2 * d:
            n = min(cap, n)
            return n, min(c, n), d
        d = d // 2 // 100_000 * 100_000
    raise RuntimeError(f"not enough GPU memory for a scenario bank of {assets} assets: {free / 2**30:.1f} GiB free")


def laptop_paths(assets, steps, cap=2_000_000, headroom=3 * 2**30):
    """Largest bank (in 100k steps, at most `cap`) that leaves `headroom` bytes free for simulating a chunk
    and for one search draw of up to half the bank. 2M at 16 assets on the 6 GB RTX 3060 (#5). Superseded by
    plan(), which accounts for the chunk and the draw explicitly; kept for the benchmarks that call it."""
    cp.get_default_memory_pool().free_all_blocks()
    free, _ = cp.cuda.runtime.memGetInfo()
    per_path = assets * steps * BYTES_PER_VALUE * 1.5
    n = int(max(free - headroom, 0) / per_path) // 100_000 * 100_000
    if n < 100_000:
        raise RuntimeError(f"not enough GPU memory for a scenario bank: {free / 2**30:.1f} GiB free")
    return min(cap, n)


def build(inputs, paths, chunk, seed, progress=None):
    """Simulate `paths` scenarios in chunks of `chunk` and return the device bank (paths, assets, steps).
    Seeded with CuPy's global generator, so the same seed, chunk size and machine give a bit-identical bank."""
    sk = sim_kwargs(inputs)
    rest = {k: v for k, v in sk.items() if k not in ("initial_prices", "forecasted_matrices", "drift", "jump_config")}
    n_assets, n_steps = len(inputs["tickers"]), len(inputs["forecasted_matrices"])
    w = np.ones(n_assets) / n_assets          # unused by the cumulative paths; the simulator wants weights
    pool = cp.get_default_memory_pool()
    G = cp.empty((paths, n_assets, n_steps), dtype=cp.float32)
    cp.random.seed(seed)
    done, t0 = 0, time.perf_counter()
    while done < paths:
        m = min(chunk, paths - done)
        pool.free_all_blocks()
        cum = sim.monte_carlo_simulation(sk["initial_prices"], sk["forecasted_matrices"], m, sk["drift"], w,
                                         sk["jump_config"], return_paths=True, return_cum=True, **rest)
        if cum.shape != (n_assets, n_steps, m):
            raise RuntimeError(f"simulator returned {cum.shape}, expected {(n_assets, n_steps, m)}")
        G[done:done + m] = cum.transpose(2, 0, 1)
        del cum
        done += m
        if progress:
            progress(done, paths, time.perf_counter() - t0)
    cp.cuda.Device().synchronize()
    pool.free_all_blocks()
    return G
