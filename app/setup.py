"""The setup screen's API (setup.html): what this computer can run, and Google Colab set up from the browser.

GET  /api/setup                    this computer (GPU or CPU, packages) and Colab (CLI installed, signed in, balance)
POST /api/setup/gpu                install the GPU package matching the NVIDIA driver into this venv
POST /api/setup/colab/install      install the colab CLI (and uv first, when it is missing)
POST /api/setup/colab/signin       start Google sign-in: returns the URL to open
POST /api/setup/colab/code         finish it with the code Google shows after you approve

Sign-in is the colab CLI's own copy-paste flow: it prints a Google URL and waits for the code on its input, so the
page shows the link and passes the code through. Nothing here stores a credential; the CLI keeps its own token in
~/.config/colab-cli.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, Body, HTTPException

from mso import colab

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
router = APIRouter()
STATE = {"device": None, "signin": None}
_lock = threading.Lock()


def probe_device():
    """This computer's run device, found in a child process (the server itself never touches the GPU)."""
    code = ("import os; from mso.xp import cp, GPU; print(cp.cuda.runtime.getDeviceProperties(0)['name'].decode() "
            "if GPU else f'CPU ({os.cpu_count()} threads)')")
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=REPO)
        STATE["device"] = out.stdout.strip().splitlines()[-1]
    except Exception:
        STATE["device"] = None
    return STATE["device"]


