"""The portfolio library (#11): plain files you can open, no database.

  library/portfolios/<id>.json   one portfolio (mso.portfolio's shape), written atomically, with a version
                                 number: a save from a stale tab is refused (Conflict) instead of overwriting
  library/runs/<run id>/         one run: portfolio.json (frozen at queue time), inputs.json (frozen inputs),
                                 run.json (status, machine, timings, CU), events.jsonl, results.json, log.txt
  library/defaults.json          the app defaults a fresh portfolio starts from (mso.portfolio.DEFAULTS)
  library/beta_overrides.json    manual crash/rally betas (mso.betas)

library/ is git-ignored; the Desktop backup covers it. The run list is built by reading each run.json.
"""
import datetime as dt
import json
import os
import re
import shutil
import threading
import uuid

from mso import portfolio as pf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "library")
CSV_SEED = os.path.join(REPO, "portfolio_data.csv")
EXAMPLES = os.path.join(REPO, "examples")
_lock = threading.RLock()


class NotFound(KeyError):
    pass


class Conflict(RuntimeError):
    pass


def _dirs(root):
    for d in ("portfolios", "runs"):
        os.makedirs(os.path.join(root, d), exist_ok=True)


def _write(path, body):
    tmp = path + f".tmp{uuid.uuid4().hex[:6]}"
    with open(tmp, "w") as f:
        json.dump(body, f, indent=1, default=float)
    os.replace(tmp, path)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _safe_id(i):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(i)):
        raise NotFound(i)
    return str(i)


class Library:
    def __init__(self, root=ROOT):
        self.root = root
        _dirs(root)

    # ------------------------------------------------------------ portfolios
    def _ppath(self, pid):
        return os.path.join(self.root, "portfolios", _safe_id(pid) + ".json")

    def portfolios(self):
        out = []
        for n in sorted(os.listdir(os.path.join(self.root, "portfolios"))):
            if n.endswith(".json"):
                p = _read(os.path.join(self.root, "portfolios", n))
                out.append(dict(id=p["id"], name=p["name"], version=p.get("version", 1), updated=p.get("updated"),
                                assets=len(pf.tickers(p)),
                                subportfolios=sum(1 for n_, _, _ in pf.walk(p["tree"]) if n_["kind"] == "group") - 1))
        return out

    def get(self, pid):
        path = self._ppath(pid)
        if not os.path.exists(path):
            raise NotFound(pid)
        return _read(path)

    def save(self, p, expected_version=None):
        """Create or update. With expected_version, the stored version must match (else Conflict)."""
        with _lock:
            p = dict(p)
            p.setdefault("id", uuid.uuid4().hex[:12])
            path = self._ppath(p["id"])
            if os.path.exists(path):
                cur = _read(path).get("version", 1)
                if expected_version is not None and int(expected_version) != cur:
                    raise Conflict(f"portfolio {p['id']} is at version {cur}, the save was made on {expected_version}")
                p["version"] = cur + 1
            else:
                p["version"] = 1
                p.setdefault("created", dt.datetime.now().isoformat(timespec="seconds"))
            p["updated"] = dt.datetime.now().isoformat(timespec="seconds")
            _write(path, p)
            return p

    def delete(self, pid):
        path = self._ppath(pid)
        if not os.path.exists(path):
            raise NotFound(pid)
        os.remove(path)

    def duplicate(self, pid, name=None):
        p = pf.copy_of(self.get(pid))
        p["id"] = uuid.uuid4().hex[:12]
        p["name"] = name or f"{p['name']} (copy)"
        p.pop("version", None)
        p.pop("created", None)
        return self.save(p)

    def import_csv(self, path, name=None):
        return self.save(pf.from_csv(path, name))

    def seed_if_empty(self):
        """First start (#11): an empty library takes the example portfolios in examples/ (*.json) and imports
        portfolio_data.csv. Returns the first one it added, or None."""
        if self.portfolios():
            return None
        added = []
        if os.path.isdir(EXAMPLES):
            for f in sorted(os.listdir(EXAMPLES)):
                if f.endswith(".json"):
                    p = _read(os.path.join(EXAMPLES, f))
                    for k in ("id", "version", "created", "updated"):
                        p.pop(k, None)
                    added.append(self.save(p))
        if os.path.exists(CSV_SEED):
            added.append(self.import_csv(CSV_SEED, "Example: 16 assets, flat (from portfolio_data.csv)"))
        return added[0] if added else None

    # ------------------------------------------------------------ runs
    def run_dir(self, rid):
        return os.path.join(self.root, "runs", _safe_id(rid))

    def new_run(self, portfolio, machine, settings=None):
        rid = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = self.run_dir(rid)
        os.makedirs(d)
        _write(os.path.join(d, "portfolio.json"), portfolio)
        rec = dict(id=rid, portfolio_id=portfolio["id"], portfolio_name=portfolio["name"],
                   portfolio_version=portfolio.get("version"), machine=machine, status="queued",
                   queued=dt.datetime.now().isoformat(timespec="seconds"), settings=settings or {})
        _write(os.path.join(d, "run.json"), rec)
        return rec

    def run(self, rid):
        path = os.path.join(self.run_dir(rid), "run.json")
        if not os.path.exists(path):
            raise NotFound(rid)
        return _read(path)

    def update_run(self, rid, **fields):
        with _lock:
            rec = self.run(rid)
            rec.update(fields)
            _write(os.path.join(self.run_dir(rid), "run.json"), rec)
            return rec

    def runs(self, portfolio_id=None):
        out = []
        for n in sorted(os.listdir(os.path.join(self.root, "runs")), reverse=True):
            p = os.path.join(self.root, "runs", n, "run.json")
            if os.path.exists(p):
                r = _read(p)
                if portfolio_id is None or r.get("portfolio_id") == portfolio_id:
                    out.append(r)
        return out

    def results(self, rid):
        path = os.path.join(self.run_dir(rid), "results.json")
        if not os.path.exists(path):
            raise NotFound(f"{rid} has no results")
        return _read(path)

    def events(self, rid, since=0):
        path = os.path.join(self.run_dir(rid), "events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(l) for i, l in enumerate(f) if i >= since and l.strip()]

    def delete_run(self, rid):
        d = self.run_dir(rid)
        if not os.path.isdir(d):
            raise NotFound(rid)
        shutil.rmtree(d)

    def mark_interrupted(self):
        """At server start: runs left queued or running by a server that died are marked interrupted."""
        changed = []
        for r in self.runs():
            if r.get("status") in ("queued", "running", "waiting"):
                self.update_run(r["id"], status="interrupted",
                                ended=dt.datetime.now().isoformat(timespec="seconds"),
                                error="the server stopped while this run was " + r["status"])
                changed.append(r["id"])
        return changed
