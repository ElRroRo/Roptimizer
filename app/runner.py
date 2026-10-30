"""The job runner (#11): three lanes, each running one job at a time.

  laptop  optimizer runs on the RTX 3060
  a100    optimizer runs on a Colab A100 (frozen and packed here, run with `colab run`)
  data    Refresh data and jump-database recalibrations

Every job is a child process, so the server never touches the GPU, an engine crash cannot take it down, and
Cancel kills the process (and the GPU memory with it). The engine prints `@@MSO {json}` events on stdout,
the same on both machines; the runner appends them to the run's events.jsonl and hands them to live
subscribers. A run's portfolio is frozen into its folder when it is queued; its inputs (market data, fits,
jump version, betas) are frozen into inputs.json when it starts. A run starting while a refresh or
recalibration is running waits for it; a refresh waits for running input builds.
"""
import collections
import datetime as dt
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

from mso import colab, events

from .library import REPO, Library, NotFound

PY = sys.executable


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _signal_tree(pid, hard):
    """End a child process and everything it started: its process group on Linux and macOS, taskkill's
    tree on Windows."""
    if os.name == "nt":
        # A console process refuses taskkill without /F (exit 128, "can only be terminated forcefully"), so the
        # tree is always ended with /F; it is gone already only when taskkill says "not found" (checked in WinBoat).
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
        if r.returncode and "not found" in (r.stdout + r.stderr).lower():
            raise ProcessLookupError(pid)
        return
    os.killpg(pid, signal.SIGKILL if hard else signal.SIGTERM)


