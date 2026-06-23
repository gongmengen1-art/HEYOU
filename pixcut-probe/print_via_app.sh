#!/bin/bash
# Thin wrapper: run print_via_app.py with the project venv (needs Pillow).
# Usage: ./print_via_app.sh [--cutout] [--dry-run] [--fresh] [--keep] [--no-wait] [--margin IN] <image>
#   Validate a NEW image with --dry-run first (no ribbon), then run for real.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$HERE/print_via_app.py" "$@"
