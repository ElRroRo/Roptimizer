"""Slice 2's A100 measurements, four runs on one plain A100 VM (one start-up for all four):

  1 flat    the reference inputs as a flat portfolio, 30M bank, 3M draws, re-scored on 3 x 10M fresh paths
            (the flat regression check, the way the reference answer was re-scored)
  2 tree    the reference tree (benchmarks/reference/tree.json), default stop rule, 10 noise draws per search
  3 repeat  the same tree and seed again (the same seed must give the same answer)
  4 study   the same tree with the stop rule off (tol=-1) to the 80-generation cap, every generation's
            incumbent scored on the held-out paths, 10 noise draws per search (the stop-rule study)

Usage (repo root): .venv/bin/python benchmarks/checks/slice2/a100_runs.py benchmarks/results [run names...]
Writes slice2-a100-<run>.json and slice2-a100[-<runs>].colab.log there, and prints the CU measured. With
run names, only those runs (the first job's study was cut short on 2026-10-29 and rerun alone).
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from mso import colab, job  # noqa: E402

OUT = sys.argv[1]
SEED = "20261029"
base = ["run", "--snapshot", "inputs.json", "--machine", "local", "--profile", "a100", "--seed", SEED]
tree = base + ["--tree", "tree.json"]
RUNS = {
    "flat": base + ["--rescore-paths", "10000000", "--rescore-reps", "3", "--out", "flat.json"],
    "tree": tree + ["--noise", "10", "--out", "tree.json.out"],
    "repeat": tree + ["--noise", "10", "--out", "repeat.json"],
    "study": tree + ["--set", "tol=-1", "--set", "maxgen=80", "--trace", "--noise", "10", "--out", "study.json"],
}
if sys.argv[2:]:
    RUNS = {k: v for k, v in RUNS.items() if k in sys.argv[2:]}
tag = "" if len(RUNS) == 4 else "-" + "-".join(RUNS)
work = tempfile.mkdtemp(prefix="mso-slice2-")
script = os.path.join(work, "job.py")
size = job.build(script, {"inputs.json": "benchmarks/reference/inputs.json", "tree.json": "benchmarks/reference/tree.json"},
                 list(RUNS.values()))
session = f"{colab.SESSION_PREFIX}slice2-{time.strftime('%Y%m%d-%H%M%S')}"
before = colab.usage()
print(f"[a100] {session}: payload {size / 1024:.0f} KiB, balance before {before['balance']:.2f} CU", flush=True)
log = open(os.path.join(OUT, f"slice2-a100{tag}.colab.log"), "w")
t0 = time.time()
try:
    code, out = colab.run(script, session, on_line=lambda l: (log.write(l + "\n"), log.flush(),
                                                              print(l, flush=True) if not l.startswith(("@@MSO", "MSO-", " ")) and len(l) < 300 else None),
                          on_wait=lambda n, d: print(f"[a100] waiting for an A100 (attempt {n}, retry in {d} s)", flush=True))
finally:
    stopped, others = colab.sweep([session])
    print(f"[a100] own session stopped after the job: {stopped or 'none left running'}; other mso sessions: {others or 'none'}", flush=True)
wall = time.time() - t0
after = colab.usage()
results = job.extract_all(out)
for i, name in enumerate(RUNS):
    if i in results:
        r = results[i]
        r["colab"] = dict(session=session, job_wall_s=round(wall, 1))
        json.dump(r, open(os.path.join(OUT, f"slice2-a100-{name}.json"), "w"), indent=1)
summary = dict(session=session, exit=code, wall_s=round(wall, 1), balance_before=before["balance"],
               balance_after=after["balance"], cu_measured=round(before["balance"] - after["balance"], 2),
               cu_at_rate=round(wall / 3600 * colab.RATE_CU_PER_HOUR, 2),
               results=[n for i, n in enumerate(RUNS) if i in results])
json.dump(summary, open(os.path.join(OUT, f"slice2-a100{tag}-job.json"), "w"), indent=1)
print(f"[a100] done: exit {code}, {wall:.0f} s, {summary['cu_measured']} CU measured "
      f"({before['balance']:.2f} -> {after['balance']:.2f}); results: {summary['results']}", flush=True)
