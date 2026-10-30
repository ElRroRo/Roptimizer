"""The day-keyed market-data cache (#9): the first run of a day downloads, later runs that day reuse it.

One gzip CSV per (ticker, method, period, interval) under cache/market/<YYYY-MM-DD>/, with an index.json
recording when each file was downloaded. A ticker added mid-day downloads only itself. "Refresh data"
(DayCache.refresh) re-downloads the day. An A100 job gets the day folder its run uses and opens it
offline, so it never calls Yahoo: an offline miss raises, naming the ticker.

Methods mirror the two yfinance calls the engine makes:
  download  yf.download([t], ...)["Close"]   (the weekly panels; per ticker, the same union grid as a batch)
  history   yf.Ticker(t).history(...)["Close"]   (^VIX, ^TNX, daily histories for the betas)
"""
import datetime as dt
import json
import os
import re
import threading

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "market")


class OfflineMiss(RuntimeError):
    """A series was asked for that the (offline) cache does not hold."""


def _safe(ticker):
    return re.sub(r"[^A-Za-z0-9._-]", lambda m: f"%{ord(m.group()):02X}", ticker)


class DayCache:
    def __init__(self, day=None, root=ROOT, offline=False):
        self.day = day or dt.date.today().isoformat()
        self.dir = os.path.join(root, self.day)
        self.offline = offline
        self.hits, self.misses = 0, []
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)
        self._index_path = os.path.join(self.dir, "index.json")
        try:
            with open(self._index_path) as f:
                self.index = json.load(f)
        except (OSError, ValueError):
            self.index = {}

    def _key(self, ticker, method, period, interval):
        return f"{_safe(ticker)}__{method}_{period}_{interval}"

    def _fetch(self, ticker, method, period, interval):
        import yfinance as yf
        if method == "download":
            s = yf.download([ticker], period=period, interval=interval, auto_adjust=True, progress=False)["Close"]
            s = s[ticker] if isinstance(s, pd.DataFrame) else s
        elif method == "history":
            s = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)["Close"]
        else:
            raise ValueError(f"unknown method {method!r}")
        if s is None or s.dropna().empty:
            raise ValueError(f"No price history for {ticker} ({method} {period} {interval}): "
                             f"unknown, delisted or mistyped ticker")
        s = s.copy()
        s.name = ticker
        return s

    def close(self, ticker, period, interval, method="download"):
        """The Close series for one ticker, from today's cache or downloaded into it."""
        key = self._key(ticker, method, period, interval)
        path = os.path.join(self.dir, key + ".csv.gz")
        with self._lock:
            if key in self.index and os.path.exists(path):
                self.hits += 1
                s = pd.read_csv(path, index_col=0, parse_dates=False, float_precision="round_trip")[ticker]
                s.index = pd.to_datetime(s.index, utc=self.index[key].get("tz") is not None)
                if self.index[key].get("tz"):
                    s.index = s.index.tz_convert(self.index[key]["tz"])
                return s
            if self.offline:
                raise OfflineMiss(f"{ticker} ({method} {period} {interval}) is not in the cache for {self.day}")
        s = self._fetch(ticker, method, period, interval)
        tz = str(s.index.tz) if getattr(s.index, "tz", None) is not None else None
        tmp = path + ".tmp"
        s.to_frame().to_csv(tmp, compression="gzip")
        os.replace(tmp, path)
        with self._lock:
            self.misses.append(key)
            self.index[key] = dict(ticker=ticker, method=method, period=period, interval=interval, tz=tz,
                                   downloaded=dt.datetime.now().isoformat(timespec="seconds"), rows=int(len(s)))
            self._save_index()
        return s

    def _save_index(self):
        tmp = self._index_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.index, f, indent=1)
        os.replace(tmp, self._index_path)

    def last_price(self, ticker):
        """Last close in the day's data and its time (the builder's price and every trade-as ticker's)."""
        s = self.close(ticker, "5d", "1d").dropna()
        if s.empty:
            raise ValueError(f"No recent price for {ticker}")
        return float(s.iloc[-1]), str(s.index[-1])

    def downloaded_at(self):
        """The earliest download time of the day's data (what the pre-run review shows), or None."""
        times = [v["downloaded"] for v in self.index.values()]
        return min(times) if times else None

    def refresh(self):
        """Refresh data: drop the day's files so every series downloads again on next use."""
        with self._lock:
            for key in list(self.index):
                p = os.path.join(self.dir, key + ".csv.gz")
                if os.path.exists(p):
                    os.remove(p)
            self.index = {}
            self._save_index()


_active = None


def use(cache):
    """Route mso.data's downloads through `cache` (None: download directly, as v4.1 did)."""
    global _active
    _active = cache
    return cache


def active():
    return _active
