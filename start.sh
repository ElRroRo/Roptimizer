#!/usr/bin/env bash
# Roptimizer: installs itself on the first start, then opens in your browser.
# Run it from a terminal (./start.sh) or double-click it and choose "Run in terminal".
# First start: installs uv (astral.sh, a Python installer) if missing, Python 3.13 and the packages into .venv,
# and the GPU package when an NVIDIA GPU is found. Later starts skip all that. Stop with Ctrl+C.
# MSO_PORT changes the port; MSO_NO_BROWSER=1 starts without opening the browser.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${MSO_PORT:-8797}"
URL="http://localhost:$PORT"

open_browser() {
  [ -n "${MSO_NO_BROWSER:-}" ] && { echo "Roptimizer is at $URL"; return; }
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$URL"
  else echo "Open $URL in your browser."; fi
}

if curl -fs "$URL/api/charts" >/dev/null 2>&1; then
  echo "Roptimizer is already running at $URL"; open_browser; exit 0
fi

UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
  echo "Installing uv (the Python installer) from astral.sh ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV="$HOME/.local/bin/uv"
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv with Python 3.13 ..."
  "$UV" venv -q -p 3.13 .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing the packages (a few minutes the first time) ..."
  "$UV" pip install -q -p .venv/bin/python -r requirements.txt
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    CUDA="$(nvidia-smi | grep -oE 'CUDA (UMD )?Version: [0-9]+' | grep -oE '[0-9]+$' | head -1 || echo 12)"
    if [ "${CUDA:-12}" -ge 13 ]; then PKG="cupy-cuda13x[ctk]"; else PKG="cupy-cuda12x[ctk]"; fi
    echo "NVIDIA GPU found (CUDA $CUDA): installing $PKG ..."
    "$UV" pip install -q -p .venv/bin/python "$PKG" || echo "The GPU package did not install: runs will use the CPU."
  else
    echo "No NVIDIA GPU found: runs will use the CPU (slower, smaller scenario bank)."
  fi
  touch .venv/.installed
fi

echo "Starting Roptimizer at $URL (Ctrl+C stops it) ..."
( for _ in $(seq 1 120); do curl -fs "$URL/api/charts" >/dev/null 2>&1 && { open_browser; break; }; sleep 1; done ) &
exec .venv/bin/python -m app.server
