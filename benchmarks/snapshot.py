"""Freeze every input the optimizer sees, so a run can be repeated on the same data on any machine.

Runs the real input pipeline (mso.pipeline.build_inputs: downloads, GARCH/GJR, DCC, Heston, VIX tilt,
Black-Litterman, jump calibration), the same one MainOptimization.py runs before differential
evolution, and writes the arguments of run_optimization to JSON. Market data moves every week; the reference answer is only reproducible
against a frozen snapshot.

Usage (repo root):  MPLBACKEND=Agg .venv/bin/python benchmarks/snapshot.py benchmarks/reference/inputs.json
"""
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def encode(o):
    if isinstance(o, pd.DataFrame):
        return {"__df__": o.values.tolist(), "index": [str(i) for i in o.index], "columns": list(o.columns)}
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, dict):
        return {k: encode(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [encode(v) for v in o]
    return o


def main(out_path):
    from mso.pipeline import build_inputs

    inputs, vintage = build_inputs("portfolio_data.csv")
    snap = {"created": dt.datetime.now().isoformat(timespec="seconds"), **vintage,
            "run_optimization_kwargs": encode(inputs)}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(snap, f, indent=1)
    print(f"\n[snapshot] wrote {out_path}: {len(inputs['tickers'])} assets, data through {vintage.get('last_return_week')}")


if __name__ == "__main__":
    main(sys.argv[1])
