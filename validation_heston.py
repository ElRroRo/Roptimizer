# ==============================================================================
# PROJECT: Roptimizer
# Heston-Bates migration -- VALIDATION & A/B HARNESS
#
# Demonstrates the marginal contribution of each new model component to tail risk by
# simulating an EQUAL-WEIGHT portfolio under a ladder of engines on identical data:
#
#   1. Legacy GBM (deterministic DCC variance, memoryless jumps)   -- the old model
#   2. Heston diffusion only (stochastic variance, jumps OFF)
#   3. Heston + Bates jumps (memoryless, Hawkes beta = 0)
#   4. + Hawkes self-excitation (jump clustering)
#   5. + Variance co-jumps (SVJJ)
#
# For each it reports mean return, volatility, CVaR(5%), CDaR(5%), excess kurtosis, and the
# CONDITIONAL mean return on the worst-drawdown decile (mean|DD10).
#
# Expectation: tail risk (|CVaR|, |CDaR|, kurtosis) grows monotonically down the ladder, while BOTH
# the unconditional and the conditional mean stay flat.
#
# Why the conditional column exists. A drift bias that lives only in high-variance states is
# invisible in an unconditional mean over 400k paths -- the overwhelming majority of path-steps sit
# near v ~ theta, where any reasonable compensator is correct. Version 4.0 froze the jump
# compensator at a representative sqrt(theta), which mis-signs it once the variance co-jumps push v
# far above theta, and the flat unconditional mean was read as proof that the compensator worked.
# It was not: the v4.0 mean rose 9bp on row 5 (the co-jump engine) and that was reported as noise.
# mean|DD10 is the column that sees it -- the bias was 41bp there. Keep it.
#
# Run:  python validation_heston.py
# ==============================================================================
import copy
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import cupy as cp
import DynamicPortfolioOptimizationFunc as d


def stressed_mean(paths, q=10):
    """
    Mean terminal return over the `q`% of paths with the deepest maximum drawdown.

    The conditional counterpart to the unconditional mean: a compensator whose error is confined to
    high-variance states leaves the unconditional mean flat and shows up here.
    """
    init, final = paths[:, 0], paths[:, -1]
    fret = (final - init) / init
    running_max = np.maximum.accumulate(paths, axis=1)
    mdd = ((paths - running_max) / running_max).min(axis=1)
    return float(fret[mdd <= np.percentile(mdd, q)].mean())


def cvar_cdar(paths, alpha=0.05):
    """CVaR and CDaR of portfolio value paths, shape (num_sims, steps+1)."""
    init, final = paths[:, 0], paths[:, -1]
    fret = (final - init) / init
    var = np.percentile(fret, alpha * 100)
    cvar = fret[fret <= var].mean()
    running_max = np.maximum.accumulate(paths, axis=1)
    dd = (paths[:, 1:] - running_max[:, 1:]) / running_max[:, 1:]
    flat = dd.ravel()
    dar = np.percentile(flat, alpha * 100)
    cdar = flat[flat <= dar].mean()
    return float(cvar), float(cdar), fret


def build_inputs(seed=0):
    """Real 5y weekly data through the actual pipeline -> drift, cov/corr forecasts, Heston cfg."""
    portfolio = ["PLTR", "NVDA", "META", "JPM", "GOOGL", "FERG", "BTC=F"]
    ret = d.ret_df(portfolio, period="5y", interval="1wk", mode="max_info", verbose=True)
    vix_shifted, future_vix = d.get_shifted_vix(period="5y", interval="1wk", shift=4)
    vol_models, std_resid_df = d.fit_garch_with_exog(ret, vix_shifted)
    cov_f, corr_f = d.forecast_dcc(ret, vol_models, std_resid_df, future_vix, steps=12)
    heston = d.calibrate_heston_params(vol_models, std_resid_df=std_resid_df)

    import yfinance as yf
    pdat = yf.download(portfolio, period="5d", progress=False)["Close"]
    S0 = [float(pdat[t].dropna().iloc[-1]) for t in portfolio]
    drift = np.full(len(portfolio), ((1 + 0.10) ** (1 / 52) - 1), dtype=float)
    return portfolio, S0, drift, cov_f, corr_f, heston


