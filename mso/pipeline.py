"""From a portfolio CSV to the optimizer's inputs: downloads, GARCH/GJR-X, DCC, Heston, VIX tilt,
Black-Litterman, jump configs and the risk-free rate.

The result is a dict of run_optimization's arguments (minus the run settings), the same shape a
benchmarks/ snapshot stores, so a live build and a frozen snapshot feed the engine identically.
"""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================
import json
import os

import numpy as np
import pandas as pd
from mso import betas, cache, jumpdb
from mso import portfolio as pf
from mso.views import model_view
from mso.bl import black_litterman_mod, create_black_litterman_views
from mso.data import drop_incomplete_week, get_shifted_vix, history, last_prices, ret_df
from mso.fits import calibrate_heston_params, calibrate_vix_betas, fit_garch_with_exog, forecast_dcc

# Lightweight jump configs used only in QUICK mode (avoids importing jump_paremeters, which downloads
# ~100 tickers and re-calibrates at import time). Production uses the calibrated values from that module.
QUICK_JUMP_CONFIG = {
    "systematic":    {"lambda": 0.012, "prob_crash": 0.55, "crash_shape": 0.12, "crash_scale": 0.4,
                      "rally_shape": 0.10, "rally_scale": 0.4, "threshold": 3.0},
    "idiosyncratic": {"lambda": 0.010, "prob_crash": 0.55, "crash_shape": 0.12, "crash_scale": 0.4,
                      "rally_shape": 0.10, "rally_scale": 0.4, "threshold": 3.0},
}
QUICK_HAWKES_CONFIG = {"systematic": {"lambda_inf": 0.012, "alpha": 0.8, "beta": 0.08},
                       "idiosyncratic": {"lambda_inf": 0.010, "alpha": 0.8, "beta": 0.05}}
QUICK_COJUMP_CONFIG = {"var_jump_mult": 0.4}


class InputsError(RuntimeError):
    """The inputs cannot be built (e.g. the DCC forecast is not finite)."""


def read_portfolio_csv(path):
    """tickers, equilibrium returns, views, view sds and the idiosyncratic-jump exemptions of a v4.1 CSV."""
    df_input = pd.read_csv(path)
    portfolio = df_input['ticker'].tolist()
    equilibrium_returns = df_input['equilibrium_return'].tolist()
    analyst_views = {row['ticker']: (None if pd.isna(row['analyst_view']) else row['analyst_view']) for _, row in df_input.iterrows()}
    view_volatility = {row['ticker']: (None if pd.isna(row['view_volatility']) else row['view_volatility']) for _, row in df_input.iterrows()}

    # Optional whitelist: tickers exempted from IDIOSYNCRATIC (non-systematic) jumps.
    # Add a truthy 'exclude_idio_jump' column to portfolio_data.csv to flag them. These assets still
    # receive systematic shocks (and systematic-crash variance co-jumps), just no asset-specific jumps.
    if 'exclude_idio_jump' in df_input.columns:
        # A column with blanks is read as float, so a flagged cell arrives as 1.0, not '1'.
        _truthy = {'1', '1.0', 'true', 'yes', 'y', 't'}
        idio_jump_exclude = [r['ticker'] for _, r in df_input.iterrows()
                             if str(r['exclude_idio_jump']).strip().lower() in _truthy]
    else:
        idio_jump_exclude = []
    return portfolio, equilibrium_returns, analyst_views, view_volatility, idio_jump_exclude


def load_portfolio(source):
    """A portfolio dict from a dict, a portfolio JSON path or a v4.1 CSV path (imported flat)."""
    if isinstance(source, dict):
        return source
    if str(source).lower().endswith(".csv"):
        return pf.from_csv(str(source))
    with open(source) as f:
        return json.load(f)


