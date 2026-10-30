"""Fits on the return panel: GARCH/GJR-X, DCC correlations, Heston variance and VIX betas."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.stats import norm, jarque_bera
from scipy.optimize import minimize
from arch import arch_model
import matplotlib.pyplot as plt


def _nearest_psd_corr(corr, epsilon=1e-8):
    """
    Project a (possibly pairwise-estimated / NaN-holed) matrix onto the nearest
    positive-semidefinite *correlation* matrix via eigenvalue clipping. This guarantees
    a usable Cholesky factor downstream even when the correlation target was assembled
    from assets with non-overlapping histories.
    """
    corr = np.asarray(corr, dtype=float)
    corr = np.nan_to_num(corr, nan=0.0)
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    vals, vecs = np.linalg.eigh(corr)
    vals = np.clip(vals, epsilon, None)
    psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(psd), epsilon, None))
    psd = psd / np.outer(d, d)
    psd = (psd + psd.T) / 2.0
    np.fill_diagonal(psd, 1.0)
    return psd


def check_normality(returns, perform_test=False):
    """
    Checks the normality of historical returns by plotting a histogram
    with an overlaid normal distribution curve.

    Args:
        returns (pd.DataFrame): DataFrame of historical returns.
        perform_test (bool): If True, performs the Jarque-Bera statistical test.
    """
    plt.style.use('dark_background')

    print("Checking the normality of historical returns...")

    for stock in returns.columns:
        stock_returns = returns[stock].dropna()

        # Plotting the histogram
        plt.figure(figsize=(10, 6))
        plt.hist(stock_returns, bins=50, density=True, alpha=0.7, color='lime', edgecolor='white', label='Historical Returns')

        # Plotting the normal distribution curve
        mu, sigma = np.mean(stock_returns), np.std(stock_returns)
        xmin, xmax = plt.xlim()
        x = np.linspace(xmin, xmax, 100)
        p = norm.pdf(x, mu, sigma)
        plt.plot(x, p, 'k', linewidth=2, label='Normal Distribution',color='red')

        # Adding titles and labels
        title = f"Histogram of {stock} Returns with Normal Distribution"
        plt.title(title, color='white')
        plt.xlabel("Returns", color='white')
        plt.ylabel("Density", color='white')
        plt.legend()
        plt.show()

        if perform_test:
            jb_test = jarque_bera(stock_returns)
            print(f"Jarque-Bera Test for {stock}:")
            print(f"  Statistic: {jb_test[0]:.4f}")
            print(f"  P-value: {jb_test[1]:.4f}")
            print("---")


NO_SHOCK_RESPONSE = 1e-3   # alpha + gamma/2 below this: the GARCH variance does not react to returns


def is_constant_variance(res):
    return type(res.model.volatility).__name__ == "ConstantVariance"


def fit_garch_with_exog(returns, exog, p_val=False, gjr_alpha=0.05, gjr_min_obs=104, verbose=True):
    """
    Fits a GARCH(1,1)-X (optional shifted-VIX exogenous regressor) to EACH asset on its
    OWN full history. This is robust to heterogeneous histories: every asset uses all of
    its available observations and no global intersection is imposed at this stage.

    :param returns: return panel (may contain NaNs where an asset did not yet trade).
    :param exog:    shifted-VIX series (date-indexed) or None/empty.
    :param p_val:   if True, prints the exogenous-regressor p-values.
    :param gjr_alpha:   significance level of the leverage gate (see below).
    :param gjr_min_obs: assets with fewer weekly observations are never tested and stay plain GARCH.

    Leverage gate (owner decision 2026-10-27): each asset is also fitted as GJR-GARCH, where a down week
    raises next week's variance by (alpha + gamma) * eps^2 and an up week by alpha * eps^2. GJR replaces the
    plain fit only when a likelihood-ratio test says the asymmetry is real (p < gjr_alpha) and the GJR fit
    converged; otherwise the asset keeps plain GARCH and calibrate_heston_params gives it rho = 0.

    :returns: (vol_models, std_resid_df)
        vol_models   : dict {ticker: arch fit result}
        std_resid_df : DataFrame of standardized residuals (eta = eps / sigma), date-indexed,
                       NaN outside each asset's own window. Consumed by forecast_dcc.
    """
    vol_models = {}
    std_resid = {}
    exog_significance = {}
    gate = {}

    have_exog = exog is not None and len(exog) > 0
    if have_exog:
        exog = pd.Series(exog).copy()
        exog.index = pd.to_datetime(pd.Index(exog.index)).date

    for stock in returns.columns:
        y = returns[stock].dropna()
        x_stock = None
        if have_exog:
            x_aligned = exog.reindex(y.index)
            if x_aligned.notna().all():
                x_stock = x_aligned.values.reshape(-1, 1)
            else:
                # Use only the dates where exog is available (keeps a contiguous tail).
                common = y.index[x_aligned.notna().values]
                if len(common) >= 50:
                    y = y.loc[common]
                    x_stock = x_aligned.loc[common].values.reshape(-1, 1)

        model = arch_model(y, vol='GARCH', p=1, q=1, mean='constant', dist='normal',
                           x=x_stock, rescale=False)
        res = model.fit(disp='off', options={'maxiter': 2000})
        if res.convergence_flag != 0:
            print(f"   [GARCH][warn] {stock}: plain GARCH fit did not converge (flag {res.convergence_flag}).")

        choice, lr_p, gamma = 'GARCH', np.nan, np.nan
        if len(y) < gjr_min_obs:
            reason = f"{len(y)} weeks < {gjr_min_obs}: not tested"
        else:
            try:
                res_gjr = arch_model(y, vol='GARCH', p=1, o=1, q=1, mean='constant', dist='normal',
                                     x=x_stock, rescale=False).fit(disp='off', options={'maxiter': 2000})
                lr = 2.0 * (res_gjr.loglikelihood - res.loglikelihood)
                lr_p = float(stats.chi2.sf(max(lr, 0.0), 1))
                gamma = float(res_gjr.params.get('gamma[1]', np.nan))
                if res_gjr.convergence_flag != 0:
                    reason = "GJR fit did not converge"
                elif lr_p < gjr_alpha:
                    choice, res, reason = 'GJR', res_gjr, "asymmetry significant"
                else:
                    reason = "asymmetry not significant"
            except Exception as e:  # a failed test never blocks the run: keep plain GARCH
                reason = f"GJR fit failed ({type(e).__name__})"
        # No shock response (#13): with alpha + gamma/2 ~ 0 the fitted variance never reacts to a return and
        # only decays from arch's starting value, and omega and beta are not identified. On 5y of weekly data
        # NVDA, FERG and NRIM fitted this way (2026-10-29: NVDA's last sigma 5.1%/wk against 6.5% realized).
        # Refit those as constant variance, the model the data does support.
        response = float(res.params.get('alpha[1]', 0.0)) + 0.5 * float(res.params.get('gamma[1]', 0.0))
        if response < NO_SHOCK_RESPONSE:
            res = arch_model(y, vol='Constant', mean='constant', dist='normal', x=x_stock,
                             rescale=False).fit(disp='off', options={'maxiter': 2000})
            choice, reason = 'CONST', (f"{choice} fit had no shock response (alpha+gamma/2={response:.1e}): "
                                       f"constant variance")
        gate[stock] = (choice, lr_p, gamma, reason)
        vol_models[stock] = res

        eta = pd.Series(res.std_resid.values, index=y.index[-len(res.std_resid):])
        std_resid[stock] = eta

        if p_val:
            if x_stock is not None:
                exog_significance[stock] = res.pvalues.iloc[-1]
            else:
                exog_significance[stock] = np.nan
    if p_val:
        print(exog_significance)
    if verbose:
        print("\n   [GARCH] Volatility model per asset (leverage gate, p < %.2f):" % gjr_alpha)
        for t, (choice, lr_p, gamma, reason) in gate.items():
            p_s = f"{lr_p:.3f}" if np.isfinite(lr_p) else "  -  "
            g_s = f"{gamma:+.3f}" if np.isfinite(gamma) else "  -   "
            print(f"     {t:<8} {choice:<5} gamma={g_s} LR p={p_s}  ({reason})")

    std_resid_df = pd.DataFrame(std_resid).sort_index()
    return vol_models, std_resid_df


SHORT_HISTORY_SHARE = 0.80   # an asset under this share of the longest history leaves the correlation dynamics


def forecast_dcc(returns, vol_models, std_resid_df, future_vix, steps=4, min_overlap=30):
    """
    Forecasts the DCC variance-covariance matrices for `steps` ahead.

    Robust to heterogeneous histories: the unconditional correlation target is estimated
    with PAIRWISE-complete observations (uses all data) and repaired to the nearest PSD
    correlation matrix, while the DCC recursion runs on the joint OVERLAP window of
    standardized residuals. Per-asset variances come from each asset's own GARCH forecast.

    :returns: (cov_forecasts, corr_forecasts)
        cov_forecasts  : list[pd.DataFrame] forecasted covariance matrices H_t (legacy output)
        corr_forecasts : list[pd.DataFrame] forecasted correlation matrices R_t
                         (used directly by the Hybrid DCC-Heston simulator)
    """
    N = std_resid_df.shape[1]
    cols = std_resid_df.columns

    # Unconditional correlation target from pairwise-complete obs, repaired to PSD.
    R_bar = _nearest_psd_corr(std_resid_df.corr().values)
    Q_bar = R_bar.copy()  # standardized residuals are ~unit-variance, so Q-bar ~ R-bar.

    # Which assets carry the correlation dynamics (owner, 2026-10-29). If the shortest history is at least
    # SHORT_HISTORY_SHARE of the longest, the dynamics are fitted on the weeks all assets share. Otherwise one young
    # listing would cut that window for everyone (IBHK's 126 weeks did, against 260), so the dynamics are fitted
    # on the assets with at least that share of the longest history, over the weeks THEY share, and the shorter
    # ones keep their long-run pairwise correlations (each pair over its own overlap).
    counts = std_resid_df.notna().sum()
    longest = int(counts.max()) if N else 0
    dyn = [c for c in cols if counts[c] >= SHORT_HISTORY_SHARE * longest]
    short = [c for c in cols if c not in dyn]
    il = [cols.get_loc(c) for c in dyn]
    Nd = len(dyn)
    Qd_bar = Q_bar[np.ix_(il, il)]
    if short:
        print(f"   [forecast_dcc] short histories ({', '.join(f'{c} {int(counts[c])} weeks' for c in short)}, under "
              f"{SHORT_HISTORY_SHARE:.0%} of the longest {longest}): correlation dynamics fitted on "
              f"{'the other asset alone' if Nd == 1 else f'the other {Nd} assets'}; "
              f"{', '.join(short)} keep{'s' if len(short) == 1 else ''} long-run pairwise correlations.")

    overlap = std_resid_df[dyn].dropna(how="any")
    if overlap.shape[0] < min_overlap:
        print(f"   [forecast_dcc][warn] Joint overlap is only {overlap.shape[0]} obs "
              f"(< {min_overlap}); correlation dynamics rely mostly on the PSD-repaired target.")
    residuals = overlap.values
    T = max(residuals.shape[0], 1)

    def dcc_filter(alpha, beta):
        """Q_t for t = 0..T, where Q_T is the one-step-ahead state after the last residual."""
        Q = np.empty((T + 1, Nd, Nd))
        Q[0] = Qd_bar
        for t in range(1, T + 1):
            z = residuals[t - 1]
            Q[t] = (1 - alpha - beta) * Qd_bar + alpha * np.outer(z, z) + beta * Q[t - 1]
        return Q

    def q_to_r(Q):
        d = np.sqrt(np.einsum('...ii->...i', Q))
        return Q / (d[..., :, None] * d[..., None, :])

    def dcc_negloglik(params):
        # Correlation stage of the Gaussian QML (Engle 2002): sum_t log|R_t| + z_t' R_t^-1 z_t.
        # (The previous loss scored distance from R_bar, whose optimum is always alpha = 0.)
        alpha, beta = params
        if alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e10
        R = q_to_r(dcc_filter(alpha, beta)[:-1])
        sign, logdet = np.linalg.slogdet(R)
        if np.any(sign <= 0):
            return 1e10
        quad = np.einsum('ti,tij,tj->t', residuals, np.linalg.inv(R), residuals)
        return 0.5 * float(np.sum(logdet + quad))

    alpha_opt, beta_opt = 0.0, 0.0  # constant correlation if the dynamics cannot be estimated
    if residuals.shape[0] >= min_overlap and Nd > 1:
        opt_res = minimize(dcc_negloglik, [0.02, 0.95], method='SLSQP',
                           bounds=[(0.0, 0.5), (0.0, 0.999)],
                           constraints=[{'type': 'ineq', 'fun': lambda p: 0.998 - p[0] - p[1]}])
        if opt_res.success and np.all(np.isfinite(opt_res.x)):
            alpha_opt, beta_opt = (float(x) for x in opt_res.x)
        else:
            print(f"   [forecast_dcc][warn] DCC fit did not converge ({opt_res.message}); "
                  f"using constant correlation.")
    if alpha_opt < 1e-4:
        # With alpha = 0, Q never leaves Q_bar and beta has no effect (any value fits equally): say so plainly.
        alpha_opt, beta_opt = 0.0, 0.0
        print(f"   [forecast_dcc] no correlation dynamics in the data (alpha = 0 is the best fit over {T} joint "
              f"weeks{'' if Nd > 1 else ', single asset'}): correlations stay at their long-run level.")
    else:
        print(f"   [forecast_dcc] alpha={alpha_opt:.4f} beta={beta_opt:.4f} "
              f"(persistence {alpha_opt + beta_opt:.4f}, {T} joint weeks)")

    # Forecast from today's state, decaying toward Q_bar:
    #   Q_{T+1} = (1-a-b) Q_bar + a z_T z_T' + b Q_T   (filtered),  E[Q_{T+k}] = (1-a-b) Q_bar + (a+b) E[Q_{T+k-1}]
    Qd_forecast = np.zeros((steps, Nd, Nd))
    Qd_forecast[0] = dcc_filter(alpha_opt, beta_opt)[-1] if residuals.shape[0] >= 1 else Qd_bar
    for t in range(1, steps):
        Qd_forecast[t] = (1 - alpha_opt - beta_opt) * Qd_bar + (alpha_opt + beta_opt) * Qd_forecast[t - 1]
    # Embed the dynamic block in the long-run matrix: the short-history assets' rows and columns stay at Q-bar.
    Qt_forecast = np.repeat(Q_bar[None, :, :], steps, axis=0)
    for t in range(steps):
        Qt_forecast[t][np.ix_(il, il)] = Qd_forecast[t]

    Rt_forecast = q_to_r(Qt_forecast)
    if short:   # the mixed matrix need not be positive definite: repair each step where it is not
        for t in range(steps):
            if np.linalg.eigvalsh(Rt_forecast[t]).min() <= 1e-10:
                Rt_forecast[t] = _nearest_psd_corr(Rt_forecast[t])

    # Per-asset GARCH variance forecast (each model uses its own history / exog state).
    vix_fill = float(np.asarray(future_vix).ravel()[0]) if future_vix is not None else None
    vol_cols = []
    for model in vol_models.values():
        has_x = getattr(model.model, "x", None) is not None
        x_future = np.full((steps, 1), vix_fill) if (has_x and vix_fill is not None) else None
        fc = model.forecast(horizon=steps, x=x_future)
        vol_cols.append(np.sqrt(fc.variance.values.flatten()))
    vol_forecast = np.array(vol_cols).T  # (steps, N)

    cov_forecasts = [Rt_forecast[t] * np.outer(vol_forecast[t], vol_forecast[t]) for t in range(steps)]
    cov_dfs = [pd.DataFrame(cov, index=cols, columns=cols) for cov in cov_forecasts]
    corr_dfs = [pd.DataFrame(Rt_forecast[t], index=cols, columns=cols) for t in range(steps)]
    return cov_dfs, corr_dfs


def gjr_leverage_rho(alpha, gamma, z):
    """Heston rho implied by a GJR fit: corr(z, (alpha + gamma*1{z<0}) z^2), the correlation between a week's
    standardized return shock and the variance shock it causes, using the residuals' own moments. Returns 0
    when the variance does not respond (alpha = gamma = 0) or the inputs are degenerate."""
    z = np.asarray(z, dtype=float)
    z = z[np.isfinite(z)]
    if z.size < 30:
        return 0.0
    shock = (alpha + gamma * (z < 0)) * z ** 2
    if np.std(shock) < 1e-12:
        return 0.0
    r = float(np.corrcoef(z, shock)[0, 1])
    return float(np.clip(r, -0.95, 0.95)) if np.isfinite(r) else 0.0


XI_FLOOR = 1e-4


def calibrate_heston_params(vol_models, std_resid_df=None, dt=1.0, verbose=True):
    """
    Calibrates per-asset Heston / CIR stochastic-variance parameters from the ALREADY
    fitted GARCH conditional-variance series (P-measure, no extra data). This reuses the
    Nelson (1990) GARCH-diffusion-limit intuition but estimates kappa/xi *directly* by
    fitting the CIR Euler regression to v_t = sigma_t^2, which is robust and self-consistent
    with the rest of the pipeline (everything stays in weekly units):

        dv = kappa (theta - v) dt + xi sqrt(v) dW_v,   corr(dW_S, dW_v) = rho

    The long-run target `theta` returned here is the historical unconditional level; the
    simulator overrides it per-step with the DCC/GARCH variance *forecast* so the VIX-driven
    view still drives the Heston mean level.

    :returns: dict {ticker: {v0, kappa, theta, xi, rho}} in WEEKLY units.
    """
    heston = {}
    constant = []
    for stock, res in vol_models.items():
        if is_constant_variance(res):
            constant.append(stock)
            continue
        sigma = np.asarray(res.conditional_volatility, dtype=float)
        sigma = sigma[np.isfinite(sigma) & (sigma > 0)]
        if sigma.size < 30:
            v_const = float(np.mean(sigma ** 2)) if sigma.size else 1e-4
            heston[stock] = dict(v0=v_const, kappa=0.05, theta=v_const, xi=1e-3, rho=0.0, source="fit",
                                 at_bound=[f"fewer than 30 variance observations ({sigma.size}): fixed defaults"])
            continue

        v = sigma ** 2
        v_lag = v[:-1]
        dv = np.diff(v)

        # OLS: dv = a + b * v_lag  =>  b = -kappa*dt, a = kappa*theta*dt
        A = np.vstack([np.ones_like(v_lag), v_lag]).T
        a, b = np.linalg.lstsq(A, dv, rcond=None)[0]
        bounds = []
        kappa = -b / dt
        if not np.isfinite(kappa) or kappa <= 1e-6:
            kappa = 0.05  # near-integrated GARCH -> weak but positive mean reversion
            bounds.append("kappa at its fallback 0.05 (no mean reversion found)")
        theta = a / (kappa * dt)
        if not np.isfinite(theta) or theta <= 0:
            theta = float(np.mean(v))
            bounds.append("theta at the sample mean variance (regression gave none)")

        # xi from the CIR diffusion term: E[resid^2] ~ xi^2 * v_lag * dt
        resid = dv - (a + b * v_lag)
        denom = np.maximum(v_lag * dt, 1e-12)
        xi = float(np.sqrt(np.mean(resid ** 2 / denom)))
        if xi < XI_FLOOR:
            bounds.append(f"xi at its floor {XI_FLOOR} (fitted {xi:.1e})")
        xi = max(xi, XI_FLOOR)

        # Leverage effect (owner decision 2026-10-27): only from a GJR fit that passed the asymmetry test in
        # fit_garch_with_exog; plain-GARCH assets get rho = 0. A symmetric GARCH variance responds to the size
        # of a shock, never its sign, so the old corr(z, dv) on it measured skewness, not leverage.
        rho = 0.0
        if 'gamma[1]' in res.params.index:
            rho = gjr_leverage_rho(float(res.params['alpha[1]']), float(res.params['gamma[1]']),
                                   np.asarray(res.std_resid, dtype=float))

        # v0 = one-step-ahead GARCH variance sigma^2_{T+1} = omega + alpha*eps_T^2 + beta*sigma^2_T, so the
        # simulation starts from the same week the DCC/GARCH forecast (theta_path[0]) starts from.
        # (sigma^2_T itself was known before the last week's return arrived.)
        v0 = float(v[-1])
        try:
            pr = res.params
            eps_T = float(np.asarray(res.resid)[-1])
            news = pr['alpha[1]'] + (pr['gamma[1]'] if ('gamma[1]' in pr.index and eps_T < 0) else 0.0)
            v_next = float(pr['omega'] + news * eps_T ** 2 + pr['beta[1]'] * v[-1])
            if np.isfinite(v_next) and v_next > 0:
                v0 = v_next
        except (KeyError, IndexError):
            pass

        heston[stock] = dict(v0=v0, kappa=float(kappa), theta=float(theta),
                             xi=xi, rho=rho, source="fit", at_bound=bounds)

    # Constant-variance assets (no shock response in their GARCH): their own variance level, with mean
    # reversion and vol of vol pooled from the identified assets (median kappa, median xi / sqrt(theta), so
    # vol of vol scales with the asset's own level). Labelled, never silent.
    ident = [p for p in heston.values() if p["source"] == "fit" and not p["at_bound"]]
    for stock in constant:
        res = vol_models[stock]
        var = float(np.asarray(res.conditional_volatility, dtype=float)[-1] ** 2)
        if ident:
            kappa = float(np.median([p["kappa"] for p in ident]))
            ratio = float(np.median([p["xi"] / np.sqrt(p["theta"]) for p in ident]))
            src = f"pooled from {len(ident)} identified assets (constant variance)"
        else:
            kappa, ratio, src = 0.05, 0.0, "no identified asset to pool from: constant variance, no vol of vol"
        heston[stock] = dict(v0=var, kappa=kappa, theta=var, xi=float(max(ratio * np.sqrt(var), XI_FLOOR)), rho=0.0,
                             source=src, at_bound=[])
    heston = {k: heston[k] for k in vol_models}

    at_bound = {t: p["at_bound"] for t, p in heston.items() if p["at_bound"]}
    if at_bound:
        print("\n   [Heston][BOUND] fits at a bound (the estimate is the bound, not the data):")
        for t, b in at_bound.items():
            print(f"     {t:<8} {', '.join(b)}")
    pooled = [t for t, p in heston.items() if p["source"] != "fit"]
    if pooled:
        print(f"   [Heston][POOLED] constant variance, kappa and xi pooled: {', '.join(pooled)}")

    if verbose:
        print("\n   [Heston] Per-asset CIR variance calibration (weekly units):")
        for t, p in heston.items():
            feller = "ok" if 2 * p['kappa'] * p['theta'] >= p['xi'] ** 2 else "violated"
            print(f"     {t:<8} v0={p['v0']:.5f} theta={p['theta']:.5f} kappa={p['kappa']:.3f} "
                  f"xi={p['xi']:.4f} rho={p['rho']:+.2f}  Feller:{feller}"
                  f"{'' if p['source'] == 'fit' else '  [' + p['source'] + ']'}")
    return heston


def calibrate_vix_betas(vol_models, vix_weekly, gamma_clip=(0.0, 2.0), verbose=True):
    """
    Estimates each asset's VIX elasticity gamma_i: the sensitivity of its variance to the level of VIX.

    gamma_i is the OLS slope of ln(conditional_variance_t) on ln(VIX_t), aligned by date, using the
    already-fitted GARCH conditional variance (reuses `vol_models`). It is the exponent in the Heston
    long-run-variance tilt theta'_{i,t} = theta_{i,t} * (VIX_now / VIX_bar) ** gamma_i, so a value of 0
    means "this asset's variance does not respond to VIX" (no tilt). Clipped to gamma_clip for stability.

    :param vix_weekly: date-indexed weekly VIX close series (python-date index, same grid as returns).
    :returns: dict {ticker: gamma_i}.
    """
    vix = pd.Series(vix_weekly).copy()
    vix.index = pd.to_datetime(pd.Index(vix.index)).date
    log_vix = np.log(vix.astype(float))

    betas = {}
    for stock, res in vol_models.items():
        sigma = pd.Series(np.asarray(res.conditional_volatility, dtype=float))
        # conditional_volatility is date-indexed via the arch result; fall back to its own index.
        try:
            sigma.index = pd.to_datetime(pd.Index(res.conditional_volatility.index)).date
        except Exception:
            betas[stock] = 0.0
            continue
        lv = np.log(np.clip(sigma.values, 1e-12, None) ** 2)
        ln_var = pd.Series(lv, index=sigma.index)

        joined = pd.concat([ln_var.rename("y"), log_vix.rename("x")], axis=1).dropna()
        if joined.shape[0] < 30 or joined["x"].std() < 1e-8:
            betas[stock] = 0.0
            continue
        # OLS slope of y on x
        x = joined["x"].values
        y = joined["y"].values
        slope = np.polyfit(x, y, 1)[0]
        betas[stock] = float(np.clip(slope, gamma_clip[0], gamma_clip[1]))

    if verbose:
        print("\n   [VIX-theta] Per-asset VIX elasticity gamma (variance ~ VIX^gamma):")
        for t, g in betas.items():
            print(f"     {t:<8} gamma={g:.3f}")
    return betas
