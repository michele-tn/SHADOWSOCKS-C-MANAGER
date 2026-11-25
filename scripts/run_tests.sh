#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"
shellcheck -x shadowsocks-c-manager.sh launch_gui.sh scripts/setup.sh scripts/run_tests.sh
for script in *.sh lib/*.sh scripts/*.sh; do bash -n "$script"; done
"$PYTHON" -m ruff check .
"$PYTHON" -m mypy scmanager
QT_QPA_PLATFORM=offscreen "$PYTHON" -m pytest -q
