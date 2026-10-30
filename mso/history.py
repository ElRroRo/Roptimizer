"""Price history for the screens (the instrument cards, the correlation and drawdown panels): weekly
auto-adjusted closes over 5 years from the day cache, in the shape the accepted designs read (#12's hist.js):
{fetched, source, tickers, series: {t: {start, end, n, dates, close, dd, vol, maxdd}}, corr, overlap}.
corr is the pairwise correlation of weekly log returns over each pair's overlap; overlap counts those weeks.
"""
import numpy as np
import pandas as pd

from mso.data import drop_incomplete_week


def build(tickers, cache, period="5y"):
    closes = {}
    for t in tickers:
        s = drop_incomplete_week(cache.close(t, period, "1wk", "download").dropna())
        s.index = pd.to_datetime(s.index)
        closes[t] = s
    series, rets = {}, {}
    for t, s in closes.items():
        c = s.values.astype(float)
        peak = np.maximum.accumulate(c)
        dd = c / peak - 1
        r = np.log(s / s.shift(1)).dropna()
        rets[t] = r
        series[t] = dict(start=str(s.index[0].date()), end=str(s.index[-1].date()), n=int(len(s)),
                         dates=[str(d.date()) for d in s.index], close=[round(float(x), 6) for x in c],
                         dd=[round(float(x), 4) for x in dd], vol=round(float(r.std() * np.sqrt(52)), 4),
                         maxdd=round(float(dd.min()), 4))
    n = len(tickers)
    corr, overlap = np.eye(n).tolist(), [[0] * n for _ in range(n)]
    for i, a in enumerate(tickers):
        for j, b in enumerate(tickers):
            j_ = pd.concat([rets[a], rets[b]], axis=1, join="inner").dropna()
            overlap[i][j] = int(len(j_))
            if i < j and len(j_) > 2:
                v = float(np.corrcoef(j_.iloc[:, 0], j_.iloc[:, 1])[0, 1])
                corr[i][j] = corr[j][i] = round(v, 3)
    downloaded = [v["downloaded"] for v in cache.index.values()]
    return dict(fetched=(min(downloaded)[:16].replace("T", " ") if downloaded else cache.day),
                source=f"Yahoo Finance via yfinance, weekly auto-adjusted closes, period {period}",
                tickers=list(tickers), series=series, corr=corr, overlap=overlap)
