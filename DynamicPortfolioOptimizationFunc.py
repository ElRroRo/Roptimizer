"""Compatibility shim: the engine now lives in the `mso` package (v5.0, build slice 0).

`from DynamicPortfolioOptimizationFunc import *` and `import DynamicPortfolioOptimizationFunc as d` keep
working for MainOptimization.py, jump_paremeters.py, validation_heston.py, paper/ and the notebooks:
every name of the old module, private ones included, is re-exported from where it moved.

To swap a function out (as the benchmarks swap the simulator for a bank lookup), patch the module that
calls it, e.g. `mso.sim.monte_carlo_simulation` or `mso.metrics.portfolio_cdar_objective`. Patching it
here changes nothing, because the engine no longer looks names up in this module.
"""
from mso import bl, data, fits, legacy, metrics, plots, sim

for _m in (data, fits, bl, sim, metrics, legacy, plots):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})
del _m
