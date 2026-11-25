"""Private, allowlisted snapshots with complete pre-restore verification."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scmanager.paths import atomic_write, private_directory, safe_path

MANAGED = (
    "/opt/shadowsocks-c/bin/ss-server",
    "/etc/shadowsocks-c/config.json",
    "/etc/systemd/system/shadowsocks-c-manager.service",
    "/opt/shadowsocks-c/provenance.json",
    "/opt/shadowsocks-c/licenses.tar",
)
SERVICE = "shadowsocks-c-manager.service"


class FileRecord(BaseModel):
    """One file's existence, role, metadata and payload identity."""

    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    role: Literal["managed", "evidence"]
    existed: bool
    payload: str
    sha256: str
    mode: int = Field(ge=0, le=0o777)
    uid: int = Field(ge=0)
    gid: int = Field(ge=0)


class ServiceState(BaseModel):
    """Recoverable enablement and runtime state."""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    enabled: Literal["enabled", "disabled", "not-found"]
    active: bool


class Manifest(BaseModel):
    """Versioned data-only snapshot manifest."""

    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    operation: Literal["install", "migrate", "backup", "safety"]
    created: str
    files: list[FileRecord]
    services: list[ServiceState]


def digest(path: Path) -> str:
    """Hash a regular file incrementally."""
    safe_path(path, must_exist=True)
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def valid_service(name: str) -> bool:
    """Allow only the replacement and simple legacy server units."""
    return name == SERVICE or bool(re.fullmatch(
        r"shadowsocks-libev(?:-server@[A-Za-z0-9_-]+)?\.service", name))


