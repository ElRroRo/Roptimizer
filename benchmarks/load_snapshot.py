"""Rebuild run_optimization's arguments from a snapshot written by snapshot.py."""
import json

import pandas as pd


def _decode(o):
    if isinstance(o, dict):
        if "__df__" in o:
            return pd.DataFrame(o["__df__"], index=o["index"], columns=o["columns"])
        return {k: _decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decode(v) for v in o]
    return o


def load(path):
    with open(path) as f:
        snap = json.load(f)
    kw = _decode(snap["run_optimization_kwargs"])
    import numpy as np
    kw["drift"] = np.asarray(kw["drift"], dtype=float)
    return snap, kw
