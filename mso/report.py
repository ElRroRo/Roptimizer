"""Per-row results on the bank's validation slice: the paths no search was scored on (#10).

Every row (an asset, a subportfolio or the Portfolio) is a mix over the assets. For each one this gives
the 12-week metrics, the outcome fan and the return and worst-drawdown histograms the results screens
draw (#8). Prototyped in benchmarks/prototypes/tree_run.py.
"""
from mso.xp import cp
import numpy as np

from mso.search import tails

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]


def _div(a, b):
    return a / b if b > 0 else None


def ratios(tr, dd, ulcer, er, rf_h, alpha, cvar, steps):
    """The usual evaluation ratios of one row, on the same validation paths. tr: 12-week returns, dd: worst
    drawdowns. Like UPI, the numerator is the expected excess return (er - rf); Omega and Rachev are the
    simulated distribution's own. Sharpe and Sortino are also given annualized by sqrt(52 / steps)."""
    ex, ann = er - rf_h, float(np.sqrt(52 / steps))
    d = tr - rf_h
    vol, down = float(tr.std()), float(cp.sqrt((cp.minimum(d, 0) ** 2).mean()))
    up, lo = float(cp.maximum(d, 0).mean()), float(cp.maximum(-d, 0).mean())
    k = int(np.floor(alpha * (tr.size - 1))) + 1
    best = float(cp.partition(-tr, k - 1)[:k].mean()) * -1            # mean of the best alpha share
    z = (tr - tr.mean()) / max(vol, 1e-12)
    avg_dd = float(dd.mean())
    sharpe, sortino = _div(ex, vol), _div(ex, down)
    return dict(sharpe=sharpe, sharpe_ann=None if sharpe is None else sharpe * ann,
                sortino=sortino, sortino_ann=None if sortino is None else sortino * ann,
                omega=_div(up, lo), starr=_div(ex, -cvar), rachev=_div(best, -cvar),
                calmar=_div(ex, -avg_dd), martin=_div(ex, ulcer), ulcer=ulcer, avg_mdd=avg_dd, downside_dev=down,
                skew=float((z ** 3).mean()), kurt=float((z ** 4).mean()) - 3, p_loss=float((tr < 0).mean()),
                p_below_rf=float((d < 0).mean()))


def row_metrics(VAL, mixes, er_assets, alpha, rf_h, bins=60):
    """VAL: validation paths (steps, paths, assets) on the device; mixes: assets x rows.
    Returns one dict per row: metrics, fan and histograms."""
    steps = VAL.shape[0]
    cdar, cvar = tails(VAL, mixes, alpha)
    Wg = cp.asarray(mixes, dtype=cp.float32)
    vals = cp.einsum("spa,ar->spr", VAL, Wg) + 1                        # (steps, paths, rows) value paths
    runmax = cp.ones(vals.shape[1:], dtype=vals.dtype)
    mdd = cp.zeros_like(runmax)                                          # per-path worst drawdown
    dd2 = cp.zeros_like(runmax)                                          # per-path sum of squared drawdowns (Ulcer index)
    for t in range(steps):
        cp.maximum(runmax, vals[t], out=runmax)
        dd = vals[t] / runmax - 1
        cp.minimum(mdd, dd, out=mdd)
        dd2 += dd * dd
    ulcer = cp.sqrt(dd2 / steps).mean(axis=0)
    term = vals[-1] - 1
    fan = cp.asnumpy(cp.quantile(vals, cp.asarray(QUANTILES, dtype=cp.float32), axis=1))   # (q, steps, rows)
    out = []
    for j in range(mixes.shape[1]):
        tr, dd = term[:, j], mdd[:, j]
        er = float(er_assets @ mixes[:, j])
        k = int(np.floor(alpha * (tr.size - 1))) + 1
        var = float(cp.sort(tr)[k - 1])
        row = dict(metrics=dict(er_12w=er, sim_mean_12w=float(tr.mean()), vol_12w=float(tr.std()), var=var,
                                cvar=float(cvar[j]), cdar=float(cdar[j]),
                                upi=(er - rf_h) / abs(float(cdar[j])) if cdar[j] < 0 else None,
                                **ratios(tr, dd, float(ulcer[j]), er, rf_h, alpha, float(cvar[j]), steps)))
        row["fan"] = {str(q): [1.0] + fan[i, :, j].tolist() for i, q in enumerate(QUANTILES)}
        lo, hi = float(cp.quantile(tr, 0.001)), float(cp.quantile(tr, 0.999))
        h, edges = cp.histogram(tr, bins=bins, range=(lo, hi))
        row["ret_hist"] = dict(edges=cp.asnumpy(edges).tolist(), counts=cp.asnumpy(h).tolist())
        lo = float(cp.quantile(dd, 0.001))
        h, edges = cp.histogram(dd, bins=bins, range=(lo, 0.0))
        row["dd_hist"] = dict(edges=cp.asnumpy(edges).tolist(), counts=cp.asnumpy(h).tolist())
        out.append(row)
    del vals, runmax, mdd, dd2, term
    cp.get_default_memory_pool().free_all_blocks()
    return out