def build_inputs(source='portfolio_data.csv', quick=False, jump_version="latest", day_cache=None, rf_rate=None):
    """Returns (inputs, record). source is a portfolio (dict or JSON path) or a v4.1 CSV. inputs holds run_optimization's arguments except num_simulations_for_cvar,
    n_iterations and popsize. record holds the return panel's first and last week, the market-data day and
    download time, the jump version used and the per-asset beta table.

    Every download goes through the day cache (a new DayCache for today unless one is passed). quick uses
    lightweight jump configs and loading-1 jumps; otherwise the jump database version `jump_version`
    supplies the configs and each asset's crash/rally betas and co-jump. rf_rate overrides ^TNX; without
    it a failed ^TNX fetch raises (v4.1 silently used 4.2%). Anything in mso.portfolio.blockers stops the
    build, naming the asset or subportfolio. Besides run_optimization's arguments, inputs carries the
    posterior returns and their uncertainty M (annual), which the tree needs."""
    c = cache.use(day_cache or cache.DayCache())
    print(f"\nMarket data: day cache {c.day} ({len(c.index)} series already cached)")
    print("\nLoading portfolio data...")
    port = load_portfolio(source)
    portfolio = pf.tickers(port)
    found = pf.blockers(port)
    if found:
        raise InputsError("the portfolio cannot run:\n  - " + "\n  - ".join(found))
    A = port["assets"]
    equilibrium_returns = [A[t]["equilibrium"] for t in portfolio]
    idio_jump_exclude = [t for t in portfolio if A[t].get("exclude_idio_jump")]
    if rf_rate is None and port.get("run", {}).get("rf") is not None:
        rf_rate = port["run"]["rf"]
    if jump_version in (None, "latest"):
        jump_version = port.get("run", {}).get("jump_version") or "latest"
    if idio_jump_exclude:
        print(f"Idiosyncratic-jump whitelist (systematic-only assets): {idio_jump_exclude}")

    print("Fetching historical returns and VIX data...")
    # mode='max_info' keeps each asset's FULL history so a young IPO or a different-calendar
    # asset (e.g. BTC=F) no longer collapses the panel; do NOT chain .dropna() here.
    port_ret = ret_df(portfolio, period='5y', interval='1wk', mode='max_info')
    print(f"Return panel shape (rows x assets): {port_ret.shape}")
    record = dict(last_return_week=str(port_ret.index.max()), first_return_week=str(port_ret.index.min()))
    vix_shifted, future_vix = get_shifted_vix(period='5y', interval='1wk', shift=4)

    # --- 2. FORECASTING (DCC-GARCH-X) ---
    print("\nFitting GARCH-X and forecasting DCC matrices...")
    model_vols, std_resid_df = fit_garch_with_exog(port_ret, vix_shifted, p_val=False)
    horizon = int((port.get("run") or {}).get("horizon_weeks") or 12)   # run-wide horizon, weeks (#7)
    DCC_forecast, DCC_corr = forecast_dcc(port_ret, vol_models=model_vols, std_resid_df=std_resid_df,
                                          future_vix=future_vix, steps=horizon)

    # SAFETY CHECK: Ensure DCC matrices are finite
    if any(not np.isfinite(m.values).all() for m in DCC_forecast):
        raise InputsError("DCC forecasting produced NaNs or Infs. Data might be too noisy or short.")

    # --- 2b. HESTON (STOCHASTIC VARIANCE) CALIBRATION ---
    # Reuse the already-fitted GARCH to calibrate per-asset CIR variance params (P-measure).
    heston_config = calibrate_heston_params(model_vols, std_resid_df=std_resid_df)

    # --- 2c. VIX -> HESTON LONG-RUN VARIANCE (theta) TILT ---
    # VIX enters the model here (NOT via arch's mean-x, which it silently drops): it tilts each asset's
    # long-run variance target up/down by how elevated VIX is vs its own history, fading over the horizon.
    # Complete weeks only, to line up with the return panel; vix_now below stays the live level.
    # A failure raises: v4.1 printed a warning and quietly ran without the tilt.
    vix_weekly = drop_incomplete_week(history("^VIX", '5y', '1wk'))
    vix_weekly.index = pd.to_datetime(vix_weekly.index).date
    vix_full = history("^VIX", 'max', '1wk')
    vix_now = float(vix_full.iloc[-1])
    vix_bar = float(vix_full.median())
    vix_gamma = calibrate_vix_betas(model_vols, vix_weekly)
    vix_theta = dict(vix_now=vix_now, vix_bar=vix_bar, gamma=vix_gamma,
                     rho_decay=0.3, clip=(0.5, 3.0))
    print(f"VIX-theta tilt active: VIX_now={vix_now:.2f} vs median={vix_bar:.2f} "
          f"(ratio={vix_now/vix_bar:.3f})")

    # --- 3. BLACK-LITTERMAN VIEWS ---
    # Prices first: a target-price view, or an uncertainty in dollars, is converted at today's price (#14).
    print("\nDownloading initial prices...")
    initial_prices = last_prices(portfolio)
    print(f"Initial Prices: {dict(zip(portfolio, [f'{p:.2f}' for p in initial_prices]))}")
    price = dict(zip(portfolio, initial_prices))
    analyst_views, view_volatility, most_likely = {}, {}, {}
    for t in portfolio:
        if A[t].get("view"):
            analyst_views[t], view_volatility[t], most_likely[t] = model_view(A[t]["view"], price[t])

    print("\nApplying Black-Litterman views...")
    p, q, view_variance = create_black_litterman_views(portfolio, analyst_views=analyst_views, view_stdevs=view_volatility)
    sigma = DCC_forecast[-1] * 52
    expected_returns, posterior_cov = black_litterman_mod(portfolio=portfolio, sigma=sigma, p=p, q=q,
                                                          equilibrium_ret=equilibrium_returns,
                                                          view_variances=view_variance, return_cov=True)

    # Posterior next to its inputs, so a view's pull (and any spillover onto no-view assets) is visible.
    print(f"  {'ticker':<7} {'equilibrium':>11} {'view':>9} {'view sd':>8} {'posterior':>10}")
    for n, r in enumerate(expected_returns):
        t = portfolio[n]
        v, sd = analyst_views.get(t), view_volatility.get(t)
        v_s = f"{v:+9.1%}" if v is not None else f"{'-':>9}"
        sd_s = f"{sd:8.1%}" if v is not None else f"{'-':>8}"
        lop = (f"   (most likely {most_likely[t]:+.1%} -> model uses {v:+.1%})"
               if v is not None and abs(most_likely[t] - v) > 5e-4 else "")
        print(f"  {t:<7} {float(equilibrium_returns[n]):+11.1%} {v_s} {sd_s} {r:+10.1%}{lop}")

    weekly_returns = ((1 + expected_returns)**(1/52)) - 1
    # Sanitize weekly returns to prevent log(0) or log(negative) in MC
    weekly_returns = np.clip(weekly_returns, -0.15, 0.15)
    print(f"Sanitized Weekly Drift range: [{weekly_returns.min():.4f}, {weekly_returns.max():.4f}]")


    # Target parameters
    cvar_floor = float(os.environ.get('OPT_CVAR_FLOOR', -0.40))  # SOFT max-loss preference (not a hard reject)
    alpha_cdar = 0.05   # Confidence level

    # Jump / Hawkes / co-jump configs: calibrated (production) or lightweight defaults (QUICK).
    beta_kwargs = {}
    if quick:
        print("\n[QUICK MODE] Using default jump configs and loading-1 jumps (no jump database).")
        jump_config_scaled = QUICK_JUMP_CONFIG
        hawkes_cfg, cojump_cfg = QUICK_HAWKES_CONFIG, QUICK_COJUMP_CONFIG
        record["jump_version"] = None
    else:
        v = jumpdb.load(jump_version)
        print(f"\nJump database version {v['version']} ({v['age_days']} days old"
              f"{', STALE: older than 90 days, recalibrate' if v['stale'] else ''})")
        jump_config_scaled = v["jump_config"]
        hawkes_cfg, cojump_cfg = v["hawkes_config"], v["cojump_config"]
        print("Per-asset jump betas and variance co-jumps (S&P surprise days, daily):")
        table = betas.ticker_table(portfolio, v, c)
        betas.print_table(table)
        steps = len(DCC_forecast)
        beta_kwargs = dict(jump_betas=dict(crash=[table[t]["crash_beta"] for t in portfolio],
                                           rally=[table[t]["rally_beta"] for t in portfolio]),
                           cojump_mults=[table[t]["cojump"] for t in portfolio],
                           market_vol=betas.market_vol_path(c, steps))
        print(f"S&P weekly volatility over the horizon: {beta_kwargs['market_vol'][0]:.2%} -> "
              f"{beta_kwargs['market_vol'][-1]:.2%}")
        record.update(jump_version=v["version"], jump_stale=v["stale"], betas=table)

    # --- HYBRID DCC-HESTON-BATES SIMULATOR CONFIG ---
    # Switches the simulator from legacy GBM to stochastic-variance (Heston) + self-exciting
    # (Hawkes) jumps + variance co-jumps, while keeping DCC correlation R_t for cross-asset moves.
    sim_config = dict(
        heston_config=heston_config,
        hawkes_config=hawkes_cfg,
        cojump_config=cojump_cfg,
        corr_matrices=DCC_corr,
        tickers=portfolio,
        scheme='full_trunc',   # 'qe' for Andersen Quadratic-Exponential CIR discretization
        use_gpu=True,
        idio_jump_exclude=idio_jump_exclude,
        vix_theta=vix_theta,
        **beta_kwargs,
    )

    if rf_rate is not None:
        risk_free_rate = float(rf_rate)
        print(f"Risk-free rate set by hand: {risk_free_rate:.3%}")
    else:
        # Last closing 10-year yield. A failed fetch raises: v4.1 silently used 4.2%.
        try:
            risk_free_rate = c.last_price("^TNX")[0] / 100
        except Exception as e:
            raise InputsError(f"could not fetch ^TNX for the risk-free rate ({e}); set it by hand") from e
        print(f"Risk-free rate (^TNX): {risk_free_rate:.3%}")

    inputs = dict(initial_prices=initial_prices, forecasted_matrices=DCC_forecast, drift=weekly_returns,
                  rf_rate=risk_free_rate, num_assets=len(portfolio), tickers=portfolio,
                  jump_config=jump_config_scaled, alpha_cdar=alpha_cdar, cvar_floor=cvar_floor,
                  sim_config=sim_config, posterior_annual=[float(x) for x in expected_returns],
                  posterior_cov=np.asarray(posterior_cov, dtype=float).tolist())
    record.update(data_day=c.day, data_downloaded=c.downloaded_at(), downloads_this_build=len(c.misses))
    return inputs, record
