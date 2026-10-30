"""The progress protocol: one `@@MSO {json}` line per event on stdout, the same on the laptop and the A100.

The runner (and anything else reading a job's stdout) picks these lines out; every other line is the
human-readable log and is kept as it is.
"""
import json
import time

PREFIX = "@@MSO "


def _plain(o):
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def emit(kind, **fields):
    print(PREFIX + json.dumps({"type": kind, "t": round(time.time(), 3), **fields}, default=_plain), flush=True)


def parse(line):
    """The event on a stdout line, or None for an ordinary log line."""
    return json.loads(line[len(PREFIX):]) if line.startswith(PREFIX) else None
