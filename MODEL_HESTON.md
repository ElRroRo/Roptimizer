# Hybrid DCC–Heston–Bates Price Engine (with Hawkes clustering & variance co-jumps)

*v4.1 — state-dependent jump compensator.*

*Mathematical companion to `A_Multi_Stage_High_Fidelity_Framework...pdf` (v3.0). This document
describes the upgrade of the Monte-Carlo price simulator from a Euler GBM-with-jumps process to a
**stochastic-variance (Heston)** process that keeps the existing asymmetric Pareto jumps (making it a
**Bates** model), adds **self-exciting (Hawkes)** jump arrivals, and **variance co-jumps** (SVJJ). The
DCC-GARCH-X, Black-Litterman, CVaR/CDaR and Differential-Evolution stages are unchanged.*

---

## 1. Motivation

The legacy simulator (paper §7.1) evolves each asset as

$$S_{i,t} = S_{i,t-1}\exp\!\Big[(\mu_{i,t}-\tfrac12\sigma_{i,t}^2)\Delta t + \sigma_{i,t}\sqrt{\Delta t}\,Z_{i,t} + \text{Jump}_{i,t}\Big],$$

where $\sigma_{i,t}$ is the **deterministic** DCC-GARCH-X variance forecast $H_t$. Three limitations:

1. **Variance is not stochastic** — a forecast path, not a random process; it cannot itself spike.
2. **Jumps are memoryless** — each step is independent, so crashes never *cluster* (2008, Mar-2020 were cascades). This structurally under-states drawdown (CDaR) risk.
3. **No price→variance feedback** — a crash does not raise future volatility, contrary to observed vol explosions.
4. The drift correction is only $-\tfrac12\sigma^2$; the **jump compensator is missing**, so asymmetric jumps silently bias the realised mean.

This upgrade addresses all four while preserving the DCC correlation structure.

---

## 2. The Hybrid DCC–Heston specification

Each asset's variance follows a **CIR / Heston** process; cross-asset dependence is carried by the
**DCC correlation** $R_t$ (we keep DCC for what it is best at — time-varying correlation — and replace
only the per-asset variance diagonal):

$$
\begin{aligned}
dS_{i}/S_{i} &= \mu_i\,dt + \sqrt{v_i}\,dW^{S}_i + \big(e^{J_i\sqrt{v_{i,t^-}\tau}}-1\big)\,dN_i,\\
dv_{i} &= \kappa_i(\theta_{i,t}-v_i)\,dt + \xi_i\sqrt{v_i}\,dW^{v}_i + m_i\theta_i\,dN^{\text{crash}}_i,\\
\operatorname{corr}(dW^{S}_i,\,dW^{v}_i) &= \rho_i \quad\text{(leverage)},\qquad
\operatorname{corr}(dW^{S}_i,\,dW^{S}_j) = R_{t,ij}\ \text{(DCC)}.
\end{aligned}
$$

* $v_i$ — instantaneous variance (weekly units), $\kappa_i$ mean-reversion speed, $\theta_{i,t}$ long-run
  target, $\xi_i$ vol-of-vol, $\rho_i$ leverage.
* $N_i$ — jump counting process (Hawkes, §4); $J_i$ — asymmetric Pareto jump size (paper §6).
* **The jump mark is vol-scaled.** $J_i$ is calibrated in **z-score units** — a GPD fit to exceedances of
  *standardized* GARCH residuals (`jump_paremeters.py`, threshold 3.0), so $J_i=-4$ means "a four-sigma
  week". A z-score is dimensionless and cannot be exponentiated on its own; the volatility prevailing at the
  jump instant, $\sqrt{v_{i,t^-}}$, is what turns it back into a log return. Hence
  $\big(e^{J_i\sqrt{v_{i,t^-}\tau}}-1\big)$, at the **left limit** $v_{i,t^-}$ so a crash is sized by
  pre-crash variance and the co-jump it triggers is felt only from the next step. $\tau$ = 1 week is the
  fixed horizon the jump law was estimated over; it carries the $\sqrt{\text{time}}$ that makes the exponent
  dimensionless and does **not** rescale with $\Delta t$.
