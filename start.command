#!/bin/bash
# macOS: double-click to start Roptimizer (Finder runs .command files in Terminal). The first time, macOS may
# ask: right-click this file, choose Open, then Open again. Everything else is in start.sh.
cd "$(dirname "$0")" && exec bash ./start.sh
