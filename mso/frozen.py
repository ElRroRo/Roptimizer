"""Frozen inputs: the optimizer's inputs written to JSON and read back exactly (the benchmarks/ snapshot
format: {"created", ..., "run_optimization_kwargs": {...}}), so a run can be repeated on any machine."""
import datetime as dt
import json

import numpy as np
import pandas as pd


def encode(o):
    if isinstance(o, pd.DataFrame):
        return {"__df__": o.values.tolist(), "index": [str(i) for i in o.index], "columns": list(o.columns)}
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, dict):
        return {k: encode(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [encode(v) for v in o]
    return o


def _decode(o):
    if isinstance(o, dict):
        if "__df__" in o:
            return pd.DataFrame(o["__df__"], index=o["index"], columns=o["columns"])
        return {k: _decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decode(v) for v in o]
    return o


def save(path, inputs, **meta):
    snap = {"created": dt.datetime.now().isoformat(timespec="seconds"), **encode(meta),
            "run_optimization_kwargs": encode(inputs)}
    with open(path, "w") as f:
        json.dump(snap, f)
    return snap


def load(path):
    with open(path) as f:
        snap = json.load(f)
    kw = _decode(snap["run_optimization_kwargs"])
    kw["drift"] = np.asarray(kw["drift"], dtype=float)
    return snap, kw
