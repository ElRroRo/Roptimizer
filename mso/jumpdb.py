"""The jump database (#9): dated versions of the market-wide jump calibration, stored in git.

A version lives in jumpdb/<calibration date>/ (a second one the same day gets -2, -3, ...; a version is
never rewritten) and keeps:
  params.json       JUMP, HAWKES and COJUMP configs, each series' data window, the code commit
  pool.json         the pool as used: every ticker modelled, too short, no data or failed (with the error)
  diagnostics.json  veto days, shocks pooled, the GPD fits, the Hawkes estimates, the co-jump sample
  regime.png        the regime plot (v4.1 lost it to plt.show())
  tickers.json      per-ticker crash/rally betas and co-jump multipliers, added on first use (mso.betas)

The editable calibration pool is jumpdb/pool.json (pre-filled with the 406-ticker default; reset puts the
default back). Edits apply at the next recalibration. The systematic series stays ^GSPC.
Calibration runs only when asked (about 66 s, #9), never at import.

The calibration math below is v4.1's jump_paremeters.py moved into functions, unchanged.
"""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================
import copy
import datetime as dt
import json
import os
import subprocess
import time
import warnings

import numpy as np
import pandas as pd
from arch import arch_model
from scipy.stats import genpareto

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "jumpdb")
POOL_PATH = os.path.join(ROOT, "pool.json")
DEFAULT_POOL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_pool.json")
STALE_DAYS = 90
VETO_THRESHOLD = 3.0
MIN_WEEKS = 500          # "strict 10-year check": a pool ticker needs about 500 weekly returns

# Pre-calibration defaults, kept for get_scaled_jump_config callers and as the co-jump fallback.
DEFAULT_JUMP_CONFIG = {
    "systematic": {
        "lambda": 0.015, "prob_crash": 0.5, "crash_shape": 0.1, "crash_scale": 1.0,
        "rally_shape": 0.1, "rally_scale": 1.0, "threshold": 4.0
    },
    "idiosyncratic": {
        "lambda": 0.01, "prob_crash": 0.5, "crash_shape": 0.1, "crash_scale": 1.0,
        "rally_shape": 0.1, "rally_scale": 1.0, "threshold": 4.0
    }
}
# Discrete-time self-exciting intensity:
#   lambda_t = lambda_inf + (lambda_{t-1} - lambda_inf) * exp(-alpha) + beta * 1{jump at t-1}
DEFAULT_HAWKES_CONFIG = {
    "systematic":    {"lambda_inf": 0.015, "alpha": 1.0, "beta": 0.0},
    "idiosyncratic": {"lambda_inf": 0.010, "alpha": 1.0, "beta": 0.0},
}
# On a CRASH arrival, variance receives a positive jump J_v = m * theta_i, m ~ Exp(mean=var_jump_mult).
DEFAULT_COJUMP_CONFIG = {"var_jump_mult": 1.0}


class CalibrationError(RuntimeError):
    """The calibration could not produce parameters (no data, no jumps)."""


# ------------------------------------------------------------------ the pool

def default_pool():
    with open(DEFAULT_POOL_PATH) as f:
        d = json.load(f)
    return dict(systematic=d["systematic"], tickers=list(d["tickers"]))


def load_pool():
    """The editable pool, created from the default the first time."""
    if not os.path.exists(POOL_PATH):
        save_pool(default_pool()["tickers"])
    with open(POOL_PATH) as f:
        return json.load(f)


