"""Resolved unit and socket parsing tests."""
from __future__ import annotations

import pytest

from scmanager.helper import legacy_exec, socket_check


class TestLegacyExec:
    """Accept only the reviewed server invocation."""

    def test_explicit_config(self) -> None:
        """A simple resolved instance unit identifies one source."""
        assert legacy_exec("{ path=/usr/bin/ss-server ; argv[]=/usr/bin/ss-server -c /etc/shadowsocks-libev/site.json ; ignore_errors=no ; start_time=[n/a] ; pid=42 ; }") == "/etc/shadowsocks-libev/site.json"

    @pytest.mark.parametrize("value", [
        "ss-server -c /etc/shadowsocks-libev/config.json", "{ argv[]=$CONFFILE $DAEMON_ARGS }",
        "{ path=/usr/bin/ss-server ; argv[]=/usr/bin/ss-server -c /etc/shadowsocks-libev/a.json -u ; ignore_errors=no ; pid=1 ; }",
    ])
    def test_overrides_rejected(self, value: str) -> None:
        """Ambiguous or overridden executions cannot be mapped automatically."""
        with pytest.raises(ValueError):
            legacy_exec(value)


class TestSocketCheck:
    """Local listener ownership is distinct from end-to-end relay health."""

    @pytest.mark.parametrize("address,endpoint", [("0.0.0.0", "0.0.0.0:8388"), ("::", "[::]:8388"), ("127.0.0.1", "127.0.0.1:8388")])
    def test_matching_pid_and_endpoint(self, address: str, endpoint: str) -> None:
        """Both address and owner must match."""
        raw = f'LISTEN 0 128 {endpoint} 0.0.0.0:* users:(("ss-server",pid=123,fd=8))'
        assert socket_check(raw, address, 8388, 123)
        assert not socket_check(raw, address, 8388, 12)
        assert not socket_check(raw, address, 8389, 123)

    def test_unexpected_output(self) -> None:
        """Unexpected command output cannot be mistaken for success."""
        assert not socket_check("invalid", "0.0.0.0", 8388, 123)
