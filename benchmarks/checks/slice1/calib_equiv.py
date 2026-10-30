"""Old jump_paremeters.py vs mso.jumpdb.calibrate on the same downloaded data."""
import json, pickle, sys, os, time
sys.path.insert(0, ".")
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf
from mso import jumpdb
S = sys.argv[1]
pool = jumpdb.default_pool()["tickers"]
t = time.perf_counter()
sys_data, idio_data = jumpdb.download(pool)
print(f"download {time.perf_counter()-t:.1f} s, idio columns {idio_data.shape[1]}", flush=True)
pickle.dump((sys_data, idio_data), open(f"{S}/calib_data.pkl", "wb"))
t = time.perf_counter()
new = jumpdb.calibrate(sys_data, idio_data, pool, verbose=False)
print(f"new calibrate {time.perf_counter()-t:.1f} s", flush=True)
real_download = yf.download
def served(tickers, *a, **k):
    tickers = list(tickers) if not isinstance(tickers, str) else [tickers]
    if tickers == ["^GSPC"]:
        return {"Close": sys_data}
    assert set(tickers) == set(pool), "unexpected tickers"
    return {"Close": idio_data}
yf.download = served
plt.show = lambda *a, **k: None
ns = {"__name__": "old_jump_paremeters"}
t = time.perf_counter()
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(open(f"{S}/old_jump_paremeters.py").read(), "old_jump_paremeters.py", "exec"), ns)
yf.download = real_download
print(f"old module {time.perf_counter()-t:.1f} s", flush=True)
same = dict(jump=ns["JUMP_CONFIG"] == new["jump_config"], hawkes=ns["HAWKES_CONFIG"] == new["hawkes_config"],
            cojump=ns["COJUMP_CONFIG"] == new["cojump_config"])
print("identical:", same)
ref = json.load(open("benchmarks/reference/inputs.json"))["run_optimization_kwargs"]
out = dict(identical=same, new=dict(jump=new["jump_config"], hawkes=new["hawkes_config"], cojump=new["cojump_config"]),
           frozen=dict(jump=ref["jump_config"], hawkes=ref["sim_config"]["hawkes_config"], cojump=ref["sim_config"]["cojump_config"]),
           diagnostics=new["diagnostics"], windows=new["windows"])
json.dump(jumpdb._plain(out), open(f"{S}/calib_equiv.json", "w"), indent=1)
