"""First build of the day downloads; the second must download nothing (offline cache, yfinance disabled)."""
import io, contextlib, json, sys, time
sys.path.insert(0, ".")
from mso import pipeline
from mso.cache import DayCache
t = time.perf_counter()
c1 = DayCache()
before = len(c1.index)
inputs1, rec1 = pipeline.build_inputs("portfolio_data.csv", day_cache=c1)
t1 = time.perf_counter() - t
import yfinance as yf
def blocked(*a, **k):
    raise RuntimeError("network call during the second build")
yf.download = blocked
yf.Ticker = blocked
t = time.perf_counter()
c2 = DayCache(offline=True)
log = io.StringIO()
with contextlib.redirect_stdout(log):
    inputs2, rec2 = pipeline.build_inputs("portfolio_data.csv", day_cache=c2)
t2 = time.perf_counter() - t
same = (inputs1["rf_rate"] == inputs2["rf_rate"] and list(inputs1["drift"]) == list(inputs2["drift"])
        and inputs1["initial_prices"] == inputs2["initial_prices"]
        and inputs1["sim_config"]["jump_betas"] == inputs2["sim_config"]["jump_betas"])
out = dict(first_build_s=round(t1, 1), first_downloads=rec1["downloads_this_build"], cached_before_first=before,
           second_build_s=round(t2, 1), second_downloads=rec2["downloads_this_build"], second_cache_hits=c2.hits,
           identical_inputs=same, jump_version=rec2["jump_version"], data_day=rec2["data_day"],
           data_downloaded=rec2["data_downloaded"], betas=rec2["betas"])
json.dump(out, open(f"{sys.argv[1]}/second_run.json", "w"), indent=1, default=str)
print({k: v for k, v in out.items() if k != "betas"})
