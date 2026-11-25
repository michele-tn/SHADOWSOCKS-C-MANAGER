"""X11 session preflight tests using synthetic authority files and command doubles."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from test_workflows import BASH, PROJECT


def run_check(tmp_path: Path, display: str, connection_ok: bool = True,
              authority_exists: bool = True) -> subprocess.CompletedProcess[str]:
    """Test only --check; neither sudo nor an X server is ever contacted."""
    if not BASH:
        pytest.skip("Bash unavailable")
    authority = tmp_path / "session authority"
    if authority_exists:
        authority.write_text("synthetic-cookie-do-not-print", encoding="ascii")
    authority_path = authority.as_posix()
    if os.name == "nt":
        authority_path = "/" + authority_path[0].lower() + authority_path[2:]
    environment = os.environ.copy()
    environment.update(DISPLAY=display, XAUTHORITY=authority_path,
                       X11_TEST_CONNECT="yes" if connection_ok else "no")
    prelude = ('uname() { printf "Linux\\n"; }; xdpyinfo() { :; }; '
               'timeout() { [[ $X11_TEST_CONNECT == yes ]]; }; source launch_gui.sh --check')
    return subprocess.run([BASH, "-c", prelude], cwd=PROJECT, env=environment,
                          capture_output=True, text=True, timeout=60)


class TestX11Launcher:
    """Distinguish a verified forwarded session from a complete application test."""

    @pytest.mark.parametrize("display", ["localhost:10.0", "127.0.0.1:11.0", "[::1]:12.0", ":0"])
    def test_forwarded_session(self, tmp_path: Path, display: str) -> None:
        """Accept a reachable local display without exposing cookie content."""
        result = run_check(tmp_path, display)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "X11 session: VERIFIED" in result.stdout
        assert "does not test Qt dependencies" in result.stdout
        assert "synthetic-cookie" not in result.stdout + result.stderr

    @pytest.mark.parametrize("display", ["", "203.0.113.1:0", "localhost:10.0;echo bad", "localhost:10.0\ninvalid"])
    def test_invalid_display(self, tmp_path: Path, display: str) -> None:
        """Missing, direct network and malformed displays stop before elevation."""
        result = run_check(tmp_path, display)
        assert result.returncode == 3
        assert "X11 session: VERIFIED" not in result.stdout

    def test_missing_authority(self, tmp_path: Path) -> None:
        """A missing authority file gives actionable session guidance."""
        result = run_check(tmp_path, "localhost:10.0", authority_exists=False)
        assert result.returncode == 3
        assert "original SSH login shell" in result.stderr

    def test_failed_connection(self, tmp_path: Path) -> None:
        """A set DISPLAY alone is never reported as a working connection."""
        result = run_check(tmp_path, "localhost:10.0", connection_ok=False)
        assert result.returncode == 3
        assert "Cannot authenticate" in result.stderr
        assert "synthetic-cookie" not in result.stdout + result.stderr
