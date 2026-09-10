#!/usr/bin/env sh
# Private-alpha local launcher. The Python entrypoint parses .env.alpha itself;
# this wrapper deliberately does not `source` or `eval` environment files.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi
exec "$PYTHON_BIN" "$SCRIPT_DIR/alpha_dev.py" "$@"