class SnapshotStore:
    """Snapshot engine; injected root supports isolated filesystem tests."""

    def __init__(self, directory: Path, system_root: Path) -> None:
        """Bind the trusted store and the filesystem namespace."""
        self.directory = directory.absolute()
        self.system_root = system_root.absolute()

    def system_path(self, value: str, role: str) -> Path:
        """Map an allowlisted absolute Unix path into the injected root."""
        if role == "managed":
            allowed = value in MANAGED
        else:
            allowed = bool(re.fullmatch(r"/etc/shadowsocks-libev/[A-Za-z0-9_.-]+\.json", value))
            allowed = allowed or bool(re.fullmatch(
                r"/(?:usr/)?lib/systemd/system/shadowsocks-libev(?:-server@)?\.service", value))
            allowed = allowed or bool(re.fullmatch(
                r"/etc/systemd/system/shadowsocks-libev(?:-server@[A-Za-z0-9_-]+)?\.service", value))
        if not allowed or ".." in Path(value).parts:
            raise ValueError("Snapshot path is outside the reviewed allowlist")
        result = self.system_root.joinpath(*value.lstrip("/").split("/"))
        safe_path(result)
        if os.name != "nt" and self.system_root == Path("/"):
            for item in (*reversed(result.parents), result):
                if item.exists():
                    info = item.stat()
                    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                        raise ValueError("System snapshot paths must be root-owned and not writable by others")
        return result

    def create(self, operation: str, evidence: list[str], services: list[ServiceState]) -> Path:
        """Copy managed state and immutable evidence, then verify all payloads."""
        if operation not in {"install", "migrate", "backup", "safety"}:
            raise ValueError("Unknown snapshot operation")
        private_directory(self.directory)
        for service in services:
            if not valid_service(service.name):
                raise ValueError("Unsupported service name")
        identifier = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = self.directory / f"{identifier}_{operation}_{uuid.uuid4().hex[:12]}"
        private_directory(destination)
        records: list[FileRecord] = []
        paths: list[tuple[str, Literal["managed", "evidence"]]] = [(item, "managed") for item in MANAGED]
        paths.extend((item, "evidence") for item in evidence)
        for index, (value, role) in enumerate(paths):
            source = self.system_path(value, role)
            existed = source.exists()
            payload = f"{index:04d}.bin"
            checksum = ""
            mode, uid, gid = 0o600, 0, 0
            if existed:
                info = source.stat()
                if info.st_size > 128 * 1024 * 1024:
                    raise ValueError("Snapshot file exceeds 128 MiB")
                mode, uid, gid = stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid
                if mode & ~0o777:
                    raise ValueError("Special permission bits are unsupported")
                atomic_write(destination / payload, source.read_bytes())
                checksum = digest(destination / payload)
                if checksum != digest(source):
                    raise ValueError("Source changed during backup")
            records.append(FileRecord(path=value, role=role, existed=existed,
                                      payload=payload, sha256=checksum, mode=mode, uid=uid, gid=gid))
        manifest = Manifest.model_validate({"operation": operation,
            "created": datetime.now(timezone.utc).isoformat(), "files": records, "services": services})
        raw = manifest.model_dump_json(indent=2).encode()
        atomic_write(destination / "manifest.json", raw)
        atomic_write(destination / "manifest.sha256", hashlib.sha256(raw).hexdigest().encode())
        self.verify(destination)
        return destination

    def verify(self, location: Path) -> Manifest:
        """Validate the entire snapshot before any service or destination mutation."""
        location = location.absolute()
        if location.parent != self.directory or not re.fullmatch(
                r"\d{8}_\d{6}_(install|migrate|backup|safety)_[a-f0-9]{12}", location.name):
            raise ValueError("Backup must be an immediate child of the trusted store")
        private_directory(self.directory)
        private_directory(location)
        manifest_path = safe_path(location / "manifest.json", True)
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("Manifest exceeds 1 MiB")
        checksum = safe_path(location / "manifest.sha256", True).read_text().strip()
        if digest(manifest_path) != checksum:
            raise ValueError("Manifest checksum mismatch")
        manifest = Manifest.model_validate_json(manifest_path.read_bytes())
        seen: set[str] = set()
        payloads = {"manifest.json", "manifest.sha256"}
        for index, record in enumerate(manifest.files):
            self.system_path(record.path, record.role)
            if record.path in seen or record.payload != f"{index:04d}.bin":
                raise ValueError("Duplicate path or invalid payload name")
            seen.add(record.path)
            if record.existed:
                payloads.add(record.payload)
                if not re.fullmatch(r"[a-f0-9]{64}", record.sha256):
                    raise ValueError("Invalid file checksum")
                payload = safe_path(location / record.payload, True)
                if payload.stat().st_size > 128 * 1024 * 1024 or digest(payload) != record.sha256:
                    raise ValueError("Payload checksum mismatch")
            elif record.sha256:
                raise ValueError("Absent file must have no checksum")
        managed = {record.path for record in manifest.files if record.role == "managed"}
        if managed != set(MANAGED) or {item.name for item in location.iterdir()} != payloads:
            raise ValueError("Incomplete snapshot or unexpected files")
        names = [item.name for item in manifest.services]
        if SERVICE not in names or len(names) != len(set(names)) or not all(map(valid_service, names)):
            raise ValueError("Invalid service records")
        return manifest

    def verify_evidence(self, manifest: Manifest) -> None:
        """Refuse to overwrite legacy files that changed since snapshot creation."""
        for record in manifest.files:
            if record.role == "evidence":
                target = self.system_path(record.path, record.role)
                if target.exists() != record.existed or (record.existed and digest(target) != record.sha256):
                    raise ValueError("Legacy evidence changed; manual review is required")

    def restore(self, location: Path) -> Manifest:
        """Restore managed files only after complete validation."""
        manifest = self.verify(location)
        self.verify_evidence(manifest)
        for record in manifest.files:
            if record.role != "managed":
                continue
            target = self.system_path(record.path, record.role)
            if record.existed:
                for directory in reversed(target.parents):
                    if directory == self.system_root or not directory.is_relative_to(self.system_root):
                        continue
                    if not directory.exists():
                        relative = "/" + directory.relative_to(self.system_root).as_posix()
                        modes = {"/opt/shadowsocks-c": 0o755, "/opt/shadowsocks-c/bin": 0o755,
                                 "/etc/shadowsocks-c": 0o700}
                        if relative not in modes:
                            raise ValueError("A shared system directory is missing; manual recovery is required")
                        directory.mkdir(mode=modes[relative])
                        directory.chmod(modes[relative])
                safe_path(target)
                atomic_write(target, (location / record.payload).read_bytes(), record.mode)
                if os.name != "nt":
                    os.chown(target, record.uid, record.gid)
            else:
                target.unlink(missing_ok=True)
        return manifest
