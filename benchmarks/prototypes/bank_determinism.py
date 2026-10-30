"""Is the bank reproducible from its seed on the same machine? Build 500k paths twice with one seed,
once with another, and compare."""
import sys
sys.path.insert(0, "benchmarks"); sys.path.insert(0, ".")
import cupy as cp
import numpy as np
import bench
from load_snapshot import load

snap, kw = load("benchmarks/reference/inputs.json")
out = []
for seed in (11, 11, 12):
    cp.random.seed(seed)
    np.random.seed(seed)
    out.append(bench.bank(kw, 500_000, 500_000, keep=True))
print("same seed identical:", bool(np.array_equal(out[0], out[1])),
      "max abs diff:", float(np.max(np.abs(out[0] - out[1]))))
print("other seed differs:", not np.array_equal(out[0], out[2]))
