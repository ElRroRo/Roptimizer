# ==============================================================================
# Generates the figures embedded in the v4.1 paper (main.tex).
# Most figures are analytic/illustrative; fig_compensator() reads the live tabulation out of
# DynamicPortfolioOptimizationFunc (which imports cupy). Run:  python figures.py
# ==============================================================================
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from scipy.stats import genpareto

OUT = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 150, "savefig.bbox": "tight"})


def fig_jump_density():
    """Asymmetric Pareto (GPD) crash vs rally jump density, in volatility (z) units."""
    thr = 3.0
    xr = np.linspace(thr, 9, 400)
    crash = genpareto.pdf(xr - thr, 0.25, scale=0.6)   # fatter tail on the downside
    rally = genpareto.pdf(xr - thr, 0.15, scale=0.5)
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.fill_between(-xr, crash * 0.55, color="#c0392b", alpha=0.75, label="Crash (p=0.55, ξ=0.25)")
    ax.fill_between(xr, rally * 0.45, color="#27ae60", alpha=0.75, label="Rally (p=0.45, ξ=0.15)")
    ax.axvspan(-thr, thr, color="grey", alpha=0.12)
    ax.text(0, ax.get_ylim()[1] * 0.5, "diffusive\ncore", ha="center", va="center", color="grey")
    ax.set_xlabel("Jump size (standard deviations)"); ax.set_ylabel("Density × P(direction)")
    ax.set_title("Asymmetric Pareto (EVT) jump distribution")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(os.path.join(OUT, "jump_density.png")); plt.close(fig)


def fig_cir_paths():
    """CIR/Heston variance sample paths mean-reverting to theta, one with an SVJJ co-jump."""
    rng = np.random.default_rng(7)
    kappa, theta, xi, dt = 0.15, 0.0025, 0.02, 1.0
    T = 52
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for k in range(6):
        v = np.empty(T); v[0] = 0.0025
        for t in range(1, T):
            vp = max(v[t - 1], 0)
            v[t] = vp + kappa * (theta - vp) * dt + xi * np.sqrt(vp) * np.sqrt(dt) * rng.standard_normal()
            if k == 0 and t == 18:            # illustrate a crash-triggered variance co-jump
                v[t] += 1.2 * theta
        ax.plot(np.sqrt(np.clip(v, 0, None)) * 100, lw=1.3,
                color="#c0392b" if k == 0 else "#34495e", alpha=0.9 if k == 0 else 0.5,
                label="path with variance co-jump" if k == 0 else None)
    ax.axhline(np.sqrt(theta) * 100, color="#2980b9", ls="--", lw=1.6, label=r"$\sqrt{\theta}$ (long-run vol)")
    ax.set_xlabel("Week"); ax.set_ylabel("Instantaneous volatility (%/wk)")
    ax.set_title("Stochastic (CIR) variance with a co-jump")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(os.path.join(OUT, "cir_paths.png")); plt.close(fig)


def fig_vix_decay():
    """Horizon decay of the VIX->theta tilt ratio for a few VIX regimes."""
    t = np.arange(12); rho = 0.3
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for (vn, vb, g, c, lbl) in [(32, 18, 0.7, "#c0392b", "stress: VIX 32, γ=0.7"),
                                (24, 18, 0.5, "#e67e22", "elevated: VIX 24, γ=0.5"),
                                (12, 18, 0.7, "#27ae60", "calm: VIX 12, γ=0.7")]:
        r0 = np.clip((vn / vb) ** g, 0.5, 3.0)
        ax.plot(t, 1 + (r0 - 1) * np.exp(-rho * t), marker="o", ms=4, color=c, label=lbl)
    ax.axhline(1.0, color="grey", ls=":", lw=1)
    ax.set_xlabel("Forecast week"); ax.set_ylabel(r"$\theta$ tilt ratio  $r_{i,t}$")
    ax.set_title("VIX→θ tilt: horizon decay toward neutral")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(os.path.join(OUT, "vix_decay.png")); plt.close(fig)


def fig_ladder():
    """Engine-ladder tail risk (from validation_heston.py A/B)."""
    names = ["Legacy\nGBM", "Heston\n(no jumps)", "+ Bates\njumps", "+ Hawkes\nclustering", "+ Co-\njumps"]
    cvar = [-0.287, -0.210, -0.286, -0.312, -0.338]
    cdar = [-0.251, -0.181, -0.250, -0.270, -0.285]
    kurt = [0.70, 0.01, 0.73, 1.94, 3.62]
    x = np.arange(len(names)); w = 0.38
    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    ax.bar(x - w / 2, np.abs(cvar), w, color="#c0392b", label="|CVaR| (5%)")
    ax.bar(x + w / 2, np.abs(cdar), w, color="#8e44ad", label="|CDaR| (5%)")
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=8.5)
    ax.set_ylabel("Tail loss magnitude"); ax.set_title("Marginal tail-risk contribution of each component")
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax2 = ax.twinx(); ax2.plot(x, kurt, "k--o", ms=4, label="excess kurtosis")
    ax2.set_ylabel("Excess kurtosis"); ax2.grid(False); ax2.legend(frameon=False, loc="upper right", fontsize=9)
    fig.savefig(os.path.join(OUT, "ladder.png")); plt.close(fig)


