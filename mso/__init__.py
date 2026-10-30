"""Multi-Stage Optimization with Jump Process: the v5.0 engine package.

Modules: data (market data), fits (GARCH/GJR-X, DCC, Heston, VIX betas), bl (Black-Litterman),
sim (Monte Carlo simulators), metrics (risk on simulated paths, v4.1 objectives), legacy (v4.1 SciPy
optimizer), plots, pipeline (CSV -> optimizer inputs), bank (scenario bank), search (the v5.0 DE loop),
report (held-out metrics per row), events (the @@MSO progress protocol), cli (`python -m mso`).
"""
__version__ = "5.0.0.dev0"