def _nvidia():
    """(True, CUDA major version) when nvidia-smi answers, else (False, None)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, None
    try:
        out = subprocess.run([smi], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False, None
    m = re.search(r"CUDA(?: UMD)? Version:\s*(\d+)", out)      # newer drivers say "CUDA UMD Version"
    return bool(out.strip()), int(m.group(1)) if m else None


def _uv():
    for p in (shutil.which("uv"), os.path.expanduser("~/.local/bin/uv"), os.path.expanduser("~/.local/bin/uv.exe"),
              os.path.expanduser("~/.cargo/bin/uv")):
        if p and os.path.exists(p):
            return p
    return None


def _has_cupy():
    try:
        import importlib.util
        return importlib.util.find_spec("cupy") is not None
    except Exception:
        return False


def _run(cmd, timeout=900, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, **kw)
    return r.returncode, (r.stdout + r.stderr).strip()


@router.get("/api/setup")
def status():
    nv, cuda = _nvidia()
    dev = STATE["device"]
    out = dict(
        computer=dict(device=dev, gpu=bool(dev) and not dev.startswith("CPU"), nvidia=nv, cuda=cuda,
                      gpu_package=_has_cupy(), python=platform.python_version(), system=f"{platform.system()} {platform.machine()}",
                      threads=os.cpu_count(), forced_cpu=os.environ.get("MSO_DEVICE", "").lower() == "cpu"),
        colab=dict(installed=colab.installed(), path=colab.COLAB if colab.installed() else None, signed_in=False,
                   balance=None, error=None),
        uv=_uv(), signin=_signin_view())
    if colab.installed() and os.path.exists(os.path.expanduser("~/.config/colab-cli/token.json")):
        try:
            u = colab.usage()
            out["colab"].update(signed_in=True, balance=u["balance"])
        except colab.SignInNeeded:
            out["colab"]["error"] = "signed out: sign in again"
        except Exception as e:
            out["colab"]["error"] = str(e)[-300:]
    return out


@router.post("/api/setup/gpu")
def install_gpu():
    nv, cuda = _nvidia()
    if not nv:
        raise HTTPException(409, "no NVIDIA GPU answered (nvidia-smi): runs stay on the CPU")
    pkg = "cupy-cuda13x[ctk]" if (cuda or 12) >= 13 else "cupy-cuda12x[ctk]"
    uv = _uv()
    cmd = [uv, "pip", "install", "-q", "-p", sys.executable, pkg] if uv else [sys.executable, "-m", "pip", "install", "-q", pkg]
    code, log = _run(cmd)
    if code:
        raise HTTPException(500, f"installing {pkg} failed: {log[-600:]}")
    return dict(installed=pkg, device=probe_device())


@router.post("/api/setup/colab/install")
def install_colab():
    uv = _uv()
    if not uv:
        if os.name == "nt":
            code, log = _run(["powershell", "-ExecutionPolicy", "ByPass", "-NoProfile", "-Command",
                              "irm https://astral.sh/uv/install.ps1 | iex"])
        else:
            code, log = _run(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"])
        uv = _uv()
        if not uv:
            raise HTTPException(500, f"installing uv failed: {log[-600:]}")
    code, log = _run([uv, "tool", "install", "google-colab-cli"])
    if code and "already installed" not in log:
        raise HTTPException(500, f"installing the colab CLI failed: {log[-600:]}")
    colab.COLAB = shutil.which("colab") or os.path.expanduser("~/.local/bin/colab")
    if not colab.installed():
        raise HTTPException(500, f"the colab CLI did not appear at {colab.COLAB}: {log[-400:]}")
    return dict(installed=colab.COLAB)


# ------------------------------------------------------------ sign-in
def _signin_view():
    s = STATE["signin"]
    if not s:
        return None
    return dict(state=s["state"], url=s.get("url"), message=s.get("message"))


def _reader(s):
    for line in s["proc"].stdout:
        s["lines"].append(line.rstrip("\n"))
        m = re.search(r"https://accounts\.google\.com/\S+", line)
        if m and not s.get("url"):
            s["url"] = m.group(0)
            s["state"] = "waiting_code"


@router.post("/api/setup/colab/signin")
def signin_start():
    """Start `colab sessions`, which signs in first when there is no valid token. Returns the URL to open, or
    state "done" when it was already signed in."""
    try:
        colab._need_cli()
    except colab.ColabError as e:
        raise HTTPException(409, str(e))
    return start_signin()


def start_signin(env=None):
    """The sign-in itself; `env` overrides are for the tests only (never taken from a request)."""
    with _lock:
        old = STATE["signin"]
        if old and old["proc"].poll() is None:
            old["proc"].kill()
        proc = subprocess.Popen([colab.COLAB, "sessions"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                env={**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})})
        s = dict(proc=proc, lines=[], state="starting", url=None)
        STATE["signin"] = s
        threading.Thread(target=_reader, args=(s,), daemon=True).start()
    for _ in range(300):                       # up to 30 s for the URL, or for the CLI to finish signed in
        if s["url"]:
            return _signin_view()
        if proc.poll() is not None:
            time.sleep(0.2)
            ok = proc.returncode == 0 and not any("authorization" in l.lower() for l in s["lines"])
            s["state"], s["message"] = ("done", "already signed in") if ok else ("failed", "\n".join(s["lines"][-8:]))
            return _signin_view()
        time.sleep(0.1)
    s["state"], s["message"] = "failed", "the colab CLI showed no sign-in link within 30 s:\n" + "\n".join(s["lines"][-8:])
    proc.kill()
    return _signin_view()


@router.post("/api/setup/colab/code")
def signin_code(body: dict = Body(...)):
    s = STATE["signin"]
    code = str(body.get("code", "")).strip()
    if not s or s["state"] != "waiting_code" or s["proc"].poll() is not None:
        raise HTTPException(409, "no sign-in is waiting for a code: start it again")
    if not code:
        raise HTTPException(400, "paste the code Google showed")
    s["proc"].stdin.write(code + "\n")
    s["proc"].stdin.flush()
    try:
        s["proc"].wait(timeout=90)
    except subprocess.TimeoutExpired:
        s["proc"].kill()
        s["state"], s["message"] = "failed", "the colab CLI did not finish within 90 s"
        return _signin_view()
    time.sleep(0.2)
    tail = "\n".join(s["lines"][-8:])
    if s["proc"].returncode == 0 and not re.search(r"error|invalid|Traceback", tail, re.I):
        s["state"], s["message"] = "done", "signed in"
    else:
        errs = [l.strip(" │") for l in s["lines"] if re.search(r"\w+Error\b.*:", l)]
        s["state"], s["message"] = "failed", (f"Google did not accept the code ({errs[-1]}). Start the sign-in again and "
                                             "paste the code from that new page." if errs else tail)
    return _signin_view()
