# Roptimizer glossary

A jump-sensitive portfolio optimizer. From v5.0 a portfolio is a tree: groups of assets are optimized, frozen, and then treated as single assets by the level above.

## The tree

**Portfolio**:
The top of the tree, and the thing the final allocation is for. One saved entry in the library.
_Avoid_: book, fund

**Subportfolio**:
A named group inside a portfolio that is optimized on its own, then frozen at those weights and treated as one asset by the level above it. It may hold assets, other subportfolios, or both, nested to any depth; a "parent subportfolio" is just a subportfolio that holds subportfolios.
_Avoid_: sleeve, basket, bucket, group, parent subportfolio (as a separate concept)

**Asset**:
A single ticker at the bottom of the tree; the only thing that is simulated directly. An asset appears at most once in a portfolio.
_Avoid_: holding, position, instrument

**Level**:
How deep an asset or subportfolio sits in the tree. Indentation is how the interface shows and changes it.
_Avoid_: layer, tier, indentation (as a term)

## Expectations

**Equilibrium return**:
The annual return an asset is expected to earn absent any manager opinion; the anchor every view is blended with.
_Avoid_: prior, base return

**View**:
A manager's own annual expected return for an asset or for a subportfolio as a whole. Asset views say how names compare inside a group; a view on a subportfolio is a call on the group itself, and only changes how much its parent gives it.
_Avoid_: analyst view, opinion, target, macro view (as a separate concept)

**Target price**:
A view written as a price instead of a return: the manager's most likely price at the view's horizon. It and the return it implies are two forms of the same view.
_Avoid_: price target, fair value (as the input's name)

**View uncertainty**:
The standard deviation of a view: how far, in annual return points (or in price), the manager's estimate could be off. "35% with uncertainty 10%" means 35% give or take 10 points. It may differ below and above the view, in which case the view is the most likely value and the model centres on the average it implies. It is uncertainty about the estimate, never the range the asset's price may end up in.
_Avoid_: view volatility, view stdev, confidence, bear/bull range

**Posterior return**:
The expected return used by the optimizer after blending the equilibrium return with every view.
_Avoid_: expected return (alone), blended return

**Posterior uncertainty**:
How far a posterior return could be off, as implied by the equilibrium anchor and the views together. Much narrower than a view uncertainty, because the equilibrium anchor is held tightly.
_Avoid_: view uncertainty (a different, wider thing), return error

**Implied return**:
What a subportfolio's contents are expected to earn: its assets' posterior returns at its frozen mix, with their posterior uncertainty. It is what the parent expects of the subportfolio before any view on the subportfolio itself.
_Avoid_: equilibrium return of a subportfolio, group return

## Jumps

**Jump database**:
The dated, stored record of market-wide jump behaviour (how often and how hard the market and single stocks jump) and of each asset's reaction to market jumps. Refreshed by hand every few months; a run names the version it used.
_Avoid_: jump parameters (as the stored thing), jump config, calibration (as a noun for the stored result)

**Surprise day**:
A day on which the S&P 500 moved by more than three times its volatility at that moment, down (a crash) or up (a rally). The model's notion of a market jump.
_Avoid_: crash day (alone), tail day, jump day

**Crash beta**:
How much an asset moves on crash surprise days relative to the market's move. **Rally beta** is the same on rally surprise days.
_Avoid_: jump beta, downside beta, liar ratio

**Co-jump**:
The jump in an asset's own variance on a market crash: how much more volatile it becomes the week after, as a multiple of its variance at that moment. Measured per asset; an asset with too little history takes the market's.
_Avoid_: variance jump, vol spike

**Constant-variance asset**:
An asset whose volatility model found no response to shocks on its own history, so its variance is held at its realized level, with how fast and how much it varies borrowed from the portfolio's other assets ("pooled"). Always labelled.
_Avoid_: failed fit, flat vol

## Optimization

**Limit**:
A minimum or maximum share for a child, measured against its parent or, when stated, against the whole portfolio.
_Avoid_: constraint, bound, cap (as separate terms)

**Scenario bank**:
The large stored set of simulated futures for every asset in a portfolio, all simulated together so their co-movements are kept. Every candidate mix is scored on scenarios taken from it; nothing is re-simulated while optimizing.
_Avoid_: simulation set, path bank, Monte Carlo sample

**Search**:
One run of the optimizer that finds a single subportfolio's (or the portfolio's) weights.
_Avoid_: optimization run, solve

**Draw**:
The fresh subset of the scenario bank that one generation of a search is scored on (3 million paths on the A100, 1 million on the laptop). Every candidate in a generation sees the same draw.
_Avoid_: sample, batch

**Held-out paths**:
The tenth of the scenario bank no search ever scores on. Every figure a run reports comes from these paths, so no number is measured on the paths it was chosen on.
_Avoid_: test set, validation set (as the user-facing term)

**Stop rule**:
A search stops when its best score has improved by less than 0.0002 over the last 5 generations, or at 80 generations.
_Avoid_: convergence criterion, early stopping

**Sensitivity band**:
The range a weight moves over when a search is repeated with posterior returns drawn within their posterior uncertainty. Shown beside the answer and never replaces it: the frozen weights always come from one search on the posterior returns themselves. Each level's band is measured with the subportfolios below it already frozen.
_Avoid_: robust mode, resampled weights, confidence interval, Michaud

## Results

**CDaR**:
Conditional drawdown at risk: across the worst 5% of simulated scenarios, the average of each scenario's deepest fall from a peak over the horizon.
_Avoid_: drawdown risk, expected drawdown

**Effective weight**:
An asset's share of the whole portfolio: the product of every weight on the path from the portfolio down to it.
_Avoid_: total weight, look-through weight

**Run**:
One complete optimization of a portfolio: every search in its tree, on one scenario bank, with its inputs recorded so it can be reopened and compared.
_Avoid_: job (the machine's unit of work), optimization (alone)

**Machine**:
Where a run goes: the laptop GPU (a draft, up to about 2 million paths) or a Colab A100 (production, 30 million paths). Both use the same frozen inputs, so their answers differ only by the scenarios.
_Avoid_: backend, device, target

**Frozen inputs**:
Everything a run uses, saved with it when it starts: the portfolio as it was, the day's market data and fits, the jump database version and the seed. A run can be repeated from them exactly.
_Avoid_: snapshot (alone), cache

**Builder**:
The part of a run's results that turns effective weights into dollars and share counts for a chosen portfolio size.
_Avoid_: order list, trade list, rebalancer

**Trade-as ticker**:
The instrument actually bought for an asset when the builder counts shares, when it differs from the ticker the model simulates (a bitcoin ETF for bitcoin futures).
_Avoid_: proxy, substitute ticker