def main():
    np.random.seed(0)
    cp.random.seed(0)
    portfolio, S0, drift, cov_f, corr_f, heston = build_inputs()
    N = len(portfolio)
    w = np.full(N, 1.0 / N)
    M = 400000

    # Mild, realistic jump MAGNITUDE parameters (shape/scale/threshold/direction).
    # NB: jump ARRIVAL intensity is driven by the Hawkes lambda_inf below, not by this 'lambda'.
    jump_config = {
        "systematic":    {"lambda": 0.02, "prob_crash": 0.55, "crash_shape": 0.15,
                          "crash_scale": 0.5, "rally_shape": 0.12, "rally_scale": 0.5, "threshold": 3.0},
        "idiosyncratic": {"lambda": 0.015, "prob_crash": 0.55, "crash_shape": 0.15,
                          "crash_scale": 0.5, "rally_shape": 0.12, "rally_scale": 0.5, "threshold": 3.0},
    }
    # Hawkes intensity configs. lambda_inf = 0 disables arrivals entirely (pure diffusion).
    hawkes_zero = {"systematic": {"lambda_inf": 0.0, "alpha": 0.8, "beta": 0.0},
                   "idiosyncratic": {"lambda_inf": 0.0, "alpha": 0.8, "beta": 0.0}}
    hawkes_off = {"systematic": {"lambda_inf": 0.02, "alpha": 0.8, "beta": 0.0},
                  "idiosyncratic": {"lambda_inf": 0.015, "alpha": 0.8, "beta": 0.0}}
    hawkes_on = {"systematic": {"lambda_inf": 0.02, "alpha": 0.8, "beta": 0.15},
                 "idiosyncratic": {"lambda_inf": 0.015, "alpha": 0.8, "beta": 0.10}}

    base = dict(heston_config=heston, corr_matrices=corr_f, tickers=portfolio,
                scheme="full_trunc", use_gpu=True)
    ladder = [
        ("1. Legacy GBM",          None),
        ("2. Heston (no jumps)",   dict(hawkes_config=hawkes_zero, cojump_config={"var_jump_mult": 0.0}, **base)),
        ("3. + Bates jumps",       dict(hawkes_config=hawkes_off,  cojump_config={"var_jump_mult": 0.0}, **base)),
        ("4. + Hawkes clustering", dict(hawkes_config=hawkes_on,   cojump_config={"var_jump_mult": 0.0}, **base)),
        ("5. + Variance co-jumps", dict(hawkes_config=hawkes_on,   cojump_config={"var_jump_mult": 0.7}, **base)),
    ]

    print("\n" + "=" * 97)
    print(f"{'ENGINE':<26}{'mean_ret':>10}{'std':>9}{'CVaR5':>10}{'CDaR5':>10}{'exKurt':>9}{'mean|DD10':>11}")
    print("=" * 97)
    for name, sc in ladder:
        np.random.seed(7); cp.random.seed(7)  # common random numbers for a fair A/B
        kwargs = dict(sc) if sc is not None else {}
        paths, am, ac, raw = d.monte_carlo_simulation(
            S0, cov_f, M, drift, w, jump_config, return_paths=True, **kwargs)
        cvar, cdar, fret = cvar_cdar(paths)
        exk = float(pd.Series(np.log(paths[:, -1] / paths[:, 0])).kurt())
        sm = stressed_mean(paths)
        print(f"{name:<26}{fret.mean():>10.4f}{fret.std():>9.4f}{cvar:>10.4f}{cdar:>10.4f}"
              f"{exk:>9.2f}{sm:>11.4f}")
    print("=" * 97)
    print("Rows 3-5 all contain jumps: BOTH mean_ret and mean|DD10 should be flat across them.")
    print("mean_ret flat while mean|DD10 drifts => the compensator is wrong in the stressed states.")

    # CIR positivity / Feller diagnostics.
    print("\nCIR / Feller diagnostics (weekly units):")
    for t in portfolio:
        p = heston[t]
        feller = 2 * p["kappa"] * p["theta"] - p["xi"] ** 2
        print(f"   {t:<8} 2*kappa*theta - xi^2 = {feller:+.6f}  "
              f"({'Feller satisfied' if feller >= 0 else 'Feller violated (QE recommended)'})")
    print("\nVALIDATION COMPLETE.")


if __name__ == "__main__":
    main()