def _kill_orphan(pid, rid):
    """End a run's child process that outlived its server (it runs in its own session), but only if that
    pid is still that run's process: its command line names the run id."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().decode(errors="replace")
    except OSError:
        return False
    if rid not in cmd or "mso" not in cmd:
        return False
    try:
        _signal_tree(pid, False)
        time.sleep(3)
        _signal_tree(pid, True)
    except ProcessLookupError:
        pass
    return True


class RWLock:
    """Many readers (input builds) or one writer (refresh / recalibration)."""

    def __init__(self):
        self._c = threading.Condition()
        self._readers = 0
        self._writer = False

    def acquire_read(self):
        with self._c:
            while self._writer:
                self._c.wait()
            self._readers += 1

    def release_read(self):
        with self._c:
            self._readers -= 1
            self._c.notify_all()

    def acquire_write(self):
        with self._c:
            while self._writer or self._readers:
                self._c.wait()
            self._writer = True

    def release_write(self):
        with self._c:
            self._writer = False
            self._c.notify_all()


class Job:
    def __init__(self, jid, lane, kind, payload):
        self.id, self.lane, self.kind, self.payload = jid, lane, kind, payload
        self.proc = None
        self.status = "queued"
        self.cancelled = False
        self.session = None
        self.record = dict(id=jid, lane=lane, kind=kind, status="queued", queued=now())


class Runner:
    LANES = ("laptop", "a100", "data")

    def __init__(self, lib=None):
        self.lib = lib or Library()
        self.data_lock = RWLock()
        self.queues = {l: collections.deque() for l in self.LANES}
        self.current = {l: None for l in self.LANES}
        self.jobs = {}                                   # data-lane jobs (runs live in the library)
        self.subs = collections.defaultdict(list)        # run id -> [queue.Queue]
        self._cv = threading.Condition()
        self._pub_lock = threading.Lock()
        self._seq = {}
        self._stop = False
        for l in self.LANES:
            threading.Thread(target=self._lane_loop, args=(l,), daemon=True, name=f"lane-{l}").start()

    # ------------------------------------------------------------ startup / shutdown
    def recover(self):
        """At server start: runs a dead server left behind are marked interrupted, and every mso-* Colab
        session (none can be live yet) is stopped."""
        live = {r["id"]: r.get("pid") for r in self.lib.runs() if r.get("status") in ("queued", "running", "waiting")}
        interrupted = self.lib.mark_interrupted()
        killed = [rid for rid, pid in live.items() if pid and _kill_orphan(pid, rid)]
        try:
            stopped, others = colab.sweep([colab.SESSION_PREFIX + r["id"] for r in self.lib.runs()]) if colab.installed() else ([], [])
        except (colab.ColabError, OSError, subprocess.SubprocessError) as e:
            stopped, others = [], [f"(could not check Colab: {e})"]
        return dict(interrupted=interrupted, orphans_killed=killed, sessions_stopped=stopped,
                    other_sessions_left=others)

    def a100_busy(self):
        return self.current["a100"] is not None

    # ------------------------------------------------------------ submitting
    def submit_run(self, portfolio, machine, opts=None):
        if machine not in ("laptop", "a100"):
            raise ValueError(f"unknown machine {machine!r}")
        opts = dict(opts or {})
        rec = self.lib.new_run(portfolio, machine, opts)
        job = Job(rec["id"], machine, "run", opts)
        with self._cv:
            self.queues[machine].append(job)
            self._cv.notify_all()
        self._publish(rec["id"], dict(type="queued", t=time.time(), machine=machine,
                                      position=len(self.queues[machine]) + (self.current[machine] is not None)))
        return rec

    def submit_data(self, kind):
        if kind not in ("refresh", "recalibrate"):
            raise ValueError(kind)
        jid = f"{kind}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        job = Job(jid, "data", kind, {})
        self.jobs[jid] = job
        with self._cv:
            self.queues["data"].append(job)
            self._cv.notify_all()
        return job.record

    # ------------------------------------------------------------ cancel
    def cancel(self, rid):
        with self._cv:
            for lane in ("laptop", "a100"):
                for job in list(self.queues[lane]):
                    if job.id == rid:
                        self.queues[lane].remove(job)
                        self.lib.update_run(rid, status="cancelled", ended=now(), error="cancelled before it started")
                        self._publish(rid, dict(type="cancelled", t=time.time()))
                        self._close(rid)
                        return dict(cancelled=True, started=False)
            job = next((self.current[l] for l in ("laptop", "a100") if self.current[l] and self.current[l].id == rid), None)
        if job is None:
            raise NotFound(rid)
        job.cancelled = True
        if job.lane == "a100":
            # Shut the Colab machine down first (Cancel always stops Colab, #8), then the local process.
            try:
                colab.stop(colab.SESSION_PREFIX + rid)
            except colab.ColabError:
                pass
        self._kill(job)
        left = None
        if job.lane == "a100":
            try:
                left = [s for s in colab.sessions() if s == colab.SESSION_PREFIX + rid]
                for s in left:
                    colab.stop(s)
            except colab.ColabError as e:
                left = [f"could not check: {e}"]
        return dict(cancelled=True, started=True, colab_sessions_left=left)

    def _kill(self, job):
        p = job.proc
        if p is None or p.poll() is not None:
            return
        try:
            _signal_tree(p.pid, False)
        except ProcessLookupError:
            return
        for _ in range(50):
            if p.poll() is not None:
                return
            time.sleep(0.1)
        try:
            _signal_tree(p.pid, True)
        except ProcessLookupError:
            pass

    # ------------------------------------------------------------ status and events
    def status(self):
        lanes = {}
        for l in self.LANES:
            cur = self.current[l]
            lanes[l] = dict(running=cur.id if cur else None, kind=cur.kind if cur else None,
                            queued=[j.id for j in self.queues[l]])
        return lanes

    def subscribe(self, rid):
        q = queue.Queue()
        self.subs[rid].append(q)
        return q

    def unsubscribe(self, rid, q):
        if q in self.subs.get(rid, []):
            self.subs[rid].remove(q)

    def _publish(self, rid, ev):
        """Append to the run's events.jsonl with a sequence number (its line number), then hand it to live
        subscribers; the number lets a stream that read the file first skip what it already sent."""
        d = self.lib.run_dir(rid)
        path = os.path.join(d, "events.jsonl")
        with self._pub_lock:
            if rid not in self._seq:
                self._seq[rid] = sum(1 for _ in open(path)) if os.path.exists(path) else 0
            ev = dict(ev, seq=self._seq[rid])
            self._seq[rid] += 1
            with open(path, "a") as f:
                f.write(json.dumps(ev, default=float) + "\n")
        for q in list(self.subs.get(rid, [])):
            q.put(ev)

    def _close(self, rid):
        for q in list(self.subs.get(rid, [])):
            q.put(None)

    # ------------------------------------------------------------ lanes
    def _lane_loop(self, lane):
        while not self._stop:
            with self._cv:
                while not self.queues[lane]:
                    self._cv.wait()
                job = self.queues[lane].popleft()
                self.current[lane] = job
            try:
                if job.kind == "run":
                    self._run(job)
                else:
                    self._data(job)
            except Exception as e:                     # a runner bug must never kill the lane
                if job.kind == "run":
                    self.lib.update_run(job.id, status="failed", ended=now(), error=f"runner: {type(e).__name__}: {e}")
                    self._publish(job.id, dict(type="failed", t=time.time(), error=str(e)))
                    self._close(job.id)
                else:
                    job.record.update(status="failed", error=str(e), ended=now())
            finally:
                self.current[lane] = None

    def _cmd(self, job, d):
        o = job.payload
        cmd = [PY, "-u", "-m", "mso", "run", "--portfolio", os.path.join(d, "portfolio.json"),
               "--machine", job.lane, "--out", os.path.join(d, "results.json"),
               "--save-inputs", os.path.join(d, "inputs.json"), "--run-id", job.id,
               "--seed", str(int(o.get("seed", 20261029)))]
        for k in ("bank", "draw", "bands", "rescore_paths", "rescore_reps"):
            if o.get(k):
                cmd += ["--" + k.replace("_", "-"), str(int(o[k]))]
        for kv in o.get("set", []):
            cmd += ["--set", kv]
        if job.lane == "a100" and o.get("gpu") in ("T4", "L4", "A100", "H100"):
            cmd += ["--colab-gpu", o["gpu"]]
        if o.get("quick"):
            cmd.append("--quick")
        return cmd

    def _run(self, job):
        rid, d = job.id, self.lib.run_dir(job.id)
        self.lib.update_run(rid, status="running", started=now())
        self._publish(rid, dict(type="started", t=time.time(), machine=job.lane))
        self.data_lock.acquire_read()                  # inputs are built from the day's data: no refresh meanwhile
        reading = True
        t0 = time.time()
        log = open(os.path.join(d, "log.txt"), "a")
        try:
            job.proc = subprocess.Popen(self._cmd(job, d), cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
                                        env={**os.environ, "MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"})
            self.lib.update_run(rid, pid=job.proc.pid)
            for line in job.proc.stdout:
                line = line.rstrip("\n")
                ev = events.parse(line)
                if ev is None:
                    log.write(line + "\n")
                    log.flush()
                    if "waiting for a" in line:
                        self.lib.update_run(rid, status="waiting")
                        self._publish(rid, dict(type="waiting", t=time.time(), text=line.replace("[mso] ", "")))
                    continue
                if reading and ev.get("type") == "stage" and ev.get("stage") in ("bank", "packed"):
                    self.data_lock.release_read()
                    reading = False
                    if self.lib.run(rid).get("status") == "waiting":
                        self.lib.update_run(rid, status="running")
                self._publish(rid, ev)
            code = job.proc.wait()
        finally:
            if reading:
                self.data_lock.release_read()
            log.close()
        wall = round(time.time() - t0, 1)
        fields = dict(ended=now(), wall_s=wall, exit=code)
        if job.cancelled:
            fields.update(status="cancelled", error="cancelled")
        elif code == 0 and os.path.exists(os.path.join(d, "results.json")):
            fields["status"] = "done"
            try:
                res = self.lib.results(rid)
                fields.update(objective=res["rows"][0]["search"].get("incumbent"), gpu=res.get("gpu"),
                              colab=res.get("colab"), searches=res.get("searches"))
            except Exception as e:
                fields.update(status="failed", error=f"unreadable results: {e}")
        else:
            tail = open(os.path.join(d, "log.txt")).read().strip().splitlines()[-3:]
            fields.update(status="failed", error=" | ".join(tail) or f"exit {code}")
        if job.lane == "a100":
            try:                                                      # always stop what you start
                fields["sessions_stopped_after"] = colab.sweep([colab.SESSION_PREFIX + rid])[0]
            except colab.ColabError as e:
                fields["sessions_check"] = str(e)
        self.lib.update_run(rid, **fields)
        self._publish(rid, dict(type="end", t=time.time(), **fields))
        self._close(rid)

    def _data(self, job):
        job.record.update(status="running", started=now())
        self.data_lock.acquire_write()
        try:
            if job.kind == "refresh":
                from mso.cache import DayCache
                c = DayCache()
                c.refresh()
                job.record.update(status="done", day=c.day)
            else:
                job.proc = subprocess.Popen([PY, "-u", "-m", "mso", "jumpdb", "recalibrate"], cwd=REPO,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            start_new_session=True, env={**os.environ, "MPLBACKEND": "Agg"})
                out = job.proc.communicate()[0]
                last = [l for l in out.splitlines() if l.startswith("[mso]")]
                job.record.update(status="done" if job.proc.returncode == 0 else "failed",
                                  message=last[-1] if last else out.strip()[-300:])
        finally:
            self.data_lock.release_write()
            job.record["ended"] = now()
