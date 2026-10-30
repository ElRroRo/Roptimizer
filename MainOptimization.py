# ==============================================================================
# PROJECT: Roptimizer
# AUTHOR: Eljon Rrodhe (eljonrrodhe11@gmail.com)
# COPYRIGHT: © 2026 Eljon Rrodhe
# LICENSE: Apache License 2.0 (see the LICENSE file)
# ==============================================================================

import os
# QUICK smoke-test mode: small sims/iters, skip the heavy 100-ticker jump calibration, and use a
# non-blocking plotting backend so the full pipeline can be validated in ~1-2 minutes. Enable with
#   OPT_QUICK=0 python MainOptimization.py
# (The trigger is deliberately '0', not '1': see commit 434d8ad.)
# Fine-tune any run with OPT_NSIM / OPT_NITER / OPT_POPSIZE. Production defaults are unchanged.
QUICK = os.environ.get('OPT_QUICK') == '0'
if QUICK:
    import matplotlib
    matplotlib.use('Agg')  # must precede any pyplot import (engine imports it) to avoid blocking show()

import sys
import cupy as cp
import numpy as np
import pandas as pd
from scipy.stats import norm, kurtosis, expon
import yfinance as yf
from arch import arch_model
from scipy.optimize import minimize, differential_evolution
from DynamicPortfolioOptimizationFunc import *
from mso.pipeline import InputsError, build_inputs
import matplotlib.pyplot as plt

def main():
    print(f"CuPy Version: {cp.__version__}")
    print(f"CUDA Runtime Version: {cp.cuda.runtime.runtimeGetVersion()}")
    print(f"CUDA Driver Version: {cp.cuda.runtime.driverGetVersion()}")

    # Quick GPU test
    try:
        test = cp.array([1, 2, 3]) ** 2
        print(f"GPU Test: SUCCESS - {test}")
    except Exception as e:
        print(f"GPU Test FAILED: {e}")
        return

    # --- 1-4. INPUTS: data, GARCH/DCC/Heston fits, VIX tilt, Black-Litterman, jump configs ---
    # Built by mso.pipeline, the same code the v5.0 CLI and benchmarks/snapshot.py use.
    try:
        inputs, _ = build_inputs('portfolio_data.csv', quick=QUICK)
    except InputsError as e:
        print(f"\n[!] FATAL: {e}")
        return
    portfolio, initial_prices, ALPHA_CDAR = inputs["tickers"], inputs["initial_prices"], inputs["alpha_cdar"]

    # Optimization scale. Production defaults; override via env for a fast smoke test, e.g.
    #   OPT_QUICK=0 (=> 400k sims, 8 iters, popsize 12) or OPT_NSIM/OPT_NITER/OPT_POPSIZE.
    num_sims = int(os.environ.get('OPT_NSIM', 400_000 if QUICK else 3_000_000))
    # DE generations kept modest (15): with a noisy per-evaluation MC objective, too many generations
    # over-fit the optimizer to sampling-noise realizations rather than to a robust optimum.
    n_iters = int(os.environ.get('OPT_NITER', 8 if QUICK else 15))
    pop_size = int(os.environ.get('OPT_POPSIZE', 12 if QUICK else 30))
    print(f"\nOptimization scale: sims={num_sims:,} iters={n_iters} popsize={pop_size}"
          f"{'  [QUICK]' if QUICK else ''}")

    print("\nStarting Jump-Sensitive Optimization...")
    weights, returns, std, cvar, starr, simulated_paths, raw_assets, cdar = run_optimization(
        num_simulations_for_cvar=num_sims,   # Heston-Bates peaks ~3.4GB at 4M (<=4.5GB cap on 6GB VRAM)
        n_iterations=n_iters,
        popsize=pop_size,
        **legacy_kwargs(inputs),
    )

    # --- 6. RESULTS ---
    # All metrics are reported over the model's native 12-week (~quarter) simulation horizon.
    # They are intentionally NOT annualized: CVaR/CDaR cannot be soundly annualized under fat
    # tails + jumps, so every figure is kept on one consistent horizon.
    print("\n" + "="*40)
    print("   OPTIMIZATION COMPLETE  (12-week horizon)")
    print("="*40)
    print(f"Expected Return (12wk, posterior): {returns:.4f}")
    print(f"Volatility (12wk):      {std:.4f}")
    print(f"CVaR ({ALPHA_CDAR*100:.0f}%, 12wk):     {cvar:.4f}")
    print(f"CDaR ({ALPHA_CDAR*100:.0f}%, 12wk):     {cdar:.4f}")
    # Signed: a negative STARR means the portfolio is expected to lose to the risk-free rate.
    print(f"STARR (12wk, excess return / |CVaR|): {starr:+.4f}")
    print("\nFinal Weights:")
    for n, w in enumerate(weights):
        if w > 0.0001:  # Only print non-zero weights
            print(f"  {portfolio[n]}: {w:.2%}")
    print("="*40)

    # --- 7. PLOTTING ---
    print("\nGenerating plots...")
    plot_optimized_port(initial_prices, weights, simulated_paths)
    plt.show() # Necessary for non-notebook execution

    plot_all_asset_distributions(raw_asset_returns=raw_assets, tickers=portfolio)
    plt.show()

if __name__ == "__main__":
    main()