def save_pool(tickers):
    seen, clean = set(), []
    for t in tickers:
        t = str(t).strip().upper()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    if not clean:
        raise ValueError("the calibration pool cannot be empty")
    d = default_pool()
    body = dict(systematic=d["systematic"], tickers=clean, is_default=clean == d["tickers"],
                edited=dt.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(ROOT, exist_ok=True)
    tmp = POOL_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(body, f, indent=1)
    os.replace(tmp, POOL_PATH)
    return body


def reset_pool():
    return save_pool(default_pool()["tickers"])


# ------------------------------------------------------------------ calibration math (v4.1, unchanged)

def get_scaled_jump_config(config, days=5):
    """
    Scales daily jump probabilities (lambda) to a target period (e.g., 5 days for a week).
    Uses the exact formula: P(period) = 1 - (1 - P(day))^days
    """
    scaled = copy.deepcopy(config)
    for regime in ['systematic', 'idiosyncratic']:
        lam_day = scaled[regime]['lambda']
        scaled[regime]['lambda'] = 1 - (1 - lam_day)**days
    return scaled


def calibrate_hawkes_from_indicators(indicator, dt=1.0, lam_floor=1e-4, max_obs=4000):
    """
    Estimate discrete-time Hawkes parameters (lambda_inf, alpha, beta) from a binary
    jump-indicator time series via (Bernoulli) maximum likelihood on the recursive intensity.
    Returns a Poisson fallback (beta=0) when there are too few jumps to identify excitation.
    """
    from scipy.optimize import minimize
    J = np.asarray(indicator, dtype=float)
    J = J[np.isfinite(J)]
    if len(J) > max_obs:
        J = J[-max_obs:]
    n = len(J)
    base = float(max(J.mean(), lam_floor)) if n else lam_floor
    if n < 50 or J.sum() < 3:
        return {"lambda_inf": base, "alpha": 1.0, "beta": 0.0}

    def negll(params):
        lam_inf, alpha, beta = params
        e = np.exp(-alpha * dt)
        lam = lam_inf
        ll = 0.0
        for t in range(n):
            p = min(max(lam, 1e-6), 0.999)
            ll += J[t] * np.log(p) + (1.0 - J[t]) * np.log(1.0 - p)
            lam = lam_inf + (lam - lam_inf) * e + beta * J[t]
        return -ll

    x0 = [base, 1.0, base * 2.0]
    bounds = [(lam_floor, 0.5), (0.05, 5.0), (0.0, 0.9)]
    res = minimize(negll, x0, bounds=bounds, method="L-BFGS-B")
    lam_inf, alpha, beta = res.x
    beta = _cap_branching(alpha, beta)
    return {"lambda_inf": float(lam_inf), "alpha": float(alpha), "beta": float(beta)}


def _cap_branching(alpha, beta, cap=0.95):
    """Keep the discrete Hawkes recursion stationary.

    With E[J_t | lambda_t] = lambda_t, lambda_t follows an AR(1) with coefficient e^{-alpha} + beta, so
    the branching ratio is beta / (1 - e^{-alpha}) (one jump's excitation summed over its decay)."""
    limit = cap * (1.0 - np.exp(-alpha))
    return float(min(beta, limit))


def baseline_for_mean_rate(lam_mean, alpha, beta):
    """lambda_inf that makes the stationary mean intensity equal lam_mean.

    Stationary mean of the recursion: lambda_inf (1 - e) / (1 - e - beta), with e = e^{-alpha}. Using the
    observed jump rate itself as lambda_inf would inflate the simulated rate by 1 / (1 - branching)."""
    e = np.exp(-alpha)
    return float(lam_mean * (1.0 - e - beta) / (1.0 - e))


def _cojump_rises(std_resid, cond_var, crash_threshold=-3.0, horizon=1):
    z = np.asarray(std_resid, dtype=float)
    v = np.asarray(cond_var, dtype=float)
    m = min(len(z), len(v))
    z, v = z[-m:], v[-m:]
    mults = []
    for t in range(m - horizon):
        if z[t] < crash_threshold and v[t] > 0:
            rise = v[t + horizon] / v[t] - 1.0
            if np.isfinite(rise) and rise > 0:
                mults.append(rise)
    return mults


def calibrate_cojump_multiplier(std_resid, cond_var, crash_threshold=-3.0, horizon=1):
    """
    Calibrate the variance co-jump size as the average PROPORTIONAL rise in conditional
    variance in the `horizon` step(s) following a crash week (standardized residual below
    crash_threshold). Returned as a multiple of the pre-crash variance level.
    """
    mults = _cojump_rises(std_resid, cond_var, crash_threshold, horizon)
    if len(mults) < 3:
        return DEFAULT_COJUMP_CONFIG["var_jump_mult"]
    return float(np.mean(mults))


def calibrate_regimes_direct(data_input, threshold=4.0, focus_quantile=0.1, label="Asset"):
    """
    Calibrates Pareto parameters but PRIORITIZES the worst 'focus_quantile' (e.g., 10%)
    to ensure the model captures the massive crashes.

    Args:
        data_input (list or array or dict):
            - If dict (vol_models), extracts residuals iteratively.
            - If array/list, uses directly (already pooled/cleaned).
    """
    pooled_z = []

    # 1. Handle Input Types - CHECK ARRAY/LIST FIRST
    if isinstance(data_input, (list, np.ndarray, pd.Series)):
        pooled_z = data_input
    elif isinstance(data_input, dict):
        for ticker, res in data_input.items():
            z = res.std_resid.dropna()
            pooled_z.extend(z.values)
    else:
        pooled_z = data_input

    pooled_z = np.array(pooled_z)
    total_obs = len(pooled_z)

    if total_obs == 0: return None  # Safety
    jumps = pooled_z[np.abs(pooled_z) > threshold]
    if len(jumps) == 0: return None  # Safety

    crashes = jumps[jumps < 0]
    rallies = jumps[jumps > 0]

    # --- HELPER: The Tail-Focused Logic ---
    def fit_with_focus(data_array, base_thresh, quantile):
        # data_array is the magnitude (absolute value)

        # A. Find the "Nightmare Line" (e.g., the worst 10% of the jumps)
        # quantile=0.10 means we look at the top 10% of magnitude
        MAX_PARETO_SHAPE = 0.3
        if len(data_array) < 10:
            # Same [0, 0.3] shape bounds as the main path, so a thin tail cannot inject an explosive shape.
            c_small, _, _ = genpareto.fit(data_array - base_thresh, floc=0)
            c_small = float(np.clip(c_small, 0.0, MAX_PARETO_SHAPE))
            _, _, scale_small = genpareto.fit(data_array - base_thresh, fc=c_small, floc=0)
            return c_small, 0, scale_small

        extreme_thresh = np.quantile(data_array, 1 - quantile)

        # B. Isolate the Monsters
        monsters = data_array[data_array >= extreme_thresh]

        # C. Fit Shape (c) ONLY on the monsters
        # This decides "How fat is the tail?" based only on the worst events
        c_extreme, _, _ = genpareto.fit(monsters - extreme_thresh, floc=0)

        # --- NATURAL CAP (COMMON SENSE FIX) ---
        # If shape > 0.3, the tail becomes mathematically "explosive" (near-infinite variance).
        # We cap it at 0.3 to ensure "Fat Tails" without the "Infinite Noise" problem.
        if c_extreme > MAX_PARETO_SHAPE:
            c_extreme = MAX_PARETO_SHAPE
        elif c_extreme < 0:
            c_extreme = 0

        # D. Fit Scale on the FULL set, but holding Shape constant
        # This ensures the curve starts at the right height (3 sigma) but decays at the "monster" rate
        _, _, scale_final = genpareto.fit(data_array - base_thresh, fc=c_extreme, floc=0)

        return c_extreme, 0, scale_final

    # 2. Fit Parameters using the Helper
    if len(crashes) > 0:
        c_crash, _, scale_crash = fit_with_focus(np.abs(crashes), threshold, quantile=focus_quantile)
        prob_crash = len(crashes) / len(jumps)
    else:
        c_crash, scale_crash, prob_crash = 0.1, 1.0, 0.5

    if len(rallies) > 0:
        c_rally, _, scale_rally = fit_with_focus(np.abs(rallies), threshold, quantile=focus_quantile)
        prob_rally = len(rallies) / len(jumps)
    else:
        c_rally, scale_rally, prob_rally = 0.1, 1.0, 0.5

    lambda_param = len(jumps) / total_obs

    return {
        "label": label,
        "lambda": lambda_param,
        "threshold": threshold,
        "prob_crash": prob_crash,
        "crash_params": (c_crash, scale_crash),
        "rally_params": (c_rally, scale_rally),
        "data": {"crashes": crashes, "rallies": rallies, "total_count": len(jumps)}
    }


def plot_regimes_side_by_side(sys_result, idio_result, path=None):
    """The regime plot: pooled jump sizes against the fitted tails. Saved to `path` when given."""
    import matplotlib.pyplot as plt
    if sys_result is None and idio_result is None: return

    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    plt.style.use('dark_background')

    results = []
    if sys_result: results.append(sys_result)
    if idio_result: results.append(idio_result)

    for i, res in enumerate(results):
        ax = axes[i] if len(results) > 1 else axes
        thresh = res['threshold']
        total = res['data']['total_count']

        crashes = res['data']['crashes']
        rallies = res['data']['rallies']

        w_c = np.ones_like(crashes) / total if len(crashes) > 0 else []
        w_r = np.ones_like(rallies) / total if len(rallies) > 0 else []

        bins = np.linspace(-20, 20, 100)
        bin_width = bins[1] - bins[0]

        if len(crashes) > 0:
            ax.hist(crashes, bins=bins, weights=w_c, color='#D00000', alpha=0.8, label='Crashes', edgecolor='black')
        if len(rallies) > 0:
            ax.hist(rallies, bins=bins, weights=w_r, color='#008000', alpha=0.8, label='Rallies', edgecolor='black')

        c_c, s_c = res['crash_params']
        x_c = np.linspace(-20, -thresh, 200)
        pdf_c = genpareto.pdf(np.abs(x_c) - thresh, c_c, loc=0, scale=s_c)
        ax.plot(x_c, pdf_c * res['prob_crash'] * bin_width, 'b--', linewidth=2.5, label=f'Shape={c_c:.2f}')

        c_r, s_r = res['rally_params']
        x_r = np.linspace(thresh, 20, 200)
        pdf_r = genpareto.pdf(x_r - thresh, c_r, loc=0, scale=s_r)
        ax.plot(x_r, pdf_r * (1 - res['prob_crash']) * bin_width, 'w--', linewidth=2.5)

        ax.set_title(res['label'], fontsize=16, fontweight='bold', color='white', pad=15)
        ax.set_xlabel("Jump Size (Z-Score)", color='white')
        ax.text(0.05, 0.95, rf"Freq ($\lambda$): {res['lambda']:.2%}", transform=ax.transAxes, color='yellow',
                fontsize=12, fontweight='bold', va='top')

        ax.axvspan(-thresh, thresh, color='gray', alpha=0.15)
        ax.legend(loc='upper right', frameon=True, facecolor='black')
        ax.grid(alpha=0.2)

    plt.tight_layout()
    if path:
        fig.savefig(path, dpi=110)
        plt.close(fig)
    else:
        plt.show()


# ------------------------------------------------------------------ download + calibrate

def download(pool, systematic="^GSPC", progress=False):
    """Max-history weekly closes for the systematic series and the pool, exactly as v4.1 downloaded them."""
    import yfinance as yf
    sys_data = yf.download([systematic], period="max", interval="1wk", progress=False, auto_adjust=True)['Close']
    try:
        idio_data = yf.download(list(pool), period="max", interval="1wk", progress=progress, auto_adjust=True)['Close']
    except Exception as e:
        raise CalibrationError(f"pool download failed: {e}") from e
    # A batch download can return a column empty on a transient Yahoo error. Retry each empty one on its
    # own; what is still empty is recorded as "no data" in the version's pool.json (2026-10-29: AVB, BK,
    # CTRA, HOLX, SEE and YELLQ, all empty on retry too).
    order = list(idio_data.columns)
    empty = [t for t in order if idio_data[t].dropna().empty]
    for t in empty:
        try:
            s = yf.download([t], period="max", interval="1wk", progress=False, auto_adjust=True)['Close']
            s = s[t] if isinstance(s, pd.DataFrame) else s
        except Exception:
            continue
        if not s.dropna().empty:
            idio_data = idio_data.drop(columns=t).join(s.rename(t), how="outer")
    # Keep the batch's column order: the idiosyncratic Hawkes estimate uses the first 60 qualifying series.
    idio_data = idio_data[order]
    # Drop the week still in progress (v4.1 calibrated on it, so a version made on Monday morning and one
    # made on Friday differed). Same rule as the return panel (#3).
    from mso.data import drop_incomplete_week
    return drop_incomplete_week(sys_data), drop_incomplete_week(idio_data)


def calibrate(sys_data, idio_data, pool=None, verbose=True):
    """The jump calibration on downloaded weekly closes. Returns a dict with the three configs, the pool
    as used, the diagnostics, and the two regime results for the plot. Raises CalibrationError when it
    cannot produce parameters (v4.1 silently kept its defaults)."""
    say = print if verbose else (lambda *a, **k: None)
    warnings.filterwarnings('ignore')
    t0 = time.perf_counter()
    pool = list(pool) if pool is not None else list(getattr(idio_data, "columns", []))
    sys_returns = np.log(sys_data / sys_data.shift(1)).dropna()

    status = {t: dict(status="no data") for t in pool}
    idio_data = idio_data.dropna(axis=1, how='all')
    # Returns per ticker on its OWN dates: a batch download puts tickers on one union grid where their weekly
    # rows do not line up, so a grid-wide shift(1) divides by an empty row and silently drops ~95% of the pool.
    idio_returns = idio_data.apply(lambda c: np.log(c.dropna() / c.dropna().shift(1))).dropna(how='all')

    say("\n2. Modeling Systematic Risk (Veto Layer)...")
    sys_series = sys_returns if isinstance(sys_returns, pd.Series) else sys_returns.iloc[:, 0]
    am_sys = arch_model(sys_series, mean="AR", vol="GARCH", p=1, q=1)
    res_sys = am_sys.fit(disp="off", show_warning=False)
    if res_sys.convergence_flag != 0:
        sys_std_resid = (sys_series - sys_series.mean()) / sys_series.std()
    else:
        sys_std_resid = res_sys.std_resid.dropna()

    veto_mask = abs(sys_std_resid) > VETO_THRESHOLD
    veto_dates = sys_std_resid.index[veto_mask]
    say(f"   >> Identified {len(veto_dates)} Systemic Jump Days (Vetoed).")

    say(f"\n3. Fitting & Filtering Idiosyncratic Pool (n={len(idio_returns.columns)})...")
    count = 0
    clean_idiosyncratic_pool = []
    idio_indicator_series = []
    for i, t in enumerate(idio_returns.columns):
        series = idio_returns[t].dropna()
        if len(series) < MIN_WEEKS:
            status[t] = dict(status="too short", weeks=int(len(series)))
            continue
        try:
            am = arch_model(series, mean="AR", vol="GARCH")
            res = am.fit(disp="off", show_warning=False)
            if res.convergence_flag != 0:
                vol = series.std()
                z_scores = (series - series.mean()) / vol
                fit = "constant volatility (GARCH did not converge)"
            else:
                z_scores = res.std_resid.dropna()
                fit = "AR-GARCH(1,1)"
            clean_z = z_scores[~z_scores.index.isin(veto_dates)]
            clean_idiosyncratic_pool.extend(clean_z.values)
            idio_indicator_series.append((np.abs(clean_z.values) > 3.0).astype(float))
            count += 1
            status[t] = dict(status="modelled", weeks=int(len(series)), fit=fit,
                             first=str(series.index[0].date()), last=str(series.index[-1].date()))
        except Exception as e:
            status[t] = dict(status="failed", weeks=int(len(series)), error=f"{type(e).__name__}: {e}")
        if verbose and i % 20 == 0:
            print(f"   Progress: {i}/{len(idio_returns.columns)} | Fitted: {count}...", end='\r')
    say(f"\n   >> COMPLETED. Final Count: {count} assets modeled.")
    say(f"   >> Total Idiosyncratic Shocks Collected: {len(clean_idiosyncratic_pool)}")

    say("\n4. Calibrating Regimes (Tail-Focused)...")
    sys_res = calibrate_regimes_direct(sys_std_resid.values, threshold=3.0, label="SYSTEMATIC (S&P 500)")
    idio_res = calibrate_regimes_direct(clean_idiosyncratic_pool, threshold=3.0,
                                        label=f"IDIOSYNCRATIC (Filtered, n={count})")
    if not (sys_res and idio_res):
        raise CalibrationError(f"no jumps to calibrate (systematic {'ok' if sys_res else 'empty'}, "
                               f"idiosyncratic {'ok' if idio_res else 'empty'}, {count} pool tickers modelled)")

    jump_config = {layer: {
        "lambda": r['lambda'], "prob_crash": r['prob_crash'],
        "crash_shape": r['crash_params'][0], "crash_scale": r['crash_params'][1],
        "rally_shape": r['rally_params'][0], "rally_scale": r['rally_params'][1],
        "threshold": r['threshold']} for layer, r in (("systematic", sys_res), ("idiosyncratic", idio_res))}

    say("\n5. Calibrating Hawkes self-excitation (jump clustering)...")
    sys_indicator = (np.abs(sys_std_resid.values) > 3.0).astype(float)
    sys_hawkes = calibrate_hawkes_from_indicators(sys_indicator)
    sys_hawkes["lambda_inf"] = baseline_for_mean_rate(sys_res["lambda"], sys_hawkes["alpha"], sys_hawkes["beta"])
    idio_subset = [s for s in idio_indicator_series if s.sum() >= 3][:60]
    if idio_subset:
        ests = [calibrate_hawkes_from_indicators(s) for s in idio_subset]
        a_med = float(np.median([e["alpha"] for e in ests]))
        b_med = _cap_branching(a_med, float(np.median([e["beta"] for e in ests])))  # medians need not be jointly stationary
        idio_hawkes = {"lambda_inf": baseline_for_mean_rate(idio_res["lambda"], a_med, b_med),
                       "alpha": a_med, "beta": b_med}
    else:
        idio_hawkes = {"lambda_inf": idio_res["lambda"], "alpha": 1.0, "beta": 0.0}
    hawkes_config = {"systematic": sys_hawkes, "idiosyncratic": idio_hawkes}

    cojump_config = dict(DEFAULT_COJUMP_CONFIG)
    rises = []
    if res_sys.convergence_flag == 0:
        z, v = res_sys.std_resid.dropna().values, res_sys.conditional_volatility.values ** 2
        cojump_config["var_jump_mult"] = calibrate_cojump_multiplier(z, v)
        rises = _cojump_rises(z, v)

    say("\n--- FINAL JUMP PARAMETERS (Veto Applied) ---")
    say("JUMP_CONFIG  :", jump_config)
    say("HAWKES_CONFIG:", hawkes_config)
    say("COJUMP_CONFIG:", cojump_config)

    counts = {}
    for s in status.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    win = lambda idx: dict(first=str(pd.Timestamp(idx[0]).date()), last=str(pd.Timestamp(idx[-1]).date()), weeks=int(len(idx)))
    diagnostics = dict(
        seconds=round(time.perf_counter() - t0, 1),
        systematic_fit="AR-GARCH(1,1)" if res_sys.convergence_flag == 0 else "constant volatility (GARCH did not converge)",
        veto_threshold=VETO_THRESHOLD, veto_weeks=int(len(veto_dates)),
        veto_last=[str(pd.Timestamp(d).date()) for d in veto_dates[-10:]],
        pool_counts=counts, shocks_pooled=int(len(clean_idiosyncratic_pool)),
        gpd={layer: dict(jumps=int(r["data"]["total_count"]), crashes=int(len(r["data"]["crashes"])),
                         rallies=int(len(r["data"]["rallies"])), observations=int(len(sys_std_resid)) if layer == "systematic" else int(len(clean_idiosyncratic_pool)))
             for layer, r in (("systematic", sys_res), ("idiosyncratic", idio_res))},
        hawkes=dict(systematic_indicator_weeks=int(len(sys_indicator)), idiosyncratic_series_used=len(idio_subset)),
        cojump=dict(crash_weeks_with_rise=len(rises), fallback=len(rises) < 3),
    )
    windows = dict(systematic=win(sys_std_resid.index),
                   pool=dict(first=min((s["first"] for s in status.values() if s.get("first")), default=None),
                             last=max((s["last"] for s in status.values() if s.get("last")), default=None)))
    return dict(jump_config=jump_config, hawkes_config=hawkes_config, cojump_config=cojump_config,
                pool=status, diagnostics=diagnostics, windows=windows, sys_res=sys_res, idio_res=idio_res)


# ------------------------------------------------------------------ versions

def _commit():
    try:
        return subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def _plain(o):
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    return o


def write_version(result, systematic="^GSPC", day=None, root=ROOT):
    """Store a calibration as a new dated version and return its name."""
    day = day or dt.date.today().isoformat()
    name, n = day, 1
    while os.path.exists(os.path.join(root, name)):
        n += 1
        name = f"{day}-{n}"
    d = os.path.join(root, name)
    os.makedirs(d)
    params = dict(version=name, created=dt.datetime.now().isoformat(timespec="seconds"), code_commit=_commit(),
                  systematic=systematic, jump_config=result["jump_config"], hawkes_config=result["hawkes_config"],
                  cojump_config=result["cojump_config"], windows=result["windows"])
    for fname, body in (("params.json", params), ("pool.json", result["pool"]), ("diagnostics.json", result["diagnostics"])):
        with open(os.path.join(d, fname), "w") as f:
            json.dump(_plain(body), f, indent=1)
    plot_regimes_side_by_side(result["sys_res"], result["idio_res"], os.path.join(d, "regime.png"))
    return name


def recalibrate(verbose=True):
    """Download the editable pool, calibrate and store a new version (the GUI's Recalibrate)."""
    pool = load_pool()
    if verbose:
        print(f"1. Downloading Data for {len(pool['tickers'])} assets...")
    sys_data, idio_data = download(pool["tickers"], pool["systematic"], progress=verbose)
    result = calibrate(sys_data, idio_data, pool["tickers"], verbose=verbose)
    return write_version(result, pool["systematic"])


def versions(root=ROOT):
    """Version names, oldest first."""
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n, "params.json")))


def load(version="latest", root=ROOT, today=None):
    """A stored version's parameters, with `stale` (older than 90 days) and `age_days`."""
    names = versions(root)
    if not names:
        raise FileNotFoundError(f"the jump database at {root} has no versions: run a recalibration "
                                f"(python -m mso jumpdb recalibrate)")
    name = names[-1] if version in (None, "latest") else version
    path = os.path.join(root, name, "params.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"jump database version {name!r} not found (have {', '.join(names)})")
    with open(path) as f:
        p = json.load(f)
    age = ((today or dt.date.today()) - dt.date.fromisoformat(name[:10])).days
    p.update(age_days=age, stale=age > STALE_DAYS, path=os.path.dirname(path))
    return p
