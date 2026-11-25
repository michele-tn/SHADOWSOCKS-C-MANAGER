#!/usr/bin/env bash
# Shared transaction state and audited paths.
VERSION=0.1.1
COMMIT=50f1ae54f737aa66f8edba05bdbf7250ff7f8a60
REPOSITORY=https://github.com/shadowsocks/shadowsocks-c.git
BACKUPS=/var/backups/shadowsocks-c
STATE=/var/lib/shadowsocks-c-manager
UNIT=shadowsocks-c-manager.service
CONFIG=/etc/shadowsocks-c/config.json
BINARY=/opt/shadowsocks-c/bin/ss-server
UNIT_FILE=/etc/systemd/system/shadowsocks-c-manager.service
TRANSACTION=0
SNAPSHOT=
WORK=
LEGACY=
SOURCE=
EVIDENCE=()
PHASE=initialization

helper() { "$SCM_PYTHON" -m scmanager.helper "$@"; }

event() {
    local level=$1 message=$2
    printf '[%s] %s\n' "$level" "$message"
    if [[ -n ${WORK:-} && -d $STATE ]]; then
        printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$level" "$message" >> "$STATE/operations.log"
    fi
}

fail() { event ERROR "$1" >&2; return 1; }

confirm() {
    local word=$1 answer
    printf '\nType %s to continue; any other input cancels.\n' "$word"
    printf 'SCM_PROMPT:%s\n' "$word"
    IFS= read -r answer || return 1
    [[ $answer == "$word" ]] || { event WARN 'Cancelled before the next change.'; return 1; }
}

private_dir() {
    local path=$1 current=/ part permissions
    local -a parts
    [[ $path == /* ]] || return 1
    IFS=/ read -r -a parts <<< "$path"
    for part in "${parts[@]}"; do
        [[ -n $part ]] || continue
        current="${current%/}/$part"
        [[ ! -L $current && $part != .. ]] || fail 'Unsafe directory path.'
        if [[ -e $current ]]; then
            [[ -d $current && $(stat -c %u "$current") == 0 ]] || fail 'Untrusted directory owner.'
            permissions=$(stat -c %a "$current")
            (( (8#$permissions & 0022) == 0 )) || fail 'Writable directory ancestor.'
        fi
    done
    if [[ ! -e $path ]]; then
        mkdir -p -- "$path"
        chmod 700 "$path"
    fi
    [[ -d $path && ! -L $path ]] || return 1
}

initialize() {
    preflight
    private_dir "$STATE"
    chmod 700 "$STATE"
    [[ ! -L $STATE/lock && ! -L $STATE/operations.log && ! -L $STATE/pending ]] || fail 'Unsafe state files.'
    exec 9> "$STATE/lock"
    flock -n 9 || fail 'Another manager operation is running; wait for it to finish.'
    private_dir "$BACKUPS"
    chmod 700 "$BACKUPS"
    WORK=$(mktemp -d "$STATE/work.XXXXXXXX")
    trap 'on_failure "$?"' ERR
    trap 'on_failure 130' INT
    trap 'on_failure 143' TERM
    trap cleanup EXIT
}

cleanup() {
    if [[ -n $WORK && -f $WORK/build.log && -d $STATE ]]; then
        cp -- "$WORK/build.log" "$STATE/last-build.log"
    fi
    if [[ -n $WORK && $WORK == "$STATE"/work.* && -d $WORK && ! -L $WORK ]]; then
        rm -rf -- "$WORK"
    fi
}

on_failure() {
    local code=$1
    trap - ERR
    trap '' INT TERM
    set +e
    event ERROR "Stopped during $PHASE (exit $code). Review private logs in $STATE."
    if (( TRANSACTION == 1 )); then
        event ERROR 'Operation interrupted after cutover began; attempting snapshot recovery.'
        if (set -Eeuo pipefail; recover_snapshot "$SNAPSHOT"); then
            event INFO 'Recovery VERIFIED: previous file and service state restored.'
            rm -f -- "$STATE/pending"
        else
            event ERROR "Recovery FAILED. Retain backups. Run rollback using $SNAPSHOT on this host."
        fi
    else
        event ERROR 'Operation stopped before cutover. Existing services were not deliberately changed.'
    fi
    exit "$code"
}

save_states() {
    local output=$1 service enabled active load
    : > "$output"
    for service in "$UNIT" ${LEGACY:+"$LEGACY"}; do
        load=$(systemctl show "$service" -p LoadState --value) || [[ $load == not-found ]]
        if [[ $load == not-found ]]; then
            enabled=not-found; active=inactive
        else
            [[ $load == loaded ]] || fail 'Unexpected systemd load state.'
            enabled=$(systemctl is-enabled "$service" 2>/dev/null) || [[ $enabled == disabled ]]
            [[ $enabled == enabled || $enabled == disabled ]] || fail 'Masked, static or unusual enablement cannot be restored safely.'
            active=$(systemctl show "$service" -p ActiveState --value)
            [[ $active == active || $active == inactive ]] || fail 'Service is in a transitional or failed state.'
        fi
        printf '%s\t%s\t%s\n' "$service" "$enabled" "$active" >> "$output"
    done
}

make_snapshot() {
    local operation=$1
    save_states "$WORK/states.tsv"
    SNAPSHOT=$(helper create "$BACKUPS" "$operation" "$WORK/states.tsv" "${EVIDENCE[@]}")
    event INFO "Verified snapshot: $SNAPSHOT"
}

begin_transaction() {
    printf '%s\n' "$SNAPSHOT" > "$STATE/pending"
    TRANSACTION=1
}

commit_transaction() {
    rm -f -- "$STATE/pending"
    TRANSACTION=0
    event INFO 'Operation completed. Local service checks passed; remote connectivity is untested.'
}
