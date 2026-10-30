"""Stop-rule study summary: where the 5-generation / 0.0002 rule stops each search, and what the held-out
objective is there versus at generation 80 and at its best."""
import json, sys
import numpy as np
d = json.load(open(sys.argv[1]))
W, TOL = 5, 0.0002
for r in d["rows"]:
    s = r.get("search") or {}
    if "history" not in s or not s.get("held_out_trace"):
        continue
    h, v = s["history"], s["held_out_trace"]
    stop = next((g for g in range(W + 1, len(h) + 1) if h[g - 1 - W] - h[g - 1] < TOL), None)
    sd = s.get("noise", {}).get("sd")
    best = int(np.argmin(v)) + 1
    print(f"{' / '.join(r['path'][1:]) or 'Portfolio':40} rule stops at gen {stop}: held-out {v[stop - 1]:+.5f} | gen 80 {v[-1]:+.5f} "
          f"| best {min(v):+.5f} (gen {best}) | loss at stop vs gen 80 {v[stop - 1] - v[-1]:+.5f} | draw SD {sd:.5f} | {s['s_per_gen']} s/gen")
