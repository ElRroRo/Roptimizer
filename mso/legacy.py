"""v4.1 optimizer: SciPy differential evolution re-simulating every evaluation. Kept for the reference answer
and MainOptimization.py; v5.0 searches with mso.search on a scenario bank."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
from scipy.optimize import differential_evolution
from mso.xp import cp


from mso import metrics, sim


def run_optimization(initial_prices, forecasted_matrices, drift, rf_rate, num_assets, tickers, num_simulations_for_cvar,
                     n_iterations, jump_config, max_weight=1.0, alpha_cdar=0.05, cvar_floor=-0.50,
                     final_num_simulations=250000, popsize=25, tol=0.001, tau_mc=0.015, tau_prior=0.005, hhi_lambda=0.20,
                     sim_config=None):
    # --- DASHBOARD VISIBILITY ---
    sys_lam = jump_config['systematic']['lambda']
    idio_lam = jump_config['idiosyncratic']['lambda']
    print(f"\n[Jump Engine] Simulation initialized with Pareto Dynamics:")
    print(f"   >> Systematic Jump Freq: {sys_lam:.2%} per week")
    print(f"   >> Idiosyncratic Jump Freq: {idio_lam:.2%} per week")
    print(f"   >> Safety Floor: {cvar_floor:.2%} CVaR | Strategy: Best-1-Bin Evolution\n")

    bounds = tuple((0, max_weight) for _ in range(num_assets))

    # NOTE: We deliberately do NOT impose a sum-to-one NonlinearConstraint here. Differential
    # Evolution samples weight vectors in [0, max_weight]^N, which essentially never sum to ~1, so a
    # tight sum-to-one constraint would mark almost every candidate infeasible (DE prints f(x)=inf)
    # and cripple the search. Instead the objective `portfolio_cdar_objective` NORMALIZES the weights
    # internally (scale-invariant), and the winning vector is normalized again below -- so the simplex
    # constraint is enforced exactly without starving the optimizer.
    optimal_results = differential_evolution(
        metrics.portfolio_cdar_objective,
        bounds=bounds,
        args=(
            forecasted_matrices, initial_prices, drift, rf_rate, num_simulations_for_cvar,
            jump_config, alpha_cdar, cvar_floor, tau_mc, tau_prior, hhi_lambda, sim_config
        ),
        strategy='best1bin',
        maxiter=n_iterations,
        popsize=popsize,
        tol=tol,
        disp=True,
        polish=False,
    )

    raw_weights = optimal_results.x

    if np.sum(raw_weights) == 0:
        raw_weights = np.ones(num_assets) / num_assets
    normalized_weights = raw_weights / np.sum(raw_weights)

    # Simple Clip Loop for Constraint (Optional but good safety)
    for _ in range(5):
        if np.max(normalized_weights) <= max_weight + 0.01: break
        normalized_weights = np.clip(normalized_weights, 0, max_weight)
        normalized_weights /= np.sum(normalized_weights)

    # UPDATED: Run final sim with return_paths=True to get all reporting metrics
    final_simulated_paths, final_asset_means, final_asset_cov, raw_asset_returns = sim.monte_carlo_simulation(
        initial_prices, forecasted_matrices, final_num_simulations, drift,
        normalized_weights, jump_config, return_paths=True, **(sim_config or {})
    )

    cvar, expected_return, starr = metrics.get_portfolio_cvar_and_starr(
        final_simulated_paths, initial_prices, normalized_weights, rf_rate, drift,
        sigma_mc_12week=final_asset_cov,
        asset_returns_final=final_asset_means
    )

    std_dev = metrics.get_portfolio_std_dev(final_simulated_paths, initial_prices, normalized_weights)

    # --- CONSISTENCY CHECK: the simulator must reproduce the posterior return on average ---
    # A gap far beyond Monte Carlo noise means the drift, compensator or shock clip is wrong somewhere.
    v0_port = float(np.dot(initial_prices, normalized_weights))
    sim_terminal = final_simulated_paths[:, -1] / v0_port - 1
    sim_mean = float(np.mean(sim_terminal))
    se = float(np.std(sim_terminal) / np.sqrt(len(sim_terminal)))
    z_gap = (sim_mean - expected_return) / max(se, 1e-12)
    flag = "OK" if abs(z_gap) <= 4 else "MISMATCH - simulator does not reproduce the posterior return"
    print(f"\n[check] {len(forecasted_matrices)}-week return: posterior {expected_return:+.4f} | "
          f"simulated mean {sim_mean:+.4f} | gap {z_gap:+.1f} standard errors -> {flag}")
    
    # Compute CDaR metric for final reporting
    # transfer to GPU first
    # final_simulated_paths is already (num_sims, num_steps + 1), the layout compute_cdar_gpu expects.
    paths_gpu = cp.asarray(final_simulated_paths, dtype=cp.float32)
    cdar, _ = metrics.compute_cdar_gpu(paths_gpu, alpha=alpha_cdar)
    
    return normalized_weights, expected_return, std_dev, cvar, starr, final_simulated_paths, raw_asset_returns, cdar


V5_ONLY = ("posterior_annual", "posterior_cov")


def legacy_kwargs(inputs):
    """inputs without the fields only the v5.0 tree uses, for run_optimization."""
    return {k: v for k, v in inputs.items() if k not in V5_ONLY}
