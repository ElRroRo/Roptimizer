"""Risk and reward on simulated portfolio paths, and the v4.1 objective functions."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
from mso.xp import cp

from mso import sim


def compute_cdar_gpu(portfolio_paths_gpu, alpha=0.05):
    """
    Computes CDaR directly on the GPU using cupy.
    Input shape: (num_sims, num_steps + 1)
    """
    # 1. Compute Running Maximum across the time axis (axis=1)
    # cp.maximum.accumulate is not supported in CuPy, so we use a fast loop over the small time axis
    num_steps = portfolio_paths_gpu.shape[1]
    running_max = cp.zeros_like(portfolio_paths_gpu)
    running_max[:, 0] = portfolio_paths_gpu[:, 0]
    for t in range(1, num_steps):
        running_max[:, t] = cp.maximum(running_max[:, t-1], portfolio_paths_gpu[:, t])
    
    # 2. Compute Drawdowns (will be <= 0)
    # We ignore t=0 since DD is always 0 there
    drawdowns = (portfolio_paths_gpu[:, 1:] - running_max[:, 1:]) / running_max[:, 1:]
    
    # 3. One number per scenario: its MAXIMUM drawdown over the horizon (Chekhlov, Uryasev & Zabarankin).
    # (Pooling every path-week instead counted a fall that persists for 11 weeks 11 times.)
    max_dd = cp.min(drawdowns, axis=1)

    # 4. Drawdown-at-Risk: the alpha-quantile of the per-scenario maximum drawdowns
    dar_alpha = cp.percentile(max_dd, alpha * 100)

    # 5. CDaR: the mean maximum drawdown across the worst alpha share of scenarios
    cdar = cp.mean(max_dd[max_dd <= dar_alpha])
    
    # Optional: also compute terminal CVaR as a safety check floor
    initial_values = portfolio_paths_gpu[:, 0]
    final_values = portfolio_paths_gpu[:, -1]
    final_returns = (final_values - initial_values) / initial_values
    var_alpha = cp.percentile(final_returns, alpha * 100)
    cvar = cp.mean(final_returns[final_returns <= var_alpha])
    
    return float(cdar), float(cvar)

def get_portfolio_std_dev(simulated_portfolio_paths, initial_prices, weights):
    """
    Calculates the standard deviation of the final returns for a portfolio.
    """
    initial_portfolio_value = np.dot(initial_prices, weights)
    final_returns = (simulated_portfolio_paths[:, -1] - initial_portfolio_value) / initial_portfolio_value

    return np.std(final_returns)


def posterior_horizon_return(weights, drift_weekly, horizon_weeks=12):
    """Model-exact expected return of a buy-and-hold portfolio over `horizon_weeks`: sum_i w_i ((1+d_i)^H - 1),
    with d_i each asset's weekly posterior drift. The simulator is built (via the jump compensator) so that
    its simulated mean matches this; run_optimization checks that it does."""
    d = np.asarray(drift_weekly, dtype=float)
    return float(np.dot(np.asarray(weights, dtype=float), (1 + d) ** horizon_weeks - 1))


def get_portfolio_cvar_and_starr(simulated_portfolio_paths, initial_prices, weights, rf_rate_annual, drift_weekly_bl,
                                 sigma_mc_12week, asset_returns_final, alpha=0.05):
    """
    Calculates CVaR and STARR. Uses annualized Sigma_MC for Bayesian blending,
    with Tikhonov Regularization to prevent matrix inversion failures.

    UPDATED: Accepts pre-calculated asset_returns_final (vector) instead of calculating mean again.
    """
    # ---------------------------------------------------------------------
    # --- SETUP & CVaR CALCULATION ---
    # ---------------------------------------------------------------------
    initial_prices = np.array(initial_prices)

    initial_portfolio_value = np.dot(initial_prices, weights)
    final_returns_12week = (simulated_portfolio_paths[:, -1] - initial_portfolio_value) / initial_portfolio_value

    var_12week = np.percentile(final_returns_12week, alpha * 100)
    # ---------------------------------------------------------------------
    # --- RETURN & CVaR CALCULATION (Simplified) ---
    # ---------------------------------------------------------------------
    initial_prices = np.array(initial_prices)
    initial_portfolio_value = np.dot(initial_prices, weights)
    final_returns_12week = (simulated_portfolio_paths[:, -1] - initial_portfolio_value) / initial_portfolio_value

    # Terminal CVaR (12-week)
    var_12week = np.percentile(final_returns_12week, alpha * 100)
    cvar_12week = np.mean(final_returns_12week[final_returns_12week <= var_12week])

    # Expected Return over the 12-week simulation horizon (NOT annualized). All reported metrics are
    # kept on this single native horizon: CVaR/CDaR/drawdown cannot be soundly annualized under the
    # model's fat tails + jumps, so consistency beats a spurious annual scaling.
    # The posterior expected return, the same number the optimizer rewards (not the noisy simulated mean).
    horizon = simulated_portfolio_paths.shape[1] - 1
    expected_return_12week = posterior_horizon_return(weights, drift_weekly_bl, horizon)

    # ---------------------------------------------------------------------
    # --- STARR CALCULATION (Reporting Units) ---
    # ---------------------------------------------------------------------

    # Risk-free rate over the horizon, compounded the same way as in the objective
    rf_rate_12week = (1 + rf_rate_annual) ** (horizon / 52) - 1

    # STARR based on 12-week metrics
    starr_numerator = expected_return_12week - rf_rate_12week
    epsilon = 1e-10
    starr_denominator = np.maximum(abs(cvar_12week), epsilon)
    starr = starr_numerator / starr_denominator

    if not np.isfinite(starr) or cvar_12week >= 0:
        return np.inf, np.nan, np.inf

    return cvar_12week, expected_return_12week, starr


def portfolio_starr_objective(weights, forecasted_matrices, initial_prices, drift, rf_rate, num_simulations_for_cvar,
                              jump_config, sim_config=None):
    if np.sum(weights) == 0:
        return np.inf

    weights = weights / np.sum(weights)

    # UPDATED: We use '_' to ignore the new 4th output (raw_returns)
    # The optimizer doesn't need the raw data, only the metrics
    simulated_paths, asset_means, asset_cov, _ = sim.monte_carlo_simulation(
        initial_prices, forecasted_matrices, num_simulations_for_cvar, drift,
        weights, jump_config, **(sim_config or {})
    )

    cvar, expected_return, starr = get_portfolio_cvar_and_starr(
        simulated_paths, initial_prices, weights, rf_rate, drift,
        sigma_mc_12week=asset_cov,
        asset_returns_final=asset_means
    )

    return -starr


def portfolio_cdar_objective(weights, forecasted_matrices, initial_prices, drift, rf_rate, num_simulations_for_cvar,
                             jump_config, alpha_cdar=0.05, cvar_floor=-0.25, tau_mc=0.015, tau_prior=0.005, hhi_lambda=0.20,
                             sim_config=None):
    if np.sum(weights) == 0:
        return 1e6

    weights = weights / np.sum(weights)

    # Use optimization mode (return_paths=False) to minimize VRAM
    # Returns simulated_paths_gpu directly as a cp.ndarray
    # sim_config (optional) switches the legacy GBM engine to the Hybrid DCC-Heston-Bates engine.
    simulated_paths_gpu, asset_means_cpu, asset_cov_cpu, _ = sim.monte_carlo_simulation(
        initial_prices, forecasted_matrices, num_simulations_for_cvar, drift,
        weights, jump_config, return_paths=False, **(sim_config or {})
    )
    
    # We'll just compute CDaR natively on GPU
    cdar, terminal_cvar = compute_cdar_gpu(simulated_paths_gpu, alpha=alpha_cdar)

    # --- SOFT Ruin Threshold ---
    # The CVaR floor is a SOFT preference, not a hard rejection. If the best achievable portfolio
    # still breaches the floor (e.g. CVaR -41% against a -40% floor), we return it -- penalized in
    # proportion to the breach -- rather than truncating it to an infeasible sentinel. This guarantees
    # the optimizer always yields the BEST ATTAINABLE allocation, even when no portfolio fully
    # satisfies the floor. (The breach is folded into the objective at the end.)
    floor_breach = max(0.0, cvar_floor - terminal_cvar)  # > 0 only when CVaR is worse than the floor

    # Reward = the posterior (Black-Litterman) expected return of this buy-and-hold portfolio over the
    # simulated horizon: exact and noise-free. (It used to be a 75/25 blend with the simulated means, whose
    # matrix form reduced to that plain weighted average.) tau_mc / tau_prior are kept for call compatibility.
    expected_return_12week = posterior_horizon_return(weights, drift, len(forecasted_matrices))
    rf_rate_12week = ((1 + rf_rate) ** (len(forecasted_matrices) / 52)) - 1
    if not np.isfinite(expected_return_12week):
        return 1e6

    numerator = expected_return_12week - rf_rate_12week
    denominator = max(abs(cdar), 1e-10)
    
    upi_cdar = numerator / denominator
    
    # --- DIVERSIFICATION PENALTY (HHI) ---
    # Penalizes the sum of squared weights. 
    # High concentration in JPM (e.g. 0.6^2 = 0.36) is penalized much more than 
    # diversified weights (e.g. 10 stocks at 10% = 10 * 0.1^2 = 0.10).
    # Lambda of 0.20 provides a moderate push towards spreading.
    hhi_score = np.sum(weights**2)
    
    # We subtract the penalty from the UPI (Reward)
    final_objective_reward = upi_cdar - (hhi_lambda * hhi_score)

    if not np.isfinite(final_objective_reward) or cdar >= 0:
        # print(f"DEBUG: Invalid UPI: {upi_cdar}, cdar: {cdar}")
        return 1e6

    # Soft ruin-floor penalty: proportional to how far CVaR breaches the floor (0 if within it).
    # Gently prefers floor-satisfying portfolios but never rejects a breaching one outright, so a
    # higher-reward portfolio that slightly exceeds the threshold can still win -- the best attainable
    # outcome is always returned rather than truncated.
    FLOOR_PENALTY_WEIGHT = 5.0
    return -final_objective_reward + FLOOR_PENALTY_WEIGHT * floor_breach  # negative => maximize reward