* **The variance co-jump is not a separate process.** It fires on, and only on, a *crash* arrival of the
  same $N_i$ that moves the price — that contemporaneity is the whole SVJJ mechanism. Writing it as a
  free-standing $dJ^v_i$ (as v4.0 did) hides the coupling.
* $\theta_{i,t}$ is set **per step** to the DCC/GARCH variance forecast $\operatorname{diag}(H_t)_i$, then
  optionally tilted by the VIX signal (§3b) so a forward-looking fear gauge anchors the Heston mean level.

### 2.1 Correlation construction (vectorised, GPU-friendly)
Draw $\varepsilon\sim N(0,I_N)$ and correlate the **price** shocks with the Cholesky factor of the DCC correlation:
$$Z^{S} = L_R\,\varepsilon,\qquad L_R L_R^\top = R_t.$$
Each asset's **variance** shock then carries the leverage correlation against its own price shock:
$$Z^{v}_i = \rho_i Z^{S}_i + \sqrt{1-\rho_i^2}\,\eta_i,\qquad \eta\sim N(0,I_N).$$
($R_t$ is repaired to the nearest PSD correlation matrix if needed — see `_nearest_psd_corr`.)

---

## 3. Calibration from the fitted GARCH (Nelson diffusion limit)

All Heston parameters are estimated **from the already-fitted GARCH** (P-measure, no extra data), reusing
Nelson's (1990) GARCH-diffusion-limit intuition. Let $v_t=\sigma_t^2$ be the GARCH conditional-variance series.

* $v_{0,i}=v_T$ (last conditional variance), $\theta_i=\overline{v}$ (historical fallback; overridden per-step by the DCC forecast).
* **$\kappa,\theta$** by OLS on the CIR Euler regression $\Delta v_t = a + b\,v_{t-1}+\epsilon_t$, giving
  $\kappa = -b/\Delta t$ and $\theta = a/(\kappa\Delta t)$.
* **$\xi$** from the diffusion residual: $\mathbb E[\epsilon_t^2]\approx \xi^2\,v_{t-1}\Delta t \Rightarrow \xi=\sqrt{\overline{\epsilon_t^2/(v_{t-1}\Delta t)}}$.
* **$\rho$** = $\operatorname{corr}(z_t,\,\Delta v_t)$ from standardized residuals $z_t=\epsilon_t/\sigma_t$ (the leverage effect; negative for equities).

Implemented in `calibrate_heston_params`.

---

## 3b. VIX-driven long-run variance ($\theta$) tilt

