"""Real recovery orchestration with checked command doubles, including conditional callers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from test_workflows import BASH, PROJECT

RECOVERY = r'''
set -Eeuo pipefail
source lib/common.sh
source lib/service.sh
STATE="$SANDBOX/state"
WORK="$SANDBOX/work"
mkdir -p "$STATE" "$WORK"
date() { printf '2026-11-20T00:00:00Z\n'; }
record() { printf '%s\n' "$*" >> "$SANDBOX/actions"; }
helper() {
  record "helper $1"
  [[ $FAULT != "$1" ]] || return 1
  if [[ $1 == services ]]; then
    printf 'shadowsocks-c-manager.service\tenabled\tactive\n'
  fi
}
systemctl() {
  record "systemctl $1"
  [[ $FAULT != "$1" ]] || return 1
  case "$1" in
    show) printf 'loaded\n' ;;
    is-enabled) printf 'enabled\n' ;;
  esac
}
health() { record health; [[ $FAULT != health ]]; }
if recover_snapshot "$SANDBOX/snapshot"; then
  printf 'RESTORE_SUCCESS\n'
else
  printf 'RESTORE_FAILED\n'
  exit 5
fi
'''


class TestRecovery:
    """A conditional caller must not suppress failed recovery commands."""

    @pytest.mark.parametrize("fault", ["verify", "evidence", "services", "stop", "disable",
                                       "restore", "daemon-reload", "enable", "start", "health", "is-enabled"])
    def test_failure_propagates(self, tmp_path: Path, fault: str) -> None:
        """Every critical failure prevents a successful restoration result."""
        if not BASH:
            pytest.skip("Bash unavailable")
        environment = os.environ.copy()
        environment.update(SANDBOX=tmp_path.as_posix(), FAULT=fault)
        result = subprocess.run([BASH, "-c", RECOVERY], cwd=PROJECT, env=environment,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 5, result.stdout + result.stderr
        assert "RESTORE_SUCCESS" not in result.stdout
        if fault in {"verify", "evidence", "services"}:
            assert "systemctl stop" not in (tmp_path / "actions").read_text()

    def test_restore_sequence(self, tmp_path: Path) -> None:
        """Files restore only after checks and service stop, followed by health."""
        if not BASH:
            pytest.skip("Bash unavailable")
        environment = os.environ.copy()
        environment.update(SANDBOX=tmp_path.as_posix(), FAULT="none")
        result = subprocess.run([BASH, "-c", RECOVERY], cwd=PROJECT, env=environment,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        actions = (tmp_path / "actions").read_text().splitlines()
        assert actions.index("helper verify") < actions.index("systemctl stop")
        assert actions.index("systemctl stop") < actions.index("helper restore")
        assert actions.index("helper restore") < actions.index("systemctl daemon-reload")
        assert actions.index("systemctl start") < actions.index("health")
