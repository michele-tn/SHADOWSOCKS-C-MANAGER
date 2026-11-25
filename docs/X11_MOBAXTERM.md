# Ubuntu GUI over MobaXterm SSH/X11

## Execution model

The application runs on Ubuntu Server 22.04.5. MobaXterm on Windows provides
the X server; SSH forwards X11 traffic. All paths in the GUI refer to the Ubuntu
filesystem. Windows does not need Python, Qt or a local application installation
for this workflow. The application does not open another SSH connection.

Current GUI wheel target: x86_64, Python >=3.10 and Jammy glibc 2.35. PyPI's
PySide6_Essentials 6.10.1 wheel declares manylinux_2_34_x86_64. Its ARM64 wheel
declares manylinux_2_39_aarch64, so the GUI setup explicitly refuses ARM64 on
Jammy. Use the CLI there; a different Qt build would need separate verification.

## Setup on Ubuntu

1. Start MobaXterm's X server. Enable **X11-Forwarding** in the SSH session.
   Connect to Ubuntu using that session. The server must permit X11 forwarding
   and have xauth installed. The setup below installs xauth if absent; reconnect
   afterwards if the original session did not receive a DISPLAY.
2. Deploy the source under `/opt/shadowsocks-c-manager`. Keep the directory and
   all its ancestors root-owned and not writable by other users.
3. In the original SSH login shell run:

```bash
cd /opt/shadowsocks-c-manager
sudo chown -R root:root /opt/shadowsocks-c-manager
sudo chmod -R go-w /opt/shadowsocks-c-manager
sudo bash scripts/setup.sh --gui
bash launch_gui.sh --check
bash launch_gui.sh
```

The setup installs only missing Ubuntu runtime packages with no requested
upgrades and installs pinned Python GUI requirements into the private venv.
It can extend an existing venv only after the privileged installation check.
It does not install a desktop environment or alter sshd configuration.

`--check` verifies only the current display/authority connection without sudo
or administrative operations. Normal launch validates it again after elevation,
then checks Qt import and the xcb plugin's shared library dependencies.

## Privilege and authorization

Run the launcher **without a preceding sudo** from the original SSH shell. It
requests sudo itself, preserves DISPLAY and the authority-file path explicitly,
and discards the rest of the caller environment. It uses XAUTHORITY when set,
otherwise the login user's default `$HOME/.Xauthority`. Cookies are neither
printed nor copied into a persistent root authority file. A direct root SSH
session is supported when it already has a functioning forwarded display.

The launcher selects Qt's xcb platform. It does not use `xhost +`, open TCP port
6000, replace the display with a Windows IP, or preserve arbitrary Qt/Python
loader variables through sudo. The Windows X server and the operator's desktop
are part of the trusted interaction boundary because the GUI runs as root.

## Troubleshooting

| Failure | Action |
| --- | --- |
| DISPLAY unset | Enable forwarding, check the server's effective SSH configuration and reconnect. Do not invent a DISPLAY value. |
| Authority missing | Run from the original SSH login shell. If your SSH setup uses a custom authority file, export its real existing path before launch. |
| Connection check failed | Start MobaXterm's X server; reconnect the forwarded SSH session. |
| User check passes, root check fails | Check whether root can read the authority file, including NFS/root-squash restrictions. No access-control bypass is attempted. |
| xcb libraries missing | Rerun `sudo bash scripts/setup.sh --gui`; the launcher lists missing library names. |
| Qt import fails | Review setup errors and architecture. Use the pinned GUI requirements in the project venv. |
| Qt cannot connect after a long delay | The forwarded authorization may have expired; reconnect before starting a new operation. |
| Connection lost during an operation | Reconnect, inspect the engine state and pending recovery pointer before retrying. A lost window does not prove completion or rollback. |

Keep the SSH session and X server open during an operation. SIGKILL, a fatal X
connection error or network loss may prevent GUI cleanup. Do not assume the
engine stopped when the window disappears. Use the CLI diagnostics, journal
and `/var/lib/shadowsocks-c-manager/pending` to reconcile actual state. Ordinary
GUI Cancel remains a request followed by verified engine recovery where possible.

## Evidence and sources

Launcher session checks have synthetic Bash tests; Qt widgets render offscreen.
No live MobaXterm-to-Ubuntu forwarded GUI test was available on the development
host. The checks at application launch run on the actual target, but do not
establish Shadowsocks client relay or full systemd workflow compatibility.

- https://mobaxterm.mobatek.net/documentation.html
- https://doc.qt.io/qt-6.10/linux-requirements.html
- https://manpages.ubuntu.com/manpages/jammy/man1/xauth.1.html
- https://packages.ubuntu.com/jammy/libxcb-cursor0
- https://packages.ubuntu.com/jammy/libxkbcommon-x11-0
- https://pypi.org/pypi/PySide6_Essentials/6.10.1/json