VIX enters the model **here**, at the Heston long-run variance — *not* through `arch`'s mean-regressor `x`,
which is silently dropped under `mean='constant'` (so the legacy "GARCH-X" was never functional). Because
$\theta$ is the *forward-looking* parameter the variance reverts toward, it is the natural home for VIX (an
implied, forward-looking signal). We tilt each asset's long-run target by how elevated VIX is versus its own
history, fading the tilt back to neutral across the horizon (only today's VIX is known):

$$
r_i = \operatorname{clip}\!\left(\left(\tfrac{\mathrm{VIX}_{\text{now}}}{\overline{\mathrm{VIX}}}\right)^{\gamma_i},\,c_\text{lo},\,c_\text{hi}\right),
\qquad
r_{i,t} = 1 + (r_i - 1)\,e^{-\rho t},
\qquad
\theta'_{i,t} = \theta_{i,t}\,r_{i,t}.
$$

* $\gamma_i$ — the asset's **VIX elasticity**, the OLS slope of $\ln v_t$ on $\ln \mathrm{VIX}_t$
  (`calibrate_vix_betas`), clipped to $[0,2]$. Economically sensible on real data (e.g. JPM $\approx 0.67$,
  tech $\approx 0.3$, BTC $\approx 0.09$).
* $\overline{\mathrm{VIX}}$ — long-run VIX median; the ratio is **dimensionless** (clean, no unit reconciliation).
* $\rho$ — horizon decay (default 0.3): the spike carries full weight at step 1 and relaxes toward the GARCH
  forecast by week 12. Clip $[c_\text{lo},c_\text{hi}]=[0.5,3]$ guards against freak VIX prints.
* **$\gamma_i=0$ (or `vix_theta=None`) is an exact no-op** — verified — so it cannot silently change the model.
  Only $\theta$ is tilted; the current state $v_{0}$ is left untouched.

Wired via `sim_config['vix_theta']` in `MainOptimization.py` (toggle `USE_VIX_THETA`); applied to `theta_path`
inside `_simulate_heston_bates`.

---

## 4. Self-exciting (Hawkes) jump arrivals — clustering

The constant intensity $\lambda$ is replaced by a **discrete-time self-exciting intensity**, one per layer
(systematic & idiosyncratic):

$$\lambda_t = \lambda_\infty + (\lambda_{t-1}-\lambda_\infty)\,e^{-\alpha} + \beta\,\mathbf 1\{\text{jump at }t-1\}.$$

* $\lambda_\infty$ baseline rate, $\alpha$ decay, $\beta$ excitation. $\beta=0$ collapses to the legacy memoryless model.
* Stationarity requires branching ratio $\beta/(e^{\alpha}-1)<1$ (enforced at calibration).
* A jump raises next-step intensity by $\beta$, so crashes **cluster** — the dominant driver of deep, prolonged drawdowns.

Calibrated by Bernoulli MLE on the historical jump-indicator series (`calibrate_hawkes_from_indicators` in
`jump_paremeters.py`): systematic on the S&P residual series, idiosyncratic averaged across the veto-cleaned
"centurion" pool. Jump **magnitudes** still come from the tail-focused asymmetric GPD fit (paper §6) and are
scaled by the **stochastic** $\sqrt{v_{i,t}}$ (vs. the old deterministic $\sigma$).

---

## 5. Variance co-jumps (SVJJ)

On a **crash** arrival, variance receives a positive jump (Duffie–Pan–Singleton state-dependent jumps):

$$J^{v}_i = m\,\theta_i,\qquad m\sim \text{Exp}(\text{mean}=\text{var\_jump\_mult}).$$

Expressed as a multiple of each asset's long-run variance $\theta_i$, so it is dimensionless and scales across
assets. This makes the post-crash world genuinely more volatile, deepening and lengthening drawdowns.
`var_jump_mult` is calibrated from the average proportional rise in conditional variance in the week after a
$\le-3\sigma$ market move (`calibrate_cojump_multiplier`).

---

## 6. Discretisation

Per weekly step ($\Delta t=1$):

**Variance (CIR).** Two schemes (`scheme=`):
* `full_trunc` *(default)* — full-truncation Euler (Lord et al. 2010): coefficients use $v^+=\max(v,0)$, robust and leverage-exact.
  $$v_{t+1}=v_t+\kappa(\theta_t-v^+_t)\Delta t+\xi\sqrt{v^+_t}\sqrt{\Delta t}\,Z^{v}.$$
* `qe` — Andersen (2008) Quadratic-Exponential; more accurate in the variance tail when the Feller condition
  $2\kappa\theta\ge\xi^2$ is violated. Leverage enters through the quadratic branch.

**Price (jump-compensated, Ito-drag corrected).**
$$\ln\frac{S_{i,t+1}}{S_{i,t}} = \underbrace{\ln(1+\mu_i)}_{\text{BL drift}} - \tfrac12 v^+_{i,t}\Delta t - \underbrace{\lambda_{i,t}\,\mathbb E\!\left[e^{J_i\sqrt{v^+_{i,t}\tau}}-1\ \middle|\ \mathcal F_t\right]\Delta t}_{\text{jump compensator}} + \sqrt{v^+_{i,t}\Delta t}\,Z^{S}_i + \underbrace{J_i\sqrt{v^+_{i,t}\tau}}_{\text{vol-scaled jump}}.$$

The compensator must be the expectation of **exactly** what is injected, term for term. The log price
receives $J_i\sqrt{v^+_{i,t}\tau}$, so the correction is taken over $e^{J_i\sqrt{v^+_{i,t}\tau}}-1$ — not
over $e^{J_i}-1$. It is therefore **doubly adaptive**: time-varying through the Hawkes $\lambda_{i,t}$, and
**state-dependent** through the stochastic $\sqrt{v^+_{i,t}}$ *inside* the expectation.

### 6.1 Why the state dependence cannot be approximated away

Write $g(s)=\mathbb E[e^{Js}-1\mid\text{jump}]$. It is strongly convex in $s$ and it **changes sign**: with
the calibrated parameters it is negative below roughly 5.5% weekly vol (crash branch dominates — jumps are
net-negative, so the compensator *adds* drift back) and positive above it (the Pareto rally tail dominates,
so the compensator must *remove* drift).

v4.0 called `_layer_compensator` once, at a frozen representative vol $\sqrt{\theta_i}$, and reused that
constant at every step. That is exact only where $v_{i,t}\approx\theta_i$. It mis-sizes — and can mis-sign —
the correction in exactly the high-variance states the Hawkes excitation and the variance co-jumps exist to
produce, leaving a spurious upward drift inside crash clusters, which flatters CVaR and CDaR: the two
quantities the optimizer minimises.

v4.1 evaluates $g(\sqrt{v^+_{i,t}\tau})$ per asset, per path, per step, by linear interpolation of a
tabulation built once by `_compensator_grid` on a uniform grid in $s$ (`_interp_uniform` does the lookup;
it is pure indexing, so it runs unchanged on numpy and cupy). Three details:

* **Common random numbers across the grid** keep $g$ smooth in $s$; interpolation error is below
  $3\times10^{-4}$ at the top of the grid, negligible against the curvature.
* **The table is deterministic (fixed seed) and cached**, so the compensator is bit-identical between
  optimizer candidates. v4.0 resampled 20k draws per call, injecting fresh Monte-Carlo noise into every
  differential-evolution objective evaluation.
* **The grid top** is sized at $12\times\max(\sqrt{\theta},\sqrt{v_0})$ to cover the co-jump tail; beyond it
  the lookup extrapolates flat.

The idiosyncratic leg is now masked by the same `idio_jump_exclude` whitelist that suppresses idiosyncratic
jumps — v4.0 charged exempt assets a compensator for jumps they never received.

---

## 7. Validation (`validation_heston.py`)

Equal-weight portfolio, 261 weekly observations (2021-09-20 → 2026-09-14), common random numbers, 400k
paths, 12-week horizon. `mean|DD10` is the mean terminal return over the decile of paths with the deepest
maximum drawdown — the conditional column, see 7.1.

| Engine | mean_ret | std | CVaR(5%) | CDaR(5%) | exKurt | mean\|DD10 |
|---|---|---|---|---|---|---|
| 1. Legacy GBM | 0.0236 | 0.168 | −0.287 | −0.251 | 0.70 | −0.217 |
| 2. Heston (no jumps) | 0.0224 | 0.125 | −0.210 | −0.181 | 0.01 | −0.162 |
| 3. + Bates jumps | 0.0222 | 0.166 | −0.286 | −0.250 | 0.73 | −0.218 |
| 4. + Hawkes clustering | 0.0221 | 0.177 | −0.312 | −0.270 | 1.94 | −0.223 |
| 5. + Variance co-jumps | 0.0221 | 0.184 | −0.338 | −0.285 | 3.62 | −0.234 |

* Pure Heston is near-Gaussian (kurtosis ≈ 0); each component **monotonically deepens** tail risk and fattens kurtosis.
* Bates-memoryless (#3) ≈ legacy (#1) → the new engine is a faithful superset of the old one.

### 7.1 What the invariant mean does and does not prove

The mean holds at 0.0221–0.0222 across rows 3–5, the three engines that contain jumps. **v4.0 read that
flatness as proof the compensator was correct. It is weaker evidence than it looks** — the same argument
would have passed a compensator that was wrong, and did.

Re-running the identical ladder with the v4.0 frozen-$\sqrt{\theta}$ compensator, same cached inputs, same
seeds: rows 1–2 are untouched (no jumps, no compensator), rows 3–4 move in the fourth decimal, and the whole
effect lands on row 5 — the only engine where variance co-jumps push $v_{i,t}$ far above $\theta_i$.

| Row 5 (full engine) | v4.0 frozen √θ | v4.1 state-dependent | change |
|---|---|---|---|
| mean_ret | 0.0232 | 0.0221 | −0.0011 |
| CVaR(5%) | −0.3342 | −0.3381 | −1.2% |
| CDaR(5%) | −0.2829 | −0.2853 | −0.9% |
| exKurt | 3.46 | 3.62 | +4.5% |
| mean\|DD10 | −0.2299 | −0.2340 | −1.8% |

Under v4.0 the mean runs 0.0223, 0.0223, **0.0232** down rows 3–5: flat while variance stays near θ, then
**up 9 bp the moment co-jumps are switched on**, back toward the jump-free legacy figure. That is the
signature of the bias — the engine that should look worst instead recovers drift — and v4.0 reported it as
noise. Under v4.1 the same rows read 0.0222, 0.0221, 0.0221, and every risk measure moves against the
portfolio, because the optimistic drift that was flattering them is gone.

An unconditional mean over 400k paths is a weak test of a correction whose error lives in the tail. The fix
is not more paths, it is the conditional column: on the worst-drawdown decile the bias is a clean 41 bp.

### 7.2 Does the vol-dependent charge reach the allocation? (No)

Making the compensator state-dependent has a side effect worth naming. Because `g` crosses zero near 5.5%
weekly vol, the compensator **charges** drift to names whose variance sits above that line and **credits**
it to names below. On the validation panel, over the 12-week horizon:

| asset | weekly vol | drift charged over 12wk |
|---|---|---|
| PLTR | 9.1% | −0.540% |
| BTC=F | 7.2% | −0.204% |
| META | 6.0% | −0.069% |
| NVDA | 6.4% | −0.018% |
| GOOGL | 4.5% | +0.064% |
| FERG | 4.1% | +0.084% |
| JPM | 3.5% | +0.115% |

Where that crossover sits is governed by `rally_shape` — a parameter picked for tail realism, with no
thought to capital allocation. So: does it reach the weights?

**It does not.** Full DE optimizer, three rally shapes × three seeds, 400k paths per objective evaluation,
15 generations, popsize 12, everything else pinned. The three seeds at a fixed shape give the optimizer's
own noise floor (DE is stochastic and the MC objective is noisy).

| ticker | 0.08 | 0.12 (base) | 0.16 | Δ |
|---|---|---|---|---|
| PLTR | 3.61% | 2.65% | 2.78% | −0.82 pp |
| NVDA | 13.64% | 12.91% | 12.32% | −1.32 pp |
| META | 10.96% | 12.13% | 12.42% | +1.46 pp |
| JPM | 24.37% | 23.39% | 23.20% | −1.16 pp |
| GOOGL | 18.09% | 18.37% | 18.60% | +0.50 pp |
| FERG | 18.63% | 19.53% | 19.11% | +0.49 pp |
| BTC=F | 10.71% | 11.00% | 11.57% | +0.86 pp |

* within-group spread (same shape, different seed): **1.25 pp** avg per name
* between-group spread (attributable to the shape): **0.53 pp** avg per name — **0.42x the noise floor**
* L1 turnover 0.08 → 0.16: **6.6 pp** across the whole book

Doubling the rally shape moves the allocation less than half as much as changing the seed. Two details
sharpen it: one seed returned the *identical* weight vector at all three shapes (the objective does respond
monotonically — −0.04813 → −0.04805 → −0.04797 — but over 15 generations the difference never flipped a
single accept/reject decision), and the cross-sectional tilt does not appear cleanly, since PLTR falls as
the rally tail fattens while BTC=F, also high-vol and also charged, rises.

**No adjustment made.** Capping the vol that sizes jumps, making that scaling sub-proportional, or
asymmetrising the magnitude cap would each be engineering around a bias that never reaches the decision.

*Caveat:* run at 400k paths / popsize 12, not production 3M / popsize 30, so the noise floor here is wider
than production's. A larger simulation shrinks the floor while leaving the signal, so the 0.42x ratio would
rise. The absolute 0.53 pp is the robust number, and it is small at any floor. Re-run this if the jump
calibration changes materially.

---

## 8. Code map

| Concern | Location |
|---|---|
| Robust data panel (heterogeneous histories) | `ret_df`, `_batch_close`, `_coverage_report`, `_nearest_psd_corr` |
| Per-asset GARCH-X + standardized residuals | `fit_garch_with_exog` |
| DCC forecast (covariance **and** correlation $R_t$) | `forecast_dcc` |
| Heston parameter calibration | `calibrate_heston_params` |
| Hawkes / co-jump calibration | `jump_paremeters.py`: `calibrate_hawkes_from_indicators`, `calibrate_cojump_multiplier` |
| Hybrid DCC-Heston-Bates simulator | `_simulate_heston_bates` (dispatched from `monte_carlo_simulation`) |
| Jump compensator (tabulation, lookup) | `_compensator_grid`, `_interp_uniform` (`_layer_compensator` kept for diagnostics) |
| Idiosyncratic-jump whitelist | `idio_jump_exclude` arg (both engines); CSV column `exclude_idio_jump` |
| Wiring / config | `MainOptimization.py` → `sim_config` → `run_optimization` → objectives |

### GPU cost vs. the legacy engine (measured, RTX 3060 Laptop 6 GB)
Optimization-mode call, N=7, S=12: Heston-Bates is **~2.6× slower / 1.8× VRAM** (`full_trunc`) or **~3.3× / 2.1×**
(`qe`) vs. legacy GBM. VRAM scales linearly with sims (≈0.85 GB per 1M paths, `full_trunc`). The default
`num_simulations_for_cvar` is therefore set to **4M** (~3.4 GB peak) to stay under a 4.5 GB budget on 6 GB cards;
raise it on larger GPUs. The `differential_evolution` optimizer runs **one fresh simulation per candidate weight
vector**, so the per-call cost multiplies by the number of objective evaluations.

> Setting `heston_config=None` (i.e. no `sim_config`) falls back to the original GBM engine, so A/B
> comparisons and the legacy behaviour remain available unchanged.

---

## 9. Ideas for further development

* **Options-implied (Q-measure) calibration** of $v_0,\theta,\rho$ from the live IV surface (ties into the
  `implied-probability-density` repo) with a market-price-of-vol-risk adjustment back to P.
* **Cross-asset variance correlation / common variance factor** (currently variance shocks are correlated only
  indirectly through the price block).
* **Regime-switching $\theta$** (calm/crisis Markov states).
* **Backtested risk coverage** — Kupiec POF & Christoffersen independence tests on CVaR/CDaR.
* **Rough volatility** (fractional / rough Heston) for more realistic short-horizon vol dynamics.

### Known remaining approximations

* `total_shock` is clipped to ±5 in log space while the compensator integrates the unclipped jump law. The
  clip corresponds to a 148× move and effectively never binds at calibrated vols, but the two are not
  formally consistent.
* Jump magnitudes are fitted to |z| > 3 exceedances of GARCH residuals, while the simulated diffusion is
  Gaussian, which itself puts ~0.27% of weekly mass beyond |z| = 3. The region just above the threshold is
  therefore mildly double-counted relative to λ.
* `gen_jumps` draws `u` clipped to [1e-7, 1.0]; at u = 1 the Pareto inverse-CDF divides by zero and emits a
  RuntimeWarning on the numpy path. The result is +inf, which the outer `clip(..., thr, 8.0)` maps to the
  magnitude cap, so the sampled value is correct — but the upper clip should be 1 − 1e-7.
