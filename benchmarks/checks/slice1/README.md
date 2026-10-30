# Slice 1 checks

Each script takes an output folder as its only argument and writes its JSON there (the results of the
2026-10-29 runs are in `benchmarks/results/slice1-checks/`). Run from the repo root with the repo's `.venv`.

- `calib_equiv.py`: v4.1's `jump_paremeters.py` and `mso.jumpdb.calibrate` on the same downloaded data must give
  identical JUMP, HAWKES and COJUMP configs. Put the old module in the output folder first:
  `git show 8ce47e0:jump_paremeters.py > <out>/old_jump_paremeters.py`. Also compares today's values with the
  frozen ones in `benchmarks/reference/inputs.json`.
- `beta_check.py`: the 16 portfolio tickers' normal, crash and rally betas against the table posted on #9.
- `second_run.py`: builds the inputs twice; the second build runs with the day cache offline and yfinance
  disabled, and must download nothing and give identical inputs.
- `posterior_check.py`: with per-asset betas and co-jumps on, each asset's simulated 12-week mean against its
  posterior, in standard errors (2M paths), beside the same inputs with betas removed.
