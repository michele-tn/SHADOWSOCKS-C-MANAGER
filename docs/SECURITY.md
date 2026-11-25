# Security design

Trusted boundary: root, installed manager source/venv and official upstream.
Untrusted inputs: JSON, paths, backup contents, terminal text and process output.
Use a root-owned source directory, not a writable shared checkout in production.
The launcher rejects group/world-writable code and symlinked project files.
Root can already tamper with snapshots; checksums detect corruption, not an
attacker capable of rewriting both manifest and payload. No authenticity claim.

Secrets are only in source/target configs, private credential copies and 0700
backups. Operational logs contain fixed messages and identifiers, never full
daemon diagnostics or configuration values. Daemon journal output is not copied
into manager logs. Build output is retained separately with root-only permissions.
Config errors list field names only. No shell eval, sourced manifests or remote
scripts. Restore validates paths, regular files, checksums, modes and ownership
before stopping a service. Symlinks and unexpected files block restoration.

Do not expose the GUI as a web service. No network listener is created by the
GUI. No firewall rule is changed. The daemon uses DynamicUser, no capabilities,
NoNewPrivileges and a read-only filesystem. The service receives its config via
LoadCredential, avoiding a persistent broadly readable config.

The SSH/X11 launcher preserves only display and authority-file location across
sudo and starts Qt with a clean loader environment from the trusted project
directory. It probes X access before and after elevation. It neither invokes
xhost nor copies/prints cookies. The forwarded X server and operator desktop
are trusted because they can interact with the privileged application. Loss of
the display/session is not evidence that an active operation stopped or recovered.

Report issues privately to the deployment maintainer; do not attach secrets.
This project has no hosted vulnerability intake or security support commitment.
