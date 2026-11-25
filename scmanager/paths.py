"""Filesystem boundaries shared by backup and configuration helpers."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def safe_path(path: Path, must_exist: bool = False) -> Path:
    """Reject relative paths, traversal, symlink ancestors and special files."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("An absolute path without traversal is required")
    for item in (*reversed(path.parents), path):
        if item.is_symlink():
            raise ValueError("Symlink paths are unsupported")
    if must_exist and not path.is_file():
        raise ValueError("Required regular file is missing")
    if path.exists() and not path.is_file():
        raise ValueError("Expected a regular file")
    return path


def private_directory(path: Path) -> None:
    """Create or verify a private directory without following symlinks."""
    for item in (*reversed(path.parents), path):
        if item.is_symlink():
            raise ValueError("Symlink directory is forbidden")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        info = path.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Private directory must be owned by the operator and mode 0700")


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Replace one regular file atomically using an exclusive sibling temporary."""
    import tempfile
    safe_path(path)
    descriptor, name = tempfile.mkstemp(prefix=".scm-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
