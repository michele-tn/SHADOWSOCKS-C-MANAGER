"""Configuration compatibility and secret-redaction regression tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scmanager.models import ConfigurationError, load_config, parse_config


class TestParseConfig:
    """Protect the fail-closed migration profile."""

    def test_preserves_credentials_and_source(self, tmp_path: Path, config_bytes: bytes) -> None:
        """Transformation must not rewrite the original source bytes."""
        original = b"  " + config_bytes + b"\n\n"
        source = tmp_path / "legacy.json"
        source.write_bytes(original)
        config = load_config(source)
        target = json.loads(config.target_bytes())
        assert source.read_bytes() == original
        assert target["password"] == "synthetic-test-secret"
        assert target["method"] == "aes-256-gcm"
        assert target["server_port"] == 8388
        assert target["mode"] == "tcp_and_udp"

    @pytest.mark.parametrize("field,value", [
        ("server", ["0.0.0.0", "::"]), ("server", "host.invalid"),
        ("server_port", [8388, 8389]), ("server_port", True), ("server_port", 80),
        ("server_port", "8388"), ("method", "aes-256-cfb"), ("mode", "automatic"),
        ("plugin", "unsupported"), ("timeout", 0), ("password", ""),
        ("password", "a\x00b"), ("server", "fe80::1%eth0"),
    ])
    def test_rejects_unknown_semantics(self, config_bytes: bytes, field: str, value: object) -> None:
        """Invalid and unsupported values must not be silently normalized."""
        data = json.loads(config_bytes)
        data[field] = value
        with pytest.raises(ConfigurationError) as failure:
            parse_config(json.dumps(data).encode())
        assert "synthetic-test-secret" not in str(failure.value)

    @pytest.mark.parametrize("raw", [b"{", b"[]", b'{}', b'{"password":"secret","password":"other"}', b"\xff"])
    def test_invalid_json(self, raw: bytes) -> None:
        """Malformed, duplicate and incomplete inputs fail without input disclosure."""
        with pytest.raises(ConfigurationError):
            parse_config(raw)

    def test_defaults_are_explicit(self, config_bytes: bytes) -> None:
        """An absent mode retains upstream's TCP-only default."""
        data = json.loads(config_bytes)
        del data["mode"]
        result = parse_config(json.dumps(data).encode())
        assert result.mode == "tcp_only"
        assert result.timeout == 60
        assert "synthetic-test-secret" not in repr(result)

    @pytest.mark.parametrize("mode", ["tcp_only", "tcp_and_udp", "udp_only"])
    def test_protocol_preservation(self, config_bytes: bytes, mode: str) -> None:
        """Each accepted mode survives target generation unchanged."""
        data = json.loads(config_bytes)
        data["mode"] = mode
        assert json.loads(parse_config(json.dumps(data).encode()).target_bytes())["mode"] == mode
