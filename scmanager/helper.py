"""Small structured-data boundary for the Bash engine."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from scmanager.backup import ServiceState, SnapshotStore, digest
from scmanager.models import ConfigurationError, load_config, parse_config
from scmanager.paths import atomic_write


def read_states(path: Path) -> list[ServiceState]:
    """Decode engine-produced service state without executing it."""
    result = []
    for line in path.read_text().splitlines():
        name, enabled, active = line.split("\t")
        result.append(ServiceState.model_validate({"name": name, "enabled": enabled,
                                                   "active": active == "active"}))
    return result


def legacy_exec(value: str) -> str:
    """Accept only a fully resolved single ss-server -c invocation."""
    match = re.fullmatch(
        r"\{ path=/usr/bin/ss-server ; argv\[\]=/usr/bin/ss-server -c "
        r"(/etc/shadowsocks-libev/[A-Za-z0-9_.-]+\.json) ; ignore_errors=no ; .* \}",
        value.strip())
    if not match or ".." in Path(match[1]).parts:
        raise ValueError("Legacy ExecStart is not a reviewed explicit server invocation")
    return match[1]


def socket_check(raw: str, address: str, port: int, pid: int) -> bool:
    """Check ss output for the exact local endpoint owned by the service PID."""
    import ipaddress
    expected = ipaddress.ip_address(address)
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 5 or f"pid={pid}," not in line:
            continue
        endpoint = fields[3]
        host, separator, number = endpoint.rpartition(":")
        if not separator or number != str(port):
            continue
        host = host.strip("[]")
        if host == "*":
            # ss wildcard output is acceptable only for the matching wildcard family.
            host = "::" if expected.version == 6 else "0.0.0.0"
        try:
            if ipaddress.ip_address(host) == expected:
                return True
        except ValueError:
            continue
    return False


def main() -> int:
    """Dispatch fixed helper commands; never print sensitive exception inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "transform", "facts", "hash", "create",
                        "verify", "evidence", "restore", "describe", "services", "legacy-exec",
                        "socket", "new-config", "wizard"])
    parser.add_argument("values", nargs="*")
    args = parser.parse_args()
    values = args.values
    try:
        if args.command == "wizard":
            import getpass
            import secrets
            print("Fresh server configuration (ports 1024–65535; no firewall changes)")
            address = input("Listening IP [0.0.0.0]: ").strip() or "0.0.0.0"
            port = int(input("Listening port [8388]: ").strip() or "8388")
            method = input("Method [aes-256-gcm]: ").strip() or "aes-256-gcm"
            mode = input("Mode [tcp_and_udp]: ").strip() or "tcp_and_udp"
            password = getpass.getpass("Password (empty = generate hidden random password): ") or secrets.token_urlsafe(32)
            config = parse_config(json.dumps({"server": address, "server_port": port,
                "password": password, "method": method, "mode": mode}).encode())
            atomic_write(Path(values[0]), config.target_bytes())
            print("Credentials will be stored privately in /etc/shadowsocks-c/config.json.")
        elif args.command == "new-config":
            config = parse_config(sys.stdin.buffer.read(1024 * 1024 + 1))
            atomic_write(Path(values[0]), config.target_bytes())
        elif args.command in {"validate", "transform", "facts"}:
            config = load_config(Path(values[0]))
            if args.command == "transform":
                atomic_write(Path(values[1]), config.target_bytes())
            elif args.command == "facts":
                print(config.server, config.server_port, config.method, config.mode, sep="\t")
            else:
                print("Configuration profile: VERIFIED (no end-to-end test)")
        elif args.command == "hash":
            print(digest(Path(values[0])))
        elif args.command == "legacy-exec":
            print(legacy_exec(sys.stdin.read()))
        elif args.command == "socket":
            if not socket_check(sys.stdin.read(), values[0], int(values[1]), int(values[2])):
                raise ValueError("Expected listening socket is not owned by the service")
        else:
            store = SnapshotStore(Path(values[0]), Path("/"))
            if args.command == "create":
                print(store.create(values[1], values[3:], read_states(Path(values[2]))))
            else:
                location = Path(values[1])
                manifest = store.verify(location)
                if args.command == "restore":
                    store.restore(location)
                elif args.command == "evidence":
                    store.verify_evidence(manifest)
                elif args.command == "services":
                    for state in manifest.services:
                        print(state.name, state.enabled, "active" if state.active else "inactive", sep="\t")
                elif args.command == "describe":
                    print(f"{manifest.created} | {manifest.operation} | integrity VERIFIED")
                    for record in manifest.files:
                        print(f"{record.role}: {record.path} | previously "
                              + ("present" if record.existed else "absent"))
                    for state in manifest.services:
                        print(f"service: {state.name} | {state.enabled} | active={state.active}")
                else:
                    print("Backup integrity: VERIFIED")
        return 0
    except ConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
    except (OSError, ValueError, ValidationError, IndexError):
        print("ERROR: Structured data or filesystem validation failed. Check permissions, "
              "supported settings and snapshot integrity; no secrets are displayed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
