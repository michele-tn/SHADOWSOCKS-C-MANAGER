"""Snapshot corruption, traversal and restoration behavior."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scmanager.backup import MANAGED, ServiceState, SnapshotStore


def rewrite_manifest(location: Path, data: dict[str, object]) -> None:
    """Simulate a malicious manifest with a recomputed transport checksum."""
    raw = json.dumps(data).encode()
    (location / "manifest.json").write_bytes(raw)
    (location / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest())


class TestSnapshotStore:
    """Exercise isolated files, never the real root filesystem."""

    def test_roundtrip_and_missing_paths(self, store: SnapshotStore, states: list[ServiceState]) -> None:
        """Restore bytes and mode and remove files that originally did not exist."""
        target = store.system_path(MANAGED[1], "managed")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original")
        target.chmod(0o600)
        snapshot = store.create("backup", [], states)
        target.write_bytes(b"changed")
        created = store.system_path(MANAGED[0], "managed")
        created.parent.mkdir(parents=True)
        created.write_bytes(b"new")
        store.restore(snapshot)
        assert target.read_bytes() == b"original"
        assert not created.exists()
        assert snapshot.is_dir()
        if os.name != "nt":
            assert target.stat().st_mode & 0o777 == 0o600
            assert target.stat().st_uid == os.geteuid()

    @pytest.mark.parametrize("corruption", ["payload", "missing", "manifest", "extra"])
    def test_corruption_refused_before_restore(self, store: SnapshotStore,
            states: list[ServiceState], corruption: str) -> None:
        """Every corrupt snapshot leaves the current target untouched."""
        target = store.system_path(MANAGED[1], "managed")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original")
        snapshot = store.create("backup", [], states)
        target.write_bytes(b"current")
        if corruption == "payload":
            (snapshot / "0001.bin").write_bytes(b"corrupt")
        elif corruption == "missing":
            (snapshot / "0001.bin").unlink()
        elif corruption == "manifest":
            (snapshot / "manifest.json").write_bytes(b"{}")
        else:
            (snapshot / "untracked").write_text("unexpected")
        with pytest.raises(ValueError):
            store.restore(snapshot)
        assert target.read_bytes() == b"current"

    @pytest.mark.parametrize("path", ["/etc/passwd", "/etc/shadowsocks-c/../../etc/passwd", "relative", "/root/.ssh/authorized_keys"])
    def test_malicious_manifest_path(self, store: SnapshotStore,
            states: list[ServiceState], path: str) -> None:
        """A matching checksum cannot bypass the compiled restore allowlist."""
        snapshot = store.create("backup", [], states)
        data = json.loads((snapshot / "manifest.json").read_bytes())
        data["files"][0]["path"] = path
        rewrite_manifest(snapshot, data)
        with pytest.raises(ValueError):
            store.restore(snapshot)

    def test_evidence_never_rewritten(self, store: SnapshotStore, states: list[ServiceState]) -> None:
        """Changed legacy bytes cause refusal instead of destructive restoration."""
        value = "/etc/shadowsocks-libev/config.json"
        source = store.system_path(value, "evidence")
        source.parent.mkdir(parents=True)
        source.write_bytes(b"original formatting\n")
        snapshot = store.create("migrate", [value], states)
        store.restore(snapshot)
        assert source.read_bytes() == b"original formatting\n"
        source.write_bytes(b"operator edit")
        with pytest.raises(ValueError, match="Legacy evidence changed"):
            store.restore(snapshot)
        assert source.read_bytes() == b"operator edit"

    @pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation needs separate privilege")
    def test_symlink_escape(self, store: SnapshotStore, states: list[ServiceState], tmp_path: Path) -> None:
        """A symlinked destination parent is rejected before snapshot creation."""
        outside = tmp_path / "outside"
        outside.mkdir()
        store.system_root.mkdir()
        (store.system_root / "etc").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="Symlink"):
            store.create("backup", [], states)

    def test_collisions_and_service_states(self, store: SnapshotStore, states: list[ServiceState]) -> None:
        """Same-second backups have unique IDs and preserve service states."""
        first = store.create("backup", [], states)
        second = store.create("safety", [], states)
        assert first != second
        assert store.verify(first).services == states
        assert store.verify(second).operation == "safety"

    def test_operation_validated_before_writing(self, store: SnapshotStore, states: list[ServiceState]) -> None:
        """An invalid operation cannot create a directory before validation."""
        with pytest.raises(ValueError):
            store.create("../../escape", [], states)
        assert not store.directory.exists()

    def test_recreates_traversable_binary_parents(self, store: SnapshotStore, states: list[ServiceState]) -> None:
        """A restored unprivileged daemon must be able to traverse its binary directory."""
        binary = store.system_path(MANAGED[0], "managed")
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"synthetic executable")
        binary.chmod(0o755)
        snapshot = store.create("backup", [], states)
        binary.unlink()
        binary.parent.rmdir()
        binary.parent.parent.rmdir()
        store.restore(snapshot)
        assert binary.read_bytes() == b"synthetic executable"
        if os.name != "nt":
            assert binary.parent.stat().st_mode & 0o777 == 0o755
            assert binary.parent.parent.stat().st_mode & 0o777 == 0o755

    @pytest.mark.parametrize("mutation", ["payload", "duplicate", "service", "incomplete"])
    def test_manifest_structure(self, store: SnapshotStore, states: list[ServiceState], mutation: str) -> None:
        """Reject structurally malicious but checksummed data."""
        snapshot = store.create("backup", [], states)
        data = json.loads((snapshot / "manifest.json").read_bytes())
        if mutation == "payload":
            data["files"][0]["payload"] = "../../escape"
        elif mutation == "duplicate":
            data["files"][1]["path"] = data["files"][0]["path"]
        elif mutation == "service":
            data["services"][0]["name"] = "ssh.service"
        else:
            data["files"].pop()
        rewrite_manifest(snapshot, data)
        with pytest.raises(ValueError):
            store.restore(snapshot)
