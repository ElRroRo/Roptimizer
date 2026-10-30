"""With per-asset betas and co-jumps: each asset's simulated 12-week mean vs its posterior, in standard errors."""
import io, contextlib, json, sys
sys.path.insert(0, ".")
import cupy as cp, numpy as np
from mso import bank, pipeline
from mso.cache import DayCache
with contextlib.redirect_stdout(io.StringIO()):
    inputs, rec = pipeline.build_inputs("portfolio_data.csv", day_cache=DayCache(offline=True))
out = {}
for label, kw in (("with betas", inputs), ("loading 1 (same inputs, betas removed)", None)):
    if kw is None:
        kw = dict(inputs); kw["sim_config"] = {k: v for k, v in inputs["sim_config"].items()
                                              if k not in ("jump_betas", "cojump_mults", "market_vol")}
    G = bank.build(kw, 2_000_000, 500_000, 7)
    term = G[:, :, -1]
    mean, sd = term.mean(axis=0).get(), term.std(axis=0).get()
    S = len(kw["forecasted_matrices"])
    post = (1 + np.asarray(kw["drift"])) ** S - 1
    z = (mean - post) / (sd / np.sqrt(G.shape[0]))
    out[label] = {t: dict(sim=float(m), posterior=float(p), z=round(float(zz), 2), sd=float(s))
                  for t, m, p, zz, s in zip(kw["tickers"], mean, post, z, sd)}
    print(label, "| max |z|", round(float(np.abs(z).max()), 2), "|", " ".join(f"{t} {zz:+.1f}" for t, zz in zip(kw["tickers"], z)))
    del G, term; cp.get_default_memory_pool().free_all_blocks()
json.dump(out, open(f"{sys.argv[1]}/posterior_check.json", "w"), indent=1)
