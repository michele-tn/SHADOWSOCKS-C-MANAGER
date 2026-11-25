# Troubleshooting

| Message/state | Safe next step |
| --- | --- |
| Windows inspection-only | Run administrative workflows locally on Ubuntu; no remote transport exists. |
| Root-owned project required | Deploy to a trusted directory with root ownership and no group/world write; recreate the venv there. |
| Unsupported OS | Use a disposable Ubuntu 22.04.5 VM. Do not bypass preflight on production. |
| EnvironmentFiles/drop-ins/hooks | Review actual unit semantics; automated migration refuses ambiguity. |
| Incompatible configuration | Consult the supported profile. Do not change working credentials/cipher merely to bypass validation. |
| Build failed | Inspect `/var/lib/shadowsocks-c-manager/last-build.log` locally. Legacy service is retained before cutover. |
| Port occupied | Identify the owner using `ss -lntup`; never kill an arbitrary process. |
| Service failed health | Read `systemctl status` and `journalctl -u shadowsocks-c-manager.service` locally; review recovery outcome. |
| Recovery FAILED | Keep the provider console open, preserve snapshots, inspect pending pointer and use rollback after resolving the cause. |
| Corrupted snapshot | Do not restore it. Choose a verified snapshot; retain damaged files for diagnosis. |
| Legacy evidence changed | Review the operator's edits. Automated restore deliberately does not overwrite them. |
| Incomplete transaction | Inspect `/var/lib/shadowsocks-c-manager/pending`, list backups and run rollback. |
| Qt platform plugin error | Run sudo bash scripts/setup.sh --gui on Ubuntu, then bash launch_gui.sh from the original MobaXterm SSH/X11 session. |

Credentials are in the private config and backup payloads. Never paste these
files into issue reports. The manager's ordinary log is intentionally redacted;
daemon journal/build diagnostics remain local and may require review before
sharing. A listening service does not prove routing, firewall or client success.
