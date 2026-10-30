"""Running a packed job on a Colab A100 (#4, #5, #11) with `colab run`, which releases the VM even when the
script fails.

- One session per job, named mso-<run id>, so Cancel and the orphan sweep can find it.
- stdin is /dev/null: `colab` can never sit at a sign-in prompt. A 401 or a sign-in prompt fails the job
  with SignInNeeded ("run `colab sessions` in a terminal"), the token-refresh hang #4 warned about.
- 503 at assignment (no VM, no charge; seen 2026-10-27) is retried after 30, 60, 120 s and then every
  120 s for up to 30 minutes, reported as "waiting for an A100".
- The compute-unit balance is read before and after (`colab usage`), measured, never estimated.
"""
import os
import re
import shutil
import subprocess
import time

COLAB = shutil.which("colab") or os.path.expanduser("~/.local/bin/colab")
RATE_CU_PER_HOUR = 5.30           # plain A100, measured 2026-10-27 (#5)
BACKOFF = [30, 60, 120]
RETRY_FOR_S = 30 * 60
SESSION_PREFIX = "mso-"


class ColabError(RuntimeError):
    pass


class SignInNeeded(ColabError):
    pass


class NoA100(ColabError):
    pass


class VMLost(ColabError):
    pass


SILENCE_CHECK_S = 120     # no output this long: check that the session still exists


def installed():
    return os.path.exists(COLAB)


def _need_cli():
    if not installed():
        raise ColabError("the colab CLI is not installed: `uv tool install google-colab-cli`, then sign in once "
                         "with `colab sessions` in a terminal")


def _quiet(cmd, timeout=90):
    _need_cli()
    r = subprocess.run([COLAB] + cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    if re.search(r"\b401\b|authorization code|sign in|re-authenticate", out, re.I):
        raise SignInNeeded("Colab needs you to sign in again: run `colab sessions` in a terminal")
    return r.returncode, out


def usage():
    """{"balance": CU, "rate": CU/h} from `colab usage`."""
    code, out = _quiet(["usage"])
    m = re.search(r"Current balance:\s*([\d.]+)", out)
    rate = re.search(r"Usage rate:\s*([\d.]+)", out)
    if code or not m:
        raise ColabError(f"`colab usage` failed: {out.strip()[-300:]}")
    return {"balance": float(m.group(1)), "rate": float(rate.group(1)) if rate else None}


def sessions():
    """Names of the active mso-* sessions (other sessions are never touched)."""
    code, out = _quiet(["sessions"])
    if "No active sessions" in out:
        return []
    return sorted(set(re.findall(r"\b(" + re.escape(SESSION_PREFIX) + r"[\w-]+)", out)))


def stop(session):
    _quiet(["stop", "-s", session], timeout=120)


def sweep(names):
    """Stop those of `names` that are still active (a run's own session after it ends; at server start, the
    sessions of the library's runs). Never a session it cannot attribute: on 2026-10-29 a sweep of every
    mso-* session stopped a measurement job started outside the server. Returns (stopped, other mso-* left)."""
    active = sessions()
    stopped = [s for s in active if s in set(names)]
    for s in stopped:
        stop(s)
    return stopped, [s for s in active if s not in set(names)]


def run(script, session, on_line=print, gpu="A100", high_mem=False, timeout_s=4 * 3600, on_wait=None, proc_holder=None):
    """Run `script` on a fresh Colab VM and return its whole stdout. Lines stream to on_line as they come.
    proc_holder (a dict) receives the live process under "proc", so a caller can cancel it."""
    _need_cli()
    cmd = [COLAB, "run", "--gpu", gpu, "-s", session, "--timeout", str(int(timeout_s))]
    if high_mem:
        cmd.append("--high-mem")
    cmd.append(script)
    t0, attempt = time.time(), 0
    while True:
        attempt += 1
        # Same process group as the caller, so killing a run's process group (Cancel) also ends this client.
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        if proc_holder is not None:
            proc_holder["proc"] = p
        lines, q = [], __import__("queue").Queue()
        import threading
        threading.Thread(target=lambda: ([q.put(l) for l in p.stdout], q.put(None)), daemon=True).start()
        last = time.time()
        while True:
            try:
                line = q.get(timeout=15)
            except Exception:
                # Silence. A VM stopped from outside leaves `colab run` waiting forever (2026-10-29), so after
                # SILENCE_CHECK_S without output, confirm the session still exists.
                if time.time() - last > SILENCE_CHECK_S and any("[job] started" in l for l in lines):
                    try:
                        alive = session in sessions()
                    except ColabError:
                        alive = True
                    if not alive:
                        p.kill()
                        raise VMLost(f"the A100 was lost: session {session} no longer exists "
                                     f"({(time.time() - last) / 60:.1f} min without output)")
                    last = time.time()
                continue
            if line is None:
                break
            last = time.time()
            line = line.rstrip("\n")
            lines.append(line)
            if re.search(r"authorization code|Enter the code|sign in again|\b401\b.*[Uu]nauthori", line):
                p.kill()
                raise SignInNeeded("Colab needs you to sign in again: run `colab sessions` in a terminal")
            on_line(line)
        p.wait()
        out = "\n".join(lines)
        if p.returncode != 0 and re.search(r"\b503\b|Service Unavailable", out) and "[job] started" not in out:
            waited = time.time() - t0
            if waited > RETRY_FOR_S:
                raise NoA100(f"no {gpu} after {waited / 60:.0f} minutes of retries (503 at assignment)")
            delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            if on_wait:
                on_wait(attempt, delay)
            time.sleep(delay)
            continue
        if re.search(r"\b400\b", out) and "[job] started" not in out:
            raise NoA100(f"Colab would not assign a {gpu} (400; your plan may not include it): {out.strip()[-300:]}")
        return p.returncode, out
