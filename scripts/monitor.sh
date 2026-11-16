#!/bin/sh
set -eu
monitor_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
monitor_command=${1:-mcp}
if [ "$#" -gt 0 ]; then shift; fi
case "$monitor_command" in
  mcp|scan|config) exec uv run --locked --no-dev --project "$monitor_root" gauge "$monitor_command" "$@" ;;
  test) cd "$monitor_root"; exec uv run --locked --no-dev python -m unittest discover -s tests -v ;;
  *) echo 'Usage: monitor.sh [mcp|scan|config|test] [options]' >&2; exit 2 ;;
esac
