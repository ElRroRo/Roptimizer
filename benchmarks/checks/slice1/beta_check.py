import sys, json, time; sys.path.insert(0, ".")
from mso import betas
from mso.cache import DayCache
T9 = {  # #9's table, 2026-10-28: normal, GARCH crash (n), GARCH rally (n)
 "NVDA": (1.64, 1.72, 54, 2.14, 6), "MNTS": (1.25, 0.91, 20, 1.25, 2), "META": (1.27, 1.34, 37, 1.43, 4),
 "JPM": (1.30, 1.17, 80, 1.01, 23), "GOOGL": (1.02, 1.10, 49, 1.17, 4), "FERG": (0.37, 0.42, 43, 1.12, 4),
 "BTC=F": (0.94, 0.82, 25, 1.40, 2), "ADBE": (1.30, 1.22, 76, 1.42, 12), "NRIM": (0.44, 0.50, 67, 0.30, 8),
 "SPGI": (0.92, 0.98, 84, 0.81, 26), "DBMF": (0.12, 0.34, 22, -0.14, 2), "CTA": (-0.17, 0.17, 11, -0.18, 2),
 "WTMF": (0.06, 0.12, 42, 0.12, 4), "TLT": (-0.23, -0.28, 49, 0.10, 4), "IBHK": (0.24, 0.19, 9, 0.30, 1),
 "SPY": (1.00, 1.01, 65, 1.01, 6)}
c = DayCache()
t = time.perf_counter()
m = betas.surprise_days(c)
print(f"S&P since {m[0].index[0].date()}: {len(m[1])} crash, {len(m[2])} rally surprise days")
worst = 0; out = {}
for tk, (n9, c9, nc9, r9, nr9) in T9.items():
    r = betas.raw_betas(tk, c, m); out[tk] = r
    d = max(abs(round(r["normal"], 2) - n9), abs(round(r["crash"], 2) - c9), abs(round(r["rally"], 2) - r9))
    worst = max(worst, d)
    flag = "" if (d <= 0.011 and r["crash_days"] == nc9 and r["rally_days"] == nr9) else "  <-- differs"
    print(f"{tk:6} normal {r['normal']:.2f} ({n9})  crash {r['crash']:.2f}/{r['crash_days']} ({c9}/{nc9})  rally {r['rally']:.2f}/{r['rally_days']} ({r9}/{nr9}){flag}")
print(f"largest difference after rounding: {worst:.2f}; {time.perf_counter()-t:.1f} s; downloads {len(c.misses)}")
json.dump(out, open(f"{sys.argv[1]}/beta_check.json", "w"), indent=1)
