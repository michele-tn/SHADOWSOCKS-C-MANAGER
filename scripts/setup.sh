#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
[[ ${1:-} == '' || ${1:-} == --gui ]] || { printf 'Usage: bash scripts/setup.sh [--gui]\n' >&2; exit 2; }
GUI=${1:-}
if [[ $GUI == --gui ]]; then
    (( EUID == 0 )) || { printf 'GUI setup requires sudo on the Ubuntu server.\n' >&2; exit 3; }
    [[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
        printf 'Pinned Qt GUI packages support Jammy x86_64 here. Use the CLI on ARM64.\n' >&2; exit 3;
    }
    if ! grep -qx 'ID=ubuntu' /etc/os-release || ! grep -qx 'VERSION_ID="22.04"' /etc/os-release; then
        printf 'GUI setup requires Ubuntu 22.04.\n' >&2
        exit 3
    fi
    packages=(python3-venv xauth x11-utils libxcb-cursor0 libxkbcommon-x11-0
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
        libxcb-xinerama0 libxcb-randr0 libxcb-shape0 libxcb-xfixes0
        libxcb-sync1 libxcb-render0 libxcb-shm0 libxcb-xkb1 libx11-xcb1
        libdbus-1-3 libegl1 libgl1 libfontconfig1 fonts-dejavu-core)
    missing=()
    for package in "${packages[@]}"; do
        status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) || status=missing
        [[ $status == 'install ok installed' ]] || missing+=("$package")
    done
    if (( ${#missing[@]} )); then
        printf 'Installing missing Ubuntu X11/Qt runtime packages: %s\n' "${missing[*]}"
        apt-get update
        apt-get install --no-install-recommends --no-upgrade -y "${missing[@]}"
    fi
fi
if [[ -e $ROOT/.venv && $GUI == --gui ]]; then
    /bin/bash "$ROOT/shadowsocks-c-manager.sh" --verify-installation
elif [[ ! -e $ROOT/.venv && ! -L $ROOT/.venv ]]; then
    python3 -E -s -m venv --copies "$ROOT/.venv"
else
    printf 'Environment already exists. Review it before reuse; setup never overwrites an existing venv.\n' >&2
    exit 1
fi
if [[ $GUI == --gui ]]; then
    "$ROOT/.venv/bin/python" -E -s -m pip install -r "$ROOT/requirements-gui.txt"
    printf 'GUI dependencies installed. From the original MobaXterm SSH shell: bash launch_gui.sh\n'
else
    "$ROOT/.venv/bin/python" -E -s -m pip install -r "$ROOT/requirements.txt"
    printf 'Core installed. Add SSH/X11 GUI support with: sudo bash scripts/setup.sh --gui\n'
fi
