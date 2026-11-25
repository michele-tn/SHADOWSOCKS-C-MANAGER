"""Bash workflow tests with all system mutations replaced by recording doubles."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else None)

PRELUDE = r'''
set -Eeuo pipefail
source lib/common.sh
source lib/workflows.sh
STATE="$SANDBOX/state"
WORK="$SANDBOX/work"
mkdir -p "$STATE" "$WORK"
SOURCE="$SANDBOX/legacy.json"
BINARY="$SANDBOX/replacement"
CONFIG="$SANDBOX/destination.json"
UNIT_FILE="$SANDBOX/replacement.service"
LEGACY=shadowsocks-libev.service
BACKUPS="$SANDBOX/backups"
SNAPSHOT="$BACKUPS/synthetic"
EVIDENCE=()
record() { printf '%s\n' "$*" >> "$SANDBOX/actions"; }
helper() {
  local command=$1
  shift
  case "$command" in
    hash) sha256sum "$1" | cut -d ' ' -f 1 ;;
    transform) cp -- "$1" "$2" ;;
    facts) printf '0.0.0.0\t8388\taes-256-gcm\ttcp_and_udp\n' ;;
    evidence) record evidence ;;
    *) record "helper $command" ;;
  esac
}
discover_legacy() { record discover; }
make_snapshot() { record "snapshot $1"; }
build_upstream() { record build; [[ $FAULT != build ]]; }
prepare_unit() { record prepare; }
confirm() { record "confirm $1"; [[ $FAULT != cancel ]]; }
health() { record "health $1"; [[ $FAULT != health || $1 != "$UNIT" ]]; }
port_free() { record port; [[ $FAULT != port ]]; }
write_installation() { record write; [[ $FAULT != write ]]; }
systemctl() { record "systemctl $*"; [[ $FAULT != start || $1 != start ]]; }
recover_snapshot() { record recovery; [[ $FAULT != recovery ]]; }
trap 'on_failure "$?"' ERR
trap 'on_failure 143' TERM
date() { printf '2026-11-20T00:00:00Z\n'; }
'''


def run_workflow(tmp_path: Path, fault: str, operation: str = "migrate") -> subprocess.CompletedProcess[str]:
    """Run only sourced workflow functions with injected recording doubles."""
    if not BASH:
        pytest.skip("Bash not available")
    (tmp_path / "legacy.json").write_bytes(b' { "password": "synthetic", "server_port": 8388 }\n')
    environment = os.environ.copy()
    environment.update(SANDBOX=tmp_path.as_posix(), FAULT=fault)
    script = PRELUDE + ("\nmigrate\n" if operation == "migrate" else
                        '\nassert_fresh() { record fresh; }\nfresh_install "$SOURCE"\n')
    return subprocess.run([BASH, "-c", script], cwd=PROJECT, env=environment,
                          text=True, capture_output=True, timeout=60)


class TestMigration:
    """Verify cutover ordering, compensation and immutable legacy bytes."""

    def test_success_preserves_source(self, tmp_path: Path) -> None:
        """Build, snapshot and confirmation precede stopping legacy."""
        result = run_workflow(tmp_path, "none")
        assert result.returncode == 0, result.stdout + result.stderr
        actions = (tmp_path / "actions").read_text().splitlines()
        stop = actions.index("systemctl stop shadowsocks-libev.service")
        assert actions.index("build") < stop
        assert actions.index("snapshot migrate") < stop
        assert actions.index("confirm MIGRATE") < stop
        assert actions.index("health shadowsocks-c-manager.service") < actions.index("systemctl disable shadowsocks-libev.service")
        assert "recovery" not in actions
        assert (tmp_path / "legacy.json").read_bytes() == b' { "password": "synthetic", "server_port": 8388 }\n'

    @pytest.mark.parametrize("fault", ["build", "cancel"])
    def test_failure_before_cutover(self, tmp_path: Path, fault: str) -> None:
        """Build failure or cancellation must leave the live service untouched."""
        result = run_workflow(tmp_path, fault)
        assert result.returncode != 0
        actions = (tmp_path / "actions").read_text()
        assert "systemctl stop" not in actions
        assert "recovery" not in actions

    @pytest.mark.parametrize("fault", ["start", "health", "write", "port"])
    def test_failure_after_cutover_recovers(self, tmp_path: Path, fault: str) -> None:
        """Every injected cutover failure triggers the recovery path."""
        result = run_workflow(tmp_path, fault)
        assert result.returncode != 0
        actions = (tmp_path / "actions").read_text()
        assert "recovery" in actions
        assert "Recovery VERIFIED" in result.stdout
        assert not (tmp_path / "state" / "pending").exists()

    def test_recovery_failure_retains_pointer(self, tmp_path: Path) -> None:
        """Never report successful recovery when restoration itself fails."""
        if not BASH:
            pytest.skip("Bash not available")
        environment = os.environ.copy()
        environment.update(SANDBOX=tmp_path.as_posix(), FAULT="recovery")
        result = subprocess.run([BASH, "-c", PRELUDE + '\nbegin_transaction\nfalse\n'],
            cwd=PROJECT, env=environment, text=True, capture_output=True, timeout=60)
        assert result.returncode != 0
        assert "Recovery FAILED" in result.stdout
        assert "Recovery VERIFIED" not in result.stdout
        assert (tmp_path / "state" / "pending").exists()

    @pytest.mark.parametrize("signal_name,code", [("TERM", 143), ("INT", 130)])
    def test_signal_recovers(self, tmp_path: Path, signal_name: str, code: int) -> None:
        """A catchable signal after the transaction boundary runs recovery."""
        if not BASH:
            pytest.skip("Bash unavailable")
        environment = os.environ.copy()
        environment.update(SANDBOX=tmp_path.as_posix(), FAULT="none")
        script = PRELUDE + "\ntrap 'on_failure 130' INT\nbegin_transaction\nkill -" + signal_name + " $$\n"
        result = subprocess.run([BASH, "-c", script], cwd=PROJECT, env=environment,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == code
        assert "Recovery VERIFIED" in result.stdout
        assert not (tmp_path / "state" / "pending").exists()


class TestInstallation:
    """Protect fresh-install transaction boundaries."""

    @pytest.mark.parametrize("fault,success", [("none", True), ("build", False), ("port", False), ("start", False), ("write", False)])
    def test_workflow_outcomes(self, tmp_path: Path, fault: str, success: bool) -> None:
        """Only fully checked installs commit; partial installs recover."""
        result = run_workflow(tmp_path, fault, "install")
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        actions = (tmp_path / "actions").read_text()
        if fault in {"start", "write"}:
            assert "recovery" in actions
        if fault in {"build", "port"}:
            assert "write" not in actions
