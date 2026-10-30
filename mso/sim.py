"""Monte Carlo simulators: the Heston-Bates engine with Hawkes jumps and co-jumps, and the legacy GBM engine."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
import pandas as pd
from mso.xp import cp

from mso.fits import _nearest_psd_corr


def _xp_rand(xp, shape):
    """Uniform(0,1) float32 array on the active backend (cupy or numpy)."""
    return xp.random.random(size=shape).astype(xp.float32)


def _xp_randn(xp, shape):
    """Standard-normal float32 array on the active backend (cupy or numpy)."""
    return xp.random.standard_normal(size=shape).astype(xp.float32)


def _corr_from_cov(cov):
    """Normalise a covariance matrix to a correlation matrix (numpy)."""
    d = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    R = cov / np.outer(d, d)
    R = (R + R.T) / 2.0
    np.fill_diagonal(R, 1.0)
    return R


def _layer_compensator(layer, s_repr, n_mc=20000, max_shock=8.0):
    """
    E[e^{J s} - 1 | a jump occurs] for one asymmetric-Pareto jump layer, evaluated at the
    per-asset volatility `s_repr` (array, shape (N,)). Kept for diagnostics and A/B work;
    the simulator uses `_compensator_grid` so the compensator can follow the STOCHASTIC
    sqrt(v_t) instead of a frozen representative volatility. Returns shape (N,).
    """
    c_c = max(float(layer['crash_shape']), 1e-6)
    c_r = max(float(layer['rally_shape']), 1e-6)
    thr = float(layer['threshold'])
    u1 = np.random.rand(n_mc)
    u2 = np.random.rand(n_mc)
    mag_c = np.clip(thr + (float(layer['crash_scale']) / c_c) * ((1 - u1) ** (-c_c) - 1), thr, max_shock)
    mag_r = np.clip(thr + (float(layer['rally_scale']) / c_r) * ((1 - u2) ** (-c_r) - 1), thr, max_shock)
    s = np.asarray(s_repr, dtype=float)[:, None]            # (N, 1)
    e_crash = np.exp(-mag_c[None, :] * s).mean(axis=1)      # (N,)
    e_rally = np.exp(mag_r[None, :] * s).mean(axis=1)       # (N,)
    p = float(layer['prob_crash'])
    return p * e_crash + (1 - p) * e_rally - 1.0


_COMP_GRID_CACHE = {}
SHOCK_CLIP = 5.0  # cap on one step's log shock (diffusion + jump), shared by the simulator and its compensator


def _compensator_grid(layer, s_max, n_grid=513, n_mc=200_000, max_shock=8.0, seed=20240617):
    """
    Tabulate g(s) = E[e^{J s} - 1 | a jump occurs] on a uniform grid s in [0, s_max].

    The jump size J is calibrated in Z-SCORE units (GPD fit to standardized GARCH residuals,
    `jump_paremeters.py`), so the quantity actually added to the log price is J*sqrt(v_t) and the
    martingale compensator at time t is lambda_t * g(sqrt(v_t)) -- the expectation must be taken
    over the same random variable that is injected. g is strongly convex in s and CHANGES SIGN
    (jumps are net-negative in calm states, net-positive once the Pareto rally tail dominates), so
    evaluating it once at a representative sqrt(theta) mis-signs the correction in exactly the
    high-variance states the Hawkes/co-jump machinery is built to produce.

    g is NOT monotone: it dips negative, bottoms out around 3% weekly vol and crosses back through
    zero near 5.5%, after which the rally tail makes it climb steeply. Common random numbers across
    the whole grid (fixed `seed`) keep it smooth in s despite that shape, and
    keep the table bit-identical between optimizer candidates -- a resampled compensator would
    inject fresh Monte-Carlo noise into every differential-evolution objective evaluation.
    `max_shock` must match the magnitude clip used in `gen_jumps`.

    Returns (ds, table) for a uniform grid starting at s = 0; table[k] = g(k*ds), float32.
    """
    c_c = max(float(layer['crash_shape']), 1e-6)
    c_r = max(float(layer['rally_shape']), 1e-6)
    thr = float(layer['threshold'])
    p = float(layer['prob_crash'])
    s_max = float(max(s_max, 1e-6))
    key = (c_c, c_r, thr, float(layer['crash_scale']), float(layer['rally_scale']), p,
           round(s_max, 9), n_grid, n_mc, max_shock, seed)
    hit = _COMP_GRID_CACHE.get(key)
    if hit is not None:
        return hit

    rng = np.random.default_rng(seed)
    u1 = rng.random(n_mc)
    u2 = rng.random(n_mc)
    mag_c = np.clip(thr + (float(layer['crash_scale']) / c_c) * ((1 - u1) ** (-c_c) - 1), thr, max_shock)
    mag_r = np.clip(thr + (float(layer['rally_scale']) / c_r) * ((1 - u2) ** (-c_r) - 1), thr, max_shock)

    s_grid = np.linspace(0.0, s_max, n_grid)
    table = np.empty(n_grid, dtype=np.float64)
    for lo in range(0, n_grid, 32):                          # chunked: (32, n_mc) at a time
        sl = s_grid[lo:lo + 32][:, None]
        # The simulator clips each step's log shock to [-SHOCK_CLIP, SHOCK_CLIP]; compensate the jump that
        # is actually injected, or high-vol states pay drift for rallies the clip removes (and exp overflows).
        e_crash = np.exp(np.clip(-mag_c[None, :] * sl, -SHOCK_CLIP, SHOCK_CLIP)).mean(axis=1)
        e_rally = np.exp(np.clip(mag_r[None, :] * sl, -SHOCK_CLIP, SHOCK_CLIP)).mean(axis=1)
        table[lo:lo + 32] = p * e_crash + (1 - p) * e_rally - 1.0
    table[0] = 0.0                                           # g(0) = 0 exactly: no vol, no jump

    out = (float(s_grid[1] - s_grid[0]), table.astype(np.float32))
    _COMP_GRID_CACHE[key] = out
    return out


def _beta_compensator(layer, b_crash, b_rally, sig_m, n_mc=200_000, max_shock=8.0, seed=20240617):
    """g[t, i] = E[e^{x} - 1 | a systematic jump], x the log shock asset i actually receives at step t:
    beta_crash_i * J * sig_m[t] for a crash, beta_rally_i * J * sig_m[t] for a rally, clipped to
    +/-SHOCK_CLIP as in the simulator. The same common random numbers as _compensator_grid. Returns (S, N)."""
    c_c = max(float(layer['crash_shape']), 1e-6)
    c_r = max(float(layer['rally_shape']), 1e-6)
    thr = float(layer['threshold'])
    p = float(layer['prob_crash'])
    rng = np.random.default_rng(seed)
    u1 = rng.random(n_mc)
    u2 = rng.random(n_mc)
    mag_c = np.clip(thr + (float(layer['crash_scale']) / c_c) * ((1 - u1) ** (-c_c) - 1), thr, max_shock)
    mag_r = np.clip(thr + (float(layer['rally_scale']) / c_r) * ((1 - u2) ** (-c_r) - 1), thr, max_shock)
    out = np.empty((len(sig_m), len(b_crash)))
    for t, s in enumerate(np.asarray(sig_m, dtype=float)):
        sc = (np.asarray(b_crash) * s)[:, None]
        sr = (np.asarray(b_rally) * s)[:, None]
        e_crash = np.exp(np.clip(-mag_c[None, :] * sc, -SHOCK_CLIP, SHOCK_CLIP)).mean(axis=1)
        e_rally = np.exp(np.clip(mag_r[None, :] * sr, -SHOCK_CLIP, SHOCK_CLIP)).mean(axis=1)
        out[t] = p * e_crash + (1 - p) * e_rally - 1.0
    return out


def _interp_uniform(xp, x, ds, table):
    """
    Linear interpolation of `table` (1-D, uniform grid starting at 0, spacing `ds`) at points `x`
    (any shape). Flat extrapolation past the top of the grid. Pure indexing, so it runs unchanged
    on numpy and cupy.
    """
    n = table.shape[0]
    pos = x / ds
    i0 = xp.clip(xp.floor(pos), 0, n - 2).astype(xp.int32)
    w = xp.clip(pos - i0, 0.0, 1.0)
    return table[i0] * (1.0 - w) + table[i0 + 1] * w


def monte_carlo_simulation(initial_prices, forecasted_matrices, num_simulations, drift, weights, jump_config,
                           heston_config=None, hawkes_config=None, cojump_config=None, corr_matrices=None,
                           tickers=None, scheme='full_trunc', dt=1.0, use_gpu=True, idio_jump_exclude=None,
                           vix_theta=None, return_paths=True, return_cum=False, jump_betas=None, market_vol=None,
                           cojump_mults=None):
    """
    GPU-accelerated Monte-Carlo simulation of future asset prices.

    Two engines, selected by `heston_config`:
      * heston_config is None  -> LEGACY engine: Euler GBM whose per-step variance is the
        deterministic DCC-GARCH forecast H_t, with memoryless Pareto jumps (original model).
      * heston_config provided  -> HYBRID DCC-HESTON-BATES engine:
          - per-asset variance is STOCHASTIC (CIR / Heston), calibrated via calibrate_heston_params;
          - cross-asset dependence uses the DCC CORRELATION R_t (corr_matrices), so DCC's
            time-varying correlation is preserved while variance comes from Heston;
          - each asset's price/variance Brownians are coupled by the leverage corr rho_i;
          - the existing asymmetric Pareto jumps are KEPT, scaled by stochastic sqrt(v_t),
            with SELF-EXCITING (Hawkes) arrival intensity (hawkes_config) so crashes cluster;
          - a CRASH triggers a variance CO-JUMP (SVJJ, cojump_config): vol spikes with the crash;
          - a martingale jump compensator removes the drift bias from asymmetric jumps.

    `scheme`: 'full_trunc' (full-truncation Euler, default, robust) or 'qe' (Andersen
    Quadratic-Exponential, more accurate variance tail under Feller violation).

    `idio_jump_exclude`: optional list of tickers that are EXEMPTED from idiosyncratic (non-systematic)
    jumps. Those assets still receive systematic shocks (and systematic-crash variance co-jumps), but no
    asset-specific Pareto jumps. Requires `tickers` to map names to rows.

    Uses float32 throughout. If return_paths=False, runs in low-VRAM 'optimization mode'.
    Output signature is unchanged: (portfolio_paths[num_sims, steps+1], asset_means, asset_cov, raw_returns).
    return_cum=True (Heston-Bates engine, with return_paths) instead returns each asset's cumulative return
    since t=0, on the device, shape (assets, steps, num_sims): what a scenario bank stores.
    """
    xp = cp if use_gpu else np
    if heston_config is not None:
        return _simulate_heston_bates(
            xp, initial_prices, forecasted_matrices, num_simulations, drift, weights, jump_config,
            heston_config, hawkes_config, cojump_config, corr_matrices, tickers, scheme, dt,
            idio_jump_exclude, vix_theta, return_paths, return_cum, jump_betas, market_vol, cojump_mults)
    if jump_betas is not None or cojump_mults is not None:
        raise ValueError("per-asset jump betas and co-jumps need the Heston-Bates engine (pass heston_config)")
    if return_cum:
        raise ValueError("return_cum needs the Heston-Bates engine (pass heston_config)")

    # --- Idiosyncratic-jump whitelist (legacy engine): 1.0 = jumps allowed, 0.0 = exempt ---
    num_assets = len(initial_prices)
    idio_jump_mask = cp.ones((num_assets, 1), dtype=cp.float32)
    if idio_jump_exclude and tickers is not None:
        ex = set(idio_jump_exclude)
        idio_jump_mask = cp.asarray(
            np.array([[0.0 if t in ex else 1.0] for t in tickers], dtype=np.float32))
    # Check for dimension compatibility
    num_assets = len(initial_prices)
    if not isinstance(drift, np.ndarray) or drift.shape != (num_assets,):
        raise ValueError(f"Drift must be a NumPy array with shape ({num_assets},), "
                         f"but got shape {np.asarray(drift).shape}.")

    if isinstance(forecasted_matrices, list) and all(isinstance(m, pd.DataFrame) for m in forecasted_matrices):
        forecasted_matrices = [m.values for m in forecasted_matrices]
    elif not all(isinstance(m, np.ndarray) for m in forecasted_matrices):
        raise TypeError("Input 'forecasted_matrices' must be a list of NumPy arrays or Pandas DataFrames.")

    num_steps = len(forecasted_matrices)

    # --- Transfer all data to the GPU (convert to float32 for VRAM savings) ---
    cp_initial_prices = cp.asarray(initial_prices, dtype=cp.float32)
    cp_forecasted_matrices = cp.asarray(forecasted_matrices, dtype=cp.float32)
    cp_drift = cp.asarray(drift, dtype=cp.float32)
    cp_weights = cp.asarray(weights, dtype=cp.float32)

    # Initialize container based on mode
    if return_paths:
        simulated_asset_prices = cp.zeros((num_assets, num_steps + 1, num_simulations), dtype=cp.float32)
        simulated_asset_prices[:, 0, :] = cp_initial_prices[:, cp.newaxis]
    else:
        # Optimization mode: only keep current step to save memory
        current_prices = cp.repeat(cp_initial_prices[:, cp.newaxis], num_simulations, axis=1)
        simulated_portfolio_paths = cp.zeros((num_steps + 1, num_simulations), dtype=cp.float32)
        initial_portfolio_value = cp.dot(cp_initial_prices, cp_weights)
        simulated_portfolio_paths[0, :] = initial_portfolio_value

    # --- FAT TAIL GENERATOR (float32) ---
    def generate_pareto_shocks(rows, cols, lam, p_crash, c_c, s_c, c_r, s_r, thresh, max_shock=8.0):
        # Truncation: 8.0 sigma is roughly a 25-35% weekly move. 
        # Anything larger is practically blocked by circuit breakers/market structure.
        
        has_jump = cp.random.rand(rows, cols, dtype=cp.float32) < lam
        is_crash = cp.random.rand(rows, cols, dtype=cp.float32) < p_crash
        u = cp.random.rand(rows, cols, dtype=cp.float32)

        epsilon = cp.float32(1e-6)
        c_c = max(c_c, epsilon)
        c_r = max(c_r, epsilon)

        # Generate Pareto magnitudes
        mag_crash = thresh + (s_c / c_c) * ((1 - u) ** (-c_c) - 1)
        mag_rally = thresh + (s_r / c_r) * ((1 - u) ** (-c_r) - 1)
        
        # Apply "Common Sense" Truncation (Clipping at max_shock sigma)
        mag_crash = cp.clip(mag_crash, thresh, max_shock)
        mag_rally = cp.clip(mag_rally, thresh, max_shock)

        jumps = cp.zeros((rows, cols), dtype=cp.float32)
        mask_c = has_jump & is_crash
        jumps[mask_c] = -mag_crash[mask_c]
        mask_r = has_jump & (~is_crash)
        jumps[mask_r] = mag_rally[mask_r]

        return jumps

    sys = jump_config['systematic']
    idio = jump_config['idiosyncratic']

    # --- TIME LOOP ---
    for t in range(num_steps):
        # Generate shocks for this step only (saves VRAM)
        z_step = cp.random.normal(size=(num_assets, num_simulations), dtype=cp.float32)
        
        covariance_matrix = cp_forecasted_matrices[t]

        # Volatility vector for Jump Scaling
        current_vol_vector = cp.sqrt(cp.diag(covariance_matrix))

        try:
            L = cp.linalg.cholesky(covariance_matrix)
        except cp.linalg.LinAlgError:
            L = None
        # CuPy does not raise on a non-PD matrix by default - it silently returns NaN.
        if L is None or cp.isnan(L).any():
            L = cp.diag(current_vol_vector)

        # Diffusion
        correlated_shocks = L @ z_step

        # Jumps (Z-Scores)
        sys_jumps = generate_pareto_shocks(1, num_simulations, sys['lambda'], sys['prob_crash'], sys['crash_shape'],
                                           sys['crash_scale'], sys['rally_shape'], sys['rally_scale'], sys['threshold'])
        idio_jumps = generate_pareto_shocks(num_assets, num_simulations, idio['lambda'], idio['prob_crash'],
                                            idio['crash_shape'], idio['crash_scale'], idio['rally_shape'],
                                            idio['rally_scale'], idio['threshold'])
        idio_jumps = idio_jumps * idio_jump_mask  # whitelist: exempt assets get zero idiosyncratic jumps

        # --- DRIFT CORRECTION (VOLATILITY DRAG) ---
        # Geometric Brownian Motion requires: log_drift = ln(1 + R_arithmetic) - 0.5 * sigma^2
        # This prevents the upward "compounding bias" in high-volatility assets.
        log_drift = cp.log(1 + cp_drift) - 0.5 * cp.diag(covariance_matrix)
        
        # Total Shock (Jumps scaled by Volatility)
        jump_return_impact = (sys_jumps + idio_jumps) * current_vol_vector[:, cp.newaxis]
        total_shock = correlated_shocks + jump_return_impact
        # Prevent numerical explosion (e.g. 10-sigma moves)
        total_shock = cp.clip(total_shock, -5.0, 5.0) 

        if return_paths:
            current_prices = simulated_asset_prices[:, t, :]
            next_prices = current_prices * cp.exp(log_drift[:, cp.newaxis] + total_shock)
            simulated_asset_prices[:, t + 1, :] = next_prices
        else:
            current_prices = current_prices * cp.exp(log_drift[:, cp.newaxis] + total_shock)
            # Store portfolio aggregate for this step
            step_portfolio_returns = cp.dot(cp_weights, (current_prices - cp_initial_prices[:, cp.newaxis]) / cp_initial_prices[:, cp.newaxis])
            simulated_portfolio_paths[t + 1, :] = initial_portfolio_value * (1 + step_portfolio_returns)

    # --- METRICS ---
    if return_paths:
        final_asset_prices = simulated_asset_prices[:, -1, :]
        initial_prices_expanded = simulated_asset_prices[:, 0, :]

        # THIS IS THE RAW ASSET DATA WE NEED
        total_asset_returns = (final_asset_prices - initial_prices_expanded) / initial_prices_expanded

        asset_means = cp.mean(total_asset_returns, axis=1)
        asset_cov = cp.cov(total_asset_returns)

        # Portfolio Calc
        # Buy-and-hold, matching the optimization path: V_t = V_0 * (1 + w . R_t).
        cum_returns = (simulated_asset_prices[:, 1:, :] - simulated_asset_prices[:, :1, :]) / simulated_asset_prices[:, :1, :]
        initial_portfolio_value = cp.dot(cp_initial_prices, cp_weights)
        simulated_portfolio_paths = initial_portfolio_value * (1 + cp.tensordot(cp_weights, cum_returns, axes=([0], [0])))
        simulated_portfolio_paths = cp.vstack(
            [cp.full(num_simulations, initial_portfolio_value, dtype=cp.float32), simulated_portfolio_paths])

        return (
            cp.asnumpy(simulated_portfolio_paths.T),
            cp.asnumpy(asset_means),
            cp.asnumpy(asset_cov),
            cp.asnumpy(total_asset_returns)
        )
    else:
        # Optimization mode: compute asset_means and cov efficiently
        total_asset_returns = (current_prices - cp_initial_prices[:, cp.newaxis]) / cp_initial_prices[:, cp.newaxis]
        asset_means = cp.mean(total_asset_returns, axis=1)
        asset_cov = cp.cov(total_asset_returns)
        
        # Return portfolio paths directly as cupy arrays for fast objective fn eval
        # (Transposed to shape [num_sims, num_steps+1] to match expected structure)
        return simulated_portfolio_paths.T, cp.asnumpy(asset_means), cp.asnumpy(asset_cov), None


def _simulate_heston_bates(xp, initial_prices, forecasted_matrices, num_simulations, drift, weights, jump_config,
                           heston_config, hawkes_config, cojump_config, corr_matrices, tickers, scheme, dt,
                           idio_jump_exclude=None, vix_theta=None, return_paths=True, return_cum=False,
                           jump_betas=None, market_vol=None, cojump_mults=None):
    """
    Hybrid DCC-Heston-Bates engine (see monte_carlo_simulation for the high-level description).
    Variance is stochastic (CIR), cross-asset dependence uses the DCC correlation R_t, jumps are
    self-exciting (Hawkes) and scaled by stochastic vol, crashes co-jump the variance (SVJJ), and a
    martingale compensator de-biases the drift. Output contract matches the legacy engine.

    Per-asset jump betas (jump database, #9), all optional; without them v4.1's behaviour is unchanged:
      jump_betas  {'crash': (N,), 'rally': (N,)}: a systematic jump J (S&P z-score units) hits asset i as
                  beta_i * J * market_vol[t], in log-return units, with the crash beta when J < 0 and the
                  rally beta when J > 0. Without it every asset takes J * its own sqrt(v_t) (loading 1).
      market_vol  (S,): the S&P 500's weekly volatility forecast over the horizon; required with jump_betas.
      cojump_mults (N,): each asset's own variance co-jump on a systematic crash, as a multiple of its
                  CURRENT variance (idiosyncratic crashes use the pooled var_jump_mult, also on current
                  variance). Without it every crash adds var_jump_mult x the long-run variance.
    """
    N = len(initial_prices)
    M = int(num_simulations)
    S = len(forecasted_matrices)
    drift = np.asarray(drift, dtype=float)
    if drift.shape != (N,):
        raise ValueError(f"Drift must have shape ({N},), got {drift.shape}.")
    sqrt_dt = float(np.sqrt(dt))
    f32 = xp.float32
    to_cpu = (lambda a: cp.asnumpy(a)) if xp is cp else (lambda a: np.asarray(a))

    # --- Forecast inputs: theta path (DCC/GARCH variance forecast) and correlation Choleskys ---
    H_list = [m.values if isinstance(m, pd.DataFrame) else np.asarray(m) for m in forecasted_matrices]
    theta_path = np.array([np.clip(np.diag(H), 1e-10, None) for H in H_list])  # (S, N)
    keys = list(tickers) if tickers is not None else list(heston_config.keys())

    # --- VIX-driven long-run-variance (theta) tilt (optional; exact no-op when vix_theta is None) ---
    # theta'_{i,t} = theta_{i,t} * clip( (VIX_now / VIX_bar) ** gamma_i , clip ), where the tilt decays
    # back to neutral across the horizon (only today's VIX is known). gamma_i = asset VIX elasticity.
    if vix_theta is not None:
        g = vix_theta.get('gamma', {})
        vix_now = float(vix_theta['vix_now'])
        vix_bar = max(float(vix_theta['vix_bar']), 1e-8)
        rho_decay = float(vix_theta.get('rho_decay', 0.3))
        clip_lo, clip_hi = vix_theta.get('clip', (0.5, 3.0))
        gam = np.array([float(g.get(k, 0.0)) if isinstance(g, dict) else float(g) for k in keys])
        ratio0 = np.clip((vix_now / vix_bar) ** gam, clip_lo, clip_hi)              # (N,)
        decay = np.exp(-rho_decay * np.arange(theta_path.shape[0]))[:, None]        # (S,1)
        ratio_path = np.clip(1.0 + (ratio0[None, :] - 1.0) * decay, clip_lo, clip_hi)  # (S,N)
        theta_path = theta_path * ratio_path

    theta_repr = theta_path.mean(axis=0)                                       # (N,)
    if corr_matrices is not None:
        R_list = [m.values if isinstance(m, pd.DataFrame) else np.asarray(m) for m in corr_matrices]
    else:
        R_list = [_corr_from_cov(H) for H in H_list]
    L_list = []
    for R in R_list:
        try:
            L = np.linalg.cholesky(R)
        except np.linalg.LinAlgError:
            L = np.linalg.cholesky(_nearest_psd_corr(R))
        L_list.append(L.astype(np.float32))

    # --- Per-asset Heston params (ticker order must match initial_prices / drift; keys set above) ---
    kappa = np.array([heston_config[k]['kappa'] for k in keys], dtype=np.float32)
    xi = np.array([heston_config[k]['xi'] for k in keys], dtype=np.float32)
    rho = np.array([heston_config[k]['rho'] for k in keys], dtype=np.float32)
    v0 = np.array([heston_config[k]['v0'] for k in keys], dtype=np.float32)

    # --- Idiosyncratic-jump whitelist: exempt assets get no asset-specific jumps/co-jumps ---
    ex = set(idio_jump_exclude or [])
    idio_mask_np = np.array([[0.0 if k in ex else 1.0] for k in keys], dtype=np.float32)  # (N,1)
    idio_mask_c = xp.asarray(idio_mask_np)
    idio_mask_bool = idio_mask_c > 0

    # --- Hawkes & co-jump configs (fall back to memoryless Poisson when absent) ---
    hk = hawkes_config or {}
    hk_sys = hk.get('systematic', {'lambda_inf': jump_config['systematic']['lambda'], 'alpha': 1.0, 'beta': 0.0})
    hk_idio = hk.get('idiosyncratic', {'lambda_inf': jump_config['idiosyncratic']['lambda'], 'alpha': 1.0, 'beta': 0.0})
    e_sys, e_idio = float(np.exp(-hk_sys['alpha'])), float(np.exp(-hk_idio['alpha']))
    binf_sys, binf_idio = float(hk_sys['lambda_inf']), float(hk_idio['lambda_inf'])
    beta_sys, beta_idio = float(hk_sys['beta']), float(hk_idio['beta'])
    var_jump_mult = float((cojump_config or {}).get('var_jump_mult', 1.0))
    if jump_betas is not None:
        if market_vol is None or len(market_vol) != S:
            raise ValueError(f"jump_betas need market_vol with one value per step ({S})")
        b_crash = np.asarray(jump_betas['crash'], dtype=float)
        b_rally = np.asarray(jump_betas['rally'], dtype=float)
        if b_crash.shape != (N,) or b_rally.shape != (N,):
            raise ValueError(f"jump_betas must have one crash and one rally beta per asset ({N})")
        sig_m = np.asarray(market_vol, dtype=float)
        comp_beta_sys = _beta_compensator(jump_config['systematic'], b_crash, b_rally, sig_m)   # (S, N)
        b_crash_c = xp.asarray(b_crash.astype(np.float32))[:, None]
        b_rally_c = xp.asarray(b_rally.astype(np.float32))[:, None]
    if cojump_mults is not None:
        cj = np.asarray(cojump_mults, dtype=np.float32)
        if cj.shape != (N,):
            raise ValueError(f"cojump_mults must have one value per asset ({N})")
        cojump_c = xp.asarray(cj)[:, None]

    # --- Martingale jump compensator: g(s) = E[e^{J s} - 1 | jump], tabulated in s = sqrt(v) ---
    # The jump injected into the log price is J*sqrt(v_t), so the compensator must be evaluated at
    # the CURRENT stochastic sqrt(v_t), not at a frozen representative vol. Grid top is sized to
    # cover the variance co-jump tail (v can reach a large multiple of theta after a crash); values
    # above it get flat extrapolation.
    s_ceiling = float(max(12.0 * np.sqrt(max(theta_path.max(), v0.max())), 0.2))
    comp_ds_sys, comp_tab_sys = _compensator_grid(jump_config['systematic'], s_ceiling)
    comp_ds_idio, comp_tab_idio = _compensator_grid(jump_config['idiosyncratic'], s_ceiling)

    # --- Push constants to the active backend as (N,1) column vectors ---
    kappa_c = xp.asarray(kappa)[:, None]
    xi_c = xp.asarray(xi)[:, None]
    rho_c = xp.asarray(rho)[:, None]
    comp_tab_sys_c = xp.asarray(comp_tab_sys)
    comp_tab_idio_c = xp.asarray(comp_tab_idio)
    theta_repr_c = xp.asarray(theta_repr.astype(np.float32))[:, None]
    log1p_c = xp.asarray(np.log1p(drift).astype(np.float32))[:, None]
    cp_initial_prices = xp.asarray(np.asarray(initial_prices, dtype=np.float32))
    cp_weights = xp.asarray(np.asarray(weights, dtype=np.float32))

    sysL, idioL = jump_config['systematic'], jump_config['idiosyncratic']

    def gen_jumps(shape, layer, lam):
        """Asymmetric truncated-Pareto jump (z-score units). lam may be scalar or broadcastable array.
        Returns (jumps, occurred_mask, crash_mask)."""
        occurred = _xp_rand(xp, shape) < lam
        is_crash = _xp_rand(xp, shape) < float(layer['prob_crash'])
        u = xp.clip(_xp_rand(xp, shape), 1e-7, 1.0)
        c_c = max(float(layer['crash_shape']), 1e-6)
        c_r = max(float(layer['rally_shape']), 1e-6)
        thr = float(layer['threshold'])
        mag_c = xp.clip(thr + (float(layer['crash_scale']) / c_c) * ((1 - u) ** (-c_c) - 1), thr, 8.0)
        mag_r = xp.clip(thr + (float(layer['rally_scale']) / c_r) * ((1 - u) ** (-c_r) - 1), thr, 8.0)
        zeros = xp.zeros(shape, dtype=f32)
        mask_c = occurred & is_crash
        mask_r = occurred & (~is_crash)
        jumps = xp.where(mask_c, -mag_c, zeros)
        jumps = xp.where(mask_r, mag_r, jumps).astype(f32)
        return jumps, occurred, mask_c

    def qe_variance_step(v_pos, theta_t, Zv, psi_c=1.5):
        """Andersen Quadratic-Exponential CIR step (leverage enters the psi<=psi_c branch via Zv)."""
        e = xp.exp(-kappa_c * dt)
        m = theta_t + (v_pos - theta_t) * e
        m = xp.maximum(m, 1e-12)
        s2 = (v_pos * xi_c ** 2 * e * (1 - e) / kappa_c
              + theta_t * xi_c ** 2 * (1 - e) ** 2 / (2 * kappa_c))
        psi = s2 / (m ** 2)
        # Branch 1 (psi <= psi_c): quadratic
        inv_psi = 1.0 / xp.maximum(psi, 1e-12)
        b2 = xp.maximum(2 * inv_psi - 1 + xp.sqrt(2 * inv_psi) * xp.sqrt(xp.maximum(2 * inv_psi - 1, 0.0)), 0.0)
        a = m / (1 + b2)
        v1 = a * (xp.sqrt(b2) + Zv) ** 2
        # Branch 2 (psi > psi_c): exponential
        p = (psi - 1) / (psi + 1)
        bbeta = (1 - p) / m
        U = _xp_rand(xp, v_pos.shape)
        v2 = xp.where(U <= p, xp.zeros_like(m), xp.log((1 - p) / xp.maximum(1 - U, 1e-12)) / xp.maximum(bbeta, 1e-12))
        return xp.where(psi <= psi_c, v1, v2).astype(f32)

    # --- State ---
    v = (xp.asarray(v0)[:, None] * xp.ones((1, M), dtype=f32)).astype(f32)
    lam_sys = xp.full((1, M), binf_sys, dtype=f32)
    lam_idio = xp.full((N, M), binf_idio, dtype=f32)

    if return_paths:
        prices = xp.zeros((N, S + 1, M), dtype=f32)
        prices[:, 0, :] = cp_initial_prices[:, None]
    else:
        current_prices = cp_initial_prices[:, None] * xp.ones((1, M), dtype=f32)
        portfolio_paths = xp.zeros((S + 1, M), dtype=f32)
        initial_portfolio_value = xp.dot(cp_initial_prices, cp_weights)
        portfolio_paths[0, :] = initial_portfolio_value

    # --- Time loop ---
    for t in range(S):
        Lt = xp.asarray(L_list[t])
        theta_t = xp.asarray(theta_path[t].astype(np.float32))[:, None]

        eps = _xp_randn(xp, (N, M))
        Zs = Lt @ eps                                              # correlated unit-variance price shocks
        eta = _xp_randn(xp, (N, M))
        Zv = rho_c * Zs + xp.sqrt(xp.maximum(1 - rho_c ** 2, 0.0)) * eta   # leverage-correlated variance shock

        v_pos = xp.maximum(v, 0.0)
        sqrt_v = xp.sqrt(v_pos)

        sys_jumps, sys_occ, sys_crash = gen_jumps((1, M), sysL, lam_sys)
        idio_jumps, idio_occ, idio_crash = gen_jumps((N, M), idioL, lam_idio)
        # Whitelist: zero out idiosyncratic jumps (and their occurrences/crashes) for exempt assets.
        idio_jumps = idio_jumps * idio_mask_c
        idio_occ = idio_occ & idio_mask_bool
        idio_crash = idio_crash & idio_mask_bool

        # J is a z-score; sqrt(v_t) turns it into a log return. Implicit reference horizon tau = 1
        # week (the interval the jump law was fitted over), so no sqrt(dt) here -- jump SIZE does
        # not scale with the integration step, unlike the diffusion below.
        if jump_betas is None:
            jump_impact = (sys_jumps + idio_jumps) * sqrt_v
        else:
            loading = xp.where(sys_jumps < 0, b_crash_c, b_rally_c)                  # (N, M)
            jump_impact = loading * sys_jumps * f32(sig_m[t]) + idio_jumps * sqrt_v
        diffusion = sqrt_v * sqrt_dt * Zs
        # Jump compensator: state-dependent (follows sqrt(v_t)) and time-varying (Hawkes lambda_t).
        # The idiosyncratic leg is masked so whitelisted assets are not compensated for jumps they
        # never receive.
        if jump_betas is None:
            g_sys = _interp_uniform(xp, sqrt_v, comp_ds_sys, comp_tab_sys_c)
        else:
            g_sys = xp.asarray(comp_beta_sys[t].astype(np.float32))[:, None]          # deterministic per step
        g_idio = _interp_uniform(xp, sqrt_v, comp_ds_idio, comp_tab_idio_c) * idio_mask_c
        comp = lam_sys * g_sys + lam_idio * g_idio
        log_drift = log1p_c - 0.5 * v_pos * dt - comp * dt
        total_shock = xp.clip(diffusion + jump_impact, -SHOCK_CLIP, SHOCK_CLIP)
        log_ret = log_drift + total_shock

        if return_paths:
            prices[:, t + 1, :] = (prices[:, t, :] * xp.exp(log_ret)).astype(f32)
        else:
            current_prices = (current_prices * xp.exp(log_ret)).astype(f32)
            step_ret = xp.dot(cp_weights, (current_prices - cp_initial_prices[:, None]) / cp_initial_prices[:, None])
            portfolio_paths[t + 1, :] = initial_portfolio_value * (1 + step_ret)

        # Variance update (CIR), then variance co-jump on crashes (SVJJ)
        if scheme == 'qe':
            v_new = qe_variance_step(v_pos, theta_t, Zv)
        else:
            v_new = v + kappa_c * (theta_t - v_pos) * dt + xi_c * sqrt_v * sqrt_dt * Zv
        crash_any = sys_crash | idio_crash
        if cojump_mults is None:
            var_cojump = (-xp.log(xp.clip(_xp_rand(xp, (N, M)), 1e-12, 1.0)) * var_jump_mult) * theta_repr_c
            v_new = v_new + xp.where(crash_any, var_cojump.astype(f32), xp.zeros((N, M), dtype=f32))
        else:
            # Own multiple on a systematic crash, the pooled one on an idiosyncratic-only crash; both on the
            # asset's current variance (#9).
            mult = xp.where(sys_crash, cojump_c, f32(var_jump_mult))
            var_cojump = -xp.log(xp.clip(_xp_rand(xp, (N, M)), 1e-12, 1.0)) * mult * v_pos
            v_new = v_new + xp.where(crash_any, var_cojump.astype(f32), xp.zeros((N, M), dtype=f32))
        v = v_new

        # Hawkes intensity update for next step
        lam_sys = xp.clip(binf_sys + (lam_sys - binf_sys) * e_sys + beta_sys * sys_occ.astype(f32), 0.0, 0.999)
        lam_idio = xp.clip(binf_idio + (lam_idio - binf_idio) * e_idio + beta_idio * idio_occ.astype(f32), 0.0, 0.999)

    # --- Metrics (identical contract to the legacy engine) ---
    if return_paths:
        final_prices = prices[:, -1, :]
        init_expanded = prices[:, 0, :]
        total_asset_returns = (final_prices - init_expanded) / init_expanded
        asset_means = xp.mean(total_asset_returns, axis=1)
        asset_cov = xp.cov(total_asset_returns)
        # Buy-and-hold, the same definition the optimization path scores: V_t = V_0 * (1 + w . R_t),
        # where R_t is each asset's cumulative return since t=0 (not weekly-rebalanced compounding).
        cum_returns = (prices[:, 1:, :] - prices[:, :1, :]) / prices[:, :1, :]
        if return_cum:
            return cum_returns
        initial_portfolio_value = xp.dot(cp_initial_prices, cp_weights)
        portfolio_paths = initial_portfolio_value * (1 + xp.tensordot(cp_weights, cum_returns, axes=([0], [0])))
        portfolio_paths = xp.vstack(
            [xp.full(M, initial_portfolio_value, dtype=f32), portfolio_paths])
        return (to_cpu(portfolio_paths.T), to_cpu(asset_means), to_cpu(asset_cov), to_cpu(total_asset_returns))
    else:
        total_asset_returns = (current_prices - cp_initial_prices[:, None]) / cp_initial_prices[:, None]
        asset_means = xp.mean(total_asset_returns, axis=1)
        asset_cov = xp.cov(total_asset_returns)
        return portfolio_paths.T, to_cpu(asset_means), to_cpu(asset_cov), None
