#!/usr/bin/env sh
# Atajo para macOS/Linux: ./titan.sh <comando>  (equivale a .venv/bin/python -m cvtitan <comando>)
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m cvtitan "$@"