def fig_compensator():
    """g(s) = E[e^{Js} - 1 | jump] against s = sqrt(v): the curve the compensator has to follow.

    Drawn from the engine's own tabulation (DynamicPortfolioOptimizationFunc._compensator_grid),
    not from hardcoded numbers, so the figure cannot drift away from the model.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import DynamicPortfolioOptimizationFunc as d
    layer = {"prob_crash": 0.55, "crash_shape": 0.15, "crash_scale": 0.5,
             "rally_shape": 0.12, "rally_scale": 0.5, "threshold": 3.0}
    s_max = 0.16
    ds, tab = d._compensator_grid(layer, s_max)
    s = np.arange(len(tab)) * ds
    theta_repr, hi = 0.035, 0.09          # calm sqrt(theta) and a post-co-jump stressed level

    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.axhline(0, color="#555", lw=0.9)
    ax.plot(s * 100, tab, color="#c0392b", lw=2.0, label=r"$g(s)=E[e^{Js}-1\,|\,$jump$]$")
    ax.axhline(np.interp(theta_repr, s, tab), color="#2980b9", ls="--", lw=1.4,
               label=r"v4.0: frozen at $s=\sqrt{\theta}$")
    ax.plot([theta_repr * 100], [np.interp(theta_repr, s, tab)], "o", color="#2980b9", ms=6)
    ax.plot([hi * 100], [np.interp(hi, s, tab)], "o", color="#c0392b", ms=6)
    ax.annotate("compensator frozen here...", xy=(theta_repr * 100, np.interp(theta_repr, s, tab)),
                xytext=(0.35, 0.0115), fontsize=8, color="#2980b9",
                arrowprops=dict(arrowstyle="->", color="#2980b9", lw=1.0))
    ax.annotate("...but the state is here\nafter a variance co-jump",
                xy=(hi * 100, np.interp(hi, s, tab)), xytext=(9.6, 0.004), fontsize=8, color="#c0392b",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.0))
    zc = s[np.argmin(np.abs(tab[1:])) + 1] * 100
    ax.axvline(zc, color="#7f8c8d", ls=":", lw=1.2)
    ax.text(zc + 0.15, ax.get_ylim()[1] * 0.72, f"sign change\n({zc:.1f}% weekly vol)",
            fontsize=8, color="#7f8c8d")
    ax.set_xlabel("weekly volatility $s=\\sqrt{v}$  (%)")
    ax.set_ylabel("$g(s)$")
    ax.set_title("The jump compensator is convex in volatility and changes sign")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.savefig(os.path.join(OUT, "compensator.png")); plt.close(fig)


def fig_pipeline():
    """Schematic of the end-to-end pipeline."""
    fig, ax = plt.subplots(figsize=(7.2, 2.5)); ax.axis("off")
    boxes = ["Robust\ndata panel", "GARCH +\nDCC R$_t$", "Black–\nLitterman", "Hybrid DCC–\nHeston–Bates\n(+VIX θ, Hawkes,\nco-jumps)", "CVaR /\nCDaR", "Diff.\nEvolution"]
    n = len(boxes); xs = np.linspace(0.04, 0.83, n)
    for i, (xx, b) in enumerate(zip(xs, boxes)):
        ax.add_patch(FancyBboxPatch((xx, 0.32), 0.13, 0.42, boxstyle="round,pad=0.012",
                                    fc="#eaf2f8" if i != 3 else "#fdecea",
                                    ec="#2980b9" if i != 3 else "#c0392b", lw=1.6, transform=ax.transAxes))
        ax.text(xx + 0.065, 0.53, b, ha="center", va="center", fontsize=8, transform=ax.transAxes)
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((xx + 0.13, 0.53), (xs[i + 1], 0.53), transform=ax.transAxes,
                                         arrowstyle="-|>", mutation_scale=12, color="#555"))
    ax.set_title("End-to-end optimization pipeline", fontsize=11)
    fig.savefig(os.path.join(OUT, "pipeline.png")); plt.close(fig)


if __name__ == "__main__":
    fig_jump_density(); fig_cir_paths(); fig_vix_decay(); fig_ladder(); fig_compensator(); fig_pipeline()
    print("Figures written to", OUT)
