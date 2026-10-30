"""Black-Litterman: views to (P, q, Omega) and the posterior expected returns."""
# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================


import numpy as np
import pandas as pd
from scipy import linalg as lin


def create_black_litterman_views(tickers, analyst_views, view_stdevs):
    """
    Creates P (link), Q (views), and the View Variances (for Omega).

    Args:
        tickers: List of asset tickers.
        analyst_views: Dict {ticker: absolute_return_float}.
        view_stdevs: Dict {ticker: annual standard deviation of the view itself}, i.e. how far the
                     expected return could be off. Example: {'AAPL': 0.10} with a 25% view means
                     "I expect 25% a year, give or take 10 points". Omega = stdev^2, in the same annual
                     units as Sigma, Pi and Q.

    Returns:
        P: Link matrix (num_views x num_assets).
        Q: View vector (num_views).
        view_variances: Numpy array of variances aligned with Q (for the diagonal of Omega).
    """
    num_assets = len(tickers)
    view_indices = []
    view_values = []
    view_vars = []

    for i, ticker in enumerate(tickers):
        view = analyst_views.get(ticker)

        # We only process if there is a view
        if view is not None:
            # Sanitize view if it's a percentage string
            if isinstance(view, str) and '%' in view:
                view = float(view.replace('%', '')) / 100.0
            elif isinstance(view, str):
                view = float(view)

            view_indices.append(i)
            view_values.append(view)

            # --- NEW LOGIC: Handling Confidence (Omega) ---
            if view_stdevs is not None and ticker in view_stdevs:
                yearly_stdev = view_stdevs[ticker]

                # Sanitize yearly_stdev if it's a percentage string or None
                if yearly_stdev is None:
                    yearly_stdev = 0.20
                elif isinstance(yearly_stdev, str) and '%' in yearly_stdev:
                    yearly_stdev = float(yearly_stdev.replace('%', '')) / 100.0
                elif isinstance(yearly_stdev, str):
                    yearly_stdev = float(yearly_stdev)

                # Annual variance of the expectation, the same units as the annual Sigma it is blended with.
                # (It used to be divided by 52, which made every view ~7x more certain than entered.)
                yearly_stdev = max(float(yearly_stdev), 1e-4)  # a 0 would make Omega singular
                view_vars.append(yearly_stdev ** 2)
            else:
                # Fallback if stdev dict provided but specific ticker missing:
                # Default to a loose confidence (e.g., 20% yearly stdev) or raise error
                default_stdev = 0.20
                view_vars.append(default_stdev ** 2)

    num_views = len(view_indices)

    if num_views == 0:
        return np.empty((0, num_assets)), np.empty(0), np.empty(0)

    P = np.zeros((num_views, num_assets))
    Q = np.array(view_values)
    view_variances = np.array(view_vars)

    for i, index in enumerate(view_indices):
        P[i, index] = 1

    return P, Q, view_variances


def black_litterman_mod(portfolio, sigma, p, q, equilibrium_ret, view_variances=None, return_cov=False):
    """
    Conducts Black-Litterman portfolio optimization with explicit view confidences.

    :param view_variances: Numpy array of the variances of the views (diagonal of Omega).
                           If None, defaults to He-Litterman proportional method.
    """

    # --- SANITIZE INPUTS ---
    # Convert equilibrium_ret from strings (e.g. '11.31%') to floats if necessary
    if isinstance(equilibrium_ret, (list, np.ndarray)):
        clean_ret = []
        for r in equilibrium_ret:
            if isinstance(r, str):
                clean_ret.append(float(r.replace('%', '')) / 100.0 if '%' in r else float(r))
            else:
                clean_ret.append(float(r))
        equilibrium_ret = np.array(clean_ret)

    # Ensure q is a float array
    q = np.array(q, dtype=float)

    if isinstance(sigma, pd.DataFrame):
        sigma_np = sigma.values
    else:
        sigma_np = sigma

    # Tao is the scalar for the uncertainty of the Prior (CAPM).
    # Since you are providing specific View Variances (Omega), Tao usually serves
    # only to scale the Prior Covariance.
    # Deliberately small (owner, 2026-10-27): equilibrium returns are CAPM, and the model should lean hard on
    # the efficient-market prior. Equilibrium uncertainty = sqrt(0.01) = 10% of each asset's own volatility,
    # so a view moves an asset only when its uncertainty is comparably tight.
    tao = 0.01

    if view_variances is not None and len(view_variances) > 0:
        # Construct Diagonal Matrix from input variances
        omega = np.diag(view_variances)
    else:
        # Old method: Proportional to Prior (He & Litterman standard)
        # Omega = P * (tau * Sigma) * P.T
        omega = p @ (tao * sigma_np) @ p.T

    # --- CALCULATION (Unchanged logic, just using the new Omega) ---

    # Inverse of (tau * Sigma)
    tau_sigma_inv = lin.inv(tao * sigma_np)

    # Inverse of Omega
    omega_inv = lin.inv(omega)

    # 1. Posterior Covariance (Part One)
    # H = P.T * Omega^-1 * P
    H = p.T @ omega_inv @ p

    # Posterior Sigma = ( (tau*Sigma)^-1 + H )^-1
    posterior_cov = lin.inv(tau_sigma_inv + H)

    # 2. Posterior Return (Part Two)
    # Term 1: (tau*Sigma)^-1 * Pi
    term_1 = tau_sigma_inv @ equilibrium_ret

    # Term 2: P.T * Omega^-1 * Q
    term_2 = p.T @ omega_inv @ q

    # Posterior Return = Posterior Sigma * (Term 1 + Term 2)
    posterior_ret = posterior_cov @ (term_1 + term_2)

    # return_cov: also the posterior uncertainty M = ((tau Sigma)^-1 + P' Omega^-1 P)^-1 (annual), which the
    # tree uses for a subportfolio's implied-return uncertainty and the sensitivity band's draws (#6, #7).
    return (posterior_ret, posterior_cov) if return_cov else posterior_ret
