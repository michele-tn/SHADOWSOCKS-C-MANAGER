# Architecture

Bash owns privileged workflows and systemd transitions. Python owns strict JSON
validation, file snapshots, integrity verification and the Qt desktop interface.
Both interfaces use the same Bash engine. Python subprocesses use argument
arrays; manifests are data, never executable code. The GUI runs on the Ubuntu
server; MobaXterm displays its window through the existing SSH/X11 session.
The X11 launcher probes authorization before and after sudo, then starts Qt in a
clean environment with xcb. There is no application-owned SSH transport.
Optional Windows-local GUI inspection is read-only.

Installation: preflight → validate → snapshot consent → build/test → snapshot →
prepare → INSTALL confirmation → write → reload → start → local health → commit.

Migration: discover → parse resolved runtime → compatibility → record source
checksum/state → snapshot → build/test → prepare → MIGRATE confirmation → stop
legacy → write new unit/config → start → health → source checksum → disable
legacy boot activation → enable replacement → commit.

Rollback: verify selected snapshot → show paths/state → ROLLBACK confirmation →
safety snapshot → stop affected services → restore managed files → reload →
restore enablement/activity → verify services/sockets → retain both snapshots.

The cutover boundary starts only after explicit confirmation. ERR/INT/TERM
inside this boundary attempt verified restoration. A root-only recovery pointer
survives interruption; an unresolved transaction blocks new installations.
SIGKILL/power loss cannot run traps: use the recorded backup with rollback.
Dependency installations and build caches are outside the transaction; no APT
package is uninstalled during recovery. DynamicUser requires no persistent user.

Only one operation runs under flock. Qt uses QProcess signals on the GUI thread;
stdout contains progress, stderr contains redacted errors. The engine reads
confirmations from stdin, and emits explicit machine-readable prompt markers.
Cancellation sends SIGTERM to the process group on Linux; rollback ignores a
second TERM until recovery finishes. No fake progress or estimated percentages.

Snapshots record a fixed allowlist of managed files plus read-only legacy
evidence. Restore never writes legacy evidence: if those bytes changed, refuse
and ask for manual review. Symlinks and drop-ins are rejected in this release.
This narrower contract is safer than pretending arbitrary unit trees can be
reconstructed. Additional unrelated services/files are never restored.
