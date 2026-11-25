#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

error() { printf 'ERROR: %s\n' "$1" >&2; exit 3; }

[[ ${1:-} == '' || ${1:-} == --check ]] || error 'Usage: bash launch_gui.sh [--check]'
[[ $(uname -s) == Linux ]] || error 'Run this launcher on the Ubuntu server inside your forwarded SSH session.'
[[ -n ${DISPLAY:-} ]] || error 'DISPLAY is unset. Reconnect with MobaXterm X11 forwarding enabled; do not assign a display manually.'
[[ $DISPLAY =~ ^(localhost|127\.0\.0\.1|\[::1\])?:[0-9]+(\.[0-9]+)?$ ]] ||
    error 'Expected a local SSH-forwarded or Unix X11 display. Direct network X servers are unsupported.'
AUTHORITY=${XAUTHORITY:-${HOME:?HOME is required}/.Xauthority}
[[ $AUTHORITY == /* && -f $AUTHORITY && -r $AUTHORITY ]] ||
    error 'The session Xauthority file is missing or unreadable. Run from the original SSH login shell, before sudo -i.'
for tool in timeout xdpyinfo; do
    command -v "$tool" >/dev/null || error 'X11 tools are missing. Run sudo bash scripts/setup.sh --gui first.'
done
if ! XAUTHORITY="$AUTHORITY" timeout 10 xdpyinfo -display "$DISPLAY" > /dev/null 2>&1; then
    error 'Cannot authenticate to the forwarded X display. Check the MobaXterm X server and reconnect the SSH session.'
fi
printf 'X11 session: VERIFIED (display reachable; cookies are not printed).\n'
if [[ ${1:-} == --check ]]; then
    printf 'Session check complete. This does not test Qt dependencies or administrative workflows.\n'
    exit 0
fi
if (( EUID != 0 )); then
    command -v sudo >/dev/null || error 'sudo is required for administrative GUI operations.'
    printf 'Starting the Ubuntu GUI as root using this session X11 authorization.\n'
    exec sudo -- /usr/bin/env -i \
        PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
        DISPLAY="$DISPLAY" XAUTHORITY="$AUTHORITY" \
        QT_QPA_PLATFORM=xcb SCM_X11_FORWARDED=1 \
        /bin/bash "$ROOT/launch_gui.sh"
fi

/bin/bash "$ROOT/shadowsocks-c-manager.sh" --verify-installation
cd "$ROOT"
[[ $(uname -m) == x86_64 ]] || error 'The pinned Qt ARM64 wheel requires a newer glibc than Jammy. Use the CLI on this architecture.'
PYTHON="$ROOT/.venv/bin/python"
# Rebuild a minimal environment even when launched directly from a root SSH session.
CLEAN_ENV=(/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root
    "DISPLAY=$DISPLAY" "XAUTHORITY=$AUTHORITY" QT_QPA_PLATFORM=xcb SCM_X11_FORWARDED=1)
if ! "${CLEAN_ENV[@]}" "$PYTHON" -E -s -c 'from PySide6 import QtWidgets' > /dev/null 2>&1; then
    error 'Qt cannot be imported. Run sudo bash scripts/setup.sh --gui and inspect any installation error.'
fi
PLUGIN=$("${CLEAN_ENV[@]}" "$PYTHON" -E -s -c \
    'from PySide6.QtCore import QLibraryInfo; print(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath) + "/platforms/libqxcb.so")')
[[ -f $PLUGIN ]] || error 'The Qt xcb platform plugin is missing; reinstall requirements-gui.txt.'
command -v ldd >/dev/null || error 'ldd is required for Qt runtime dependency checks.'
if ! DEPENDENCIES=$(ldd "$PLUGIN" 2>&1); then
    printf '%s\n' "$DEPENDENCIES" >&2
    error 'Qt xcb dependencies cannot be inspected. Check the architecture and glibc requirements.'
fi
if [[ $DEPENDENCIES == *'not found'* ]]; then
    printf '%s\n' "$DEPENDENCIES" | sed -n '/not found/p' >&2
    error 'Qt xcb runtime libraries are missing. Run sudo bash scripts/setup.sh --gui.'
fi
printf 'Qt import and xcb library dependencies: VERIFIED. Opening the remote window.\n'
exec "${CLEAN_ENV[@]}" "$PYTHON" -E -s "$ROOT/launch_gui.py"
