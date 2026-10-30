# Benchmarks and the v5.0 reference answer

- `snapshot.py` runs the real v4.1 pipeline and freezes everything the optimizer sees into
  `reference/inputs.json` (16 assets, data through the week of 2026-10-19). Market data moves weekly,
  so comparisons are only meaningful on this frozen file.
- `bench.py` times scenario-bank generation, one objective evaluation, scoring from a stored bank, and
  optionally runs the full optimizer. Every number it prints is measured on the machine running it.
- `make_job.py` packs the engine, `bench.py` and a snapshot into one script for `colab run`, which ships
  only the script file. Results come back on stdout between `BENCH-JSON` markers.
- `reference/answer.json` is the reference answer: the fixed v4.1 optimizer (commit d731e48) at
  production settings (3M paths, 15 generations, popsize 30, seed 20261027) on the plain A100.
  Its weights are one seeded draw of a noisy search, so compare a v5.0 answer by objective value at
  10M paths (reference: -0.08833, SD 0.00004 across three rescorings), not weight by weight.
- `results/` holds the raw measurements from the laptop and the A100, and the A100 job's stdout.

Laptop: `MPLBACKEND=Agg .venv/bin/python benchmarks/bench.py --snapshot benchmarks/reference/inputs.json --bank-paths 2000000 --bank-chunk 500000 --eval-paths 2000000 --bank-eval-paths 2000000`
