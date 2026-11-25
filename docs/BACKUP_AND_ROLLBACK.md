# Backup and rollback

Root-owned 0700 directories under `/var/backups/shadowsocks-c` use UTC IDs:
`YYYYMMDD_HHMMSS_OPERATION_RANDOM`. Payloads are numbered regular files (0600).
`manifest.json` records version, operation, timestamp, existence, role, paths,
SHA-256, Unix mode/uid/gid and service enablement/activity.
`manifest.sha256` detects accidental manifest corruption. It is not a signature.

The fixed managed file allowlist includes the server binary, target config,
unit, provenance JSON and license archive. Optional evidence holds the original
source config and resolved unit fragment. The manager rejects symlinks rather
than claiming it can restore arbitrary symbolic links or unit overrides.
Enablement symlinks are reconstructed through systemctl from recorded state.

Create a snapshot with `backup`; inspect inventory using `list`. Invalid
snapshots remain listed as invalid and cannot be restored. Restore requires
the full immediate-child path from the trusted backup root. Payload paths are
generated internally and cannot traverse directories. Every checksum and
structure check completes before any service is stopped.

Rollback shows affected paths and services and asks for `ROLLBACK`. It then
captures a safety snapshot, writes a recovery pointer, stops affected services,
restores managed file bytes/metadata, reloads systemd and restores enablement
and activity. Legacy evidence must still match and is never overwritten. A
previously absent managed file is removed; existing files are atomically replaced.

If rollback fails, the safety snapshot is used for automatic compensation.
Retain both selected and safety snapshots. A failed compensation leaves the
pending pointer intact. Recovery is not guaranteed after hardware failure,
filesystem loss, SIGKILL or simultaneous changes by another root administrator.
The single-instance lock serializes manager operations, not all root activity.

Manual recovery: use a root console, verify checksums and inspect the manifest,
identify the intended service state, and rerun the manager's `rollback` command
with the recorded snapshot. If legacy evidence has changed or systemd itself
is broken, review those differences manually before copying anything. Never
source a manifest, run commands from it, extract arbitrary archives, or overwrite
legacy files blindly. Read the private journal locally. No automatic backup
retention or package removal takes place.
