#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV ENV CDPATH
SCM_HOME=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly SCM_HOME
# Privileged execution must never load a writable or symlinked project.
if (( EUID == 0 )); then
    ancestor=$SCM_HOME
    while :; do
        permissions=$(stat -c %a "$ancestor")
        if [[ $(stat -c %u "$ancestor") != 0 ]] || (( (8#$permissions & 0022) != 0 )); then
            printf '%s\n' 'ERROR: Privileged project ancestors must be root-owned and not group/world writable.' >&2
            exit 3
        fi
        [[ $ancestor != / ]] || break
        ancestor=$(dirname -- "$ancestor")
    done
    if [[ -L ${BASH_SOURCE[0]} ]] || [[ $(stat -c %u "$SCM_HOME") != 0 ]] ||
       find "$SCM_HOME" -xdev -path "$SCM_HOME/.venv" -prune -o \( -type l -o -perm /022 -o ! -user root \) -print -quit | grep -q .; then
        printf '%s\n' 'ERROR: Install this project as root-owned, nonsymlink, non-writable code.' >&2
        exit 3
    fi
fi
if [[ -L $SCM_HOME/.venv ]]; then
    printf '%s\n' 'ERROR: A symlinked Python environment is not trusted.' >&2
    exit 3
fi
if (( EUID == 0 )) && find "$SCM_HOME/.venv" -xdev \( -perm /022 -o ! -user root \) ! -type l -print -quit | grep -q .; then
    printf '%s\n' 'ERROR: Python environment must be root-owned and not group/world writable.' >&2
    exit 3
fi
if (( EUID == 0 )); then
    if find "$SCM_HOME/.venv" -xdev -type l ! -path "$SCM_HOME/.venv/lib64" -print -quit | grep -q .; then
        printf '%s\n' 'ERROR: Unexpected symlinks in the privileged Python environment.' >&2
        exit 3
    fi
    if [[ -L $SCM_HOME/.venv/lib64 && $(readlink -f "$SCM_HOME/.venv/lib64") != "$SCM_HOME/.venv/lib" ]]; then
        printf '%s\n' 'ERROR: Invalid virtual environment library alias.' >&2
        exit 3
    fi
fi
SCM_PYTHON="$SCM_HOME/.venv/bin/python"
[[ -x $SCM_PYTHON ]] || { printf '%s\n' 'Run scripts/setup.sh first (private Python venv required).' >&2; exit 3; }
if [[ ${1:-} == --verify-installation ]]; then
    (( EUID == 0 )) || { printf 'Root is required to verify a privileged installation.\n' >&2; exit 3; }
    exit 0
fi
export PYTHONPATH="$SCM_HOME"
export PYTHONNOUSERSITE=1
# shellcheck source=lib/common.sh
source "$SCM_HOME/lib/common.sh"
# shellcheck source=lib/system.sh
source "$SCM_HOME/lib/system.sh"
# shellcheck source=lib/service.sh
source "$SCM_HOME/lib/service.sh"
# shellcheck source=lib/workflows.sh
source "$SCM_HOME/lib/workflows.sh"
main "$@"
