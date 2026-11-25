"""Isolated fixtures; no systemd or administrative host actions."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scmanager.backup import SERVICE, ServiceState, SnapshotStore

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def config_bytes() -> bytes:
    """Return synthetic credentials, never real deployment data."""
    return json.dumps({"server": "0.0.0.0", "server_port": 8388,
        "password": "synthetic-test-secret", "method": "aes-256-gcm", "mode": "tcp_and_udp"}).encode()


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    """Bind every snapshot path to a temporary filesystem namespace."""
    return SnapshotStore(tmp_path / "backups", tmp_path / "system")


@pytest.fixture
def states() -> list[ServiceState]:
    """Represent a machine with no replacement service installed."""
    return [ServiceState(name=SERVICE, enabled="not-found", active=False)]
