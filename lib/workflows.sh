#!/usr/bin/env bash
fresh_install() {
    assert_fresh
    if [[ ${1:-} == --stdin ]]; then
        local raw
        printf 'SCM_INPUT:CONFIG\n'
        IFS= read -r raw
        printf '%s' "$raw" | helper new-config "$WORK/target.json"
        unset raw
    elif [[ -n ${1:-} ]]; then
        helper transform "$1" "$WORK/target.json"
    else
        helper wizard "$WORK/target.json"
    fi
    local address port cipher mode
    IFS=$'\t' read -r address port cipher mode < <(helper facts "$WORK/target.json")
    port_free "$port"
    build_upstream
    make_snapshot install
    prepare_unit
    printf 'Install %s on %s:%s (%s). Backup: %s\n' "$cipher" "$address" "$port" "$mode" "$SNAPSHOT"
    confirm INSTALL
    begin_transaction
    write_installation
    START_TIME=$(date -u +%FT%TZ)
    systemctl start "$UNIT"
    health "$UNIT" "$CONFIG" "$BINARY"
    systemctl enable "$UNIT"
    commit_transaction
}

migrate() {
    [[ ! -e $BINARY && ! -e $CONFIG && ! -e $UNIT_FILE && ! -L $UNIT_FILE ]] || fail 'Destination already exists; review it before migration.'
    discover_legacy
    local original_hash address port cipher mode
    original_hash=$(helper hash "$SOURCE")
    helper transform "$SOURCE" "$WORK/target.json"
    make_snapshot migrate
    build_upstream
    prepare_unit
    IFS=$'\t' read -r address port cipher mode < <(helper facts "$WORK/target.json")
    START_TIME=$(date -u +%FT%TZ)
    health "$LEGACY" "$SOURCE" /usr/bin/ss-server
    printf 'Source: %s\nService: %s\nEndpoint: %s:%s\nCipher: %s\nMode: %s\nBackup: %s\nOriginal source bytes will remain unchanged.\n' \
        "$SOURCE" "$LEGACY" "$address" "$port" "$cipher" "$mode" "$SNAPSHOT"
    confirm MIGRATE
    [[ $(helper hash "$SOURCE") == "$original_hash" ]] || fail 'Source changed during preparation.'
    helper evidence "$BACKUPS" "$SNAPSHOT"
    begin_transaction
    systemctl stop "$LEGACY"
    port_free "$port"
    write_installation
    START_TIME=$(date -u +%FT%TZ)
    systemctl start "$UNIT"
    health "$UNIT" "$CONFIG" "$BINARY"
    [[ $(helper hash "$SOURCE") == "$original_hash" ]] || fail 'Original configuration checksum changed.'
    systemctl disable "$LEGACY"
    systemctl enable "$UNIT"
    event INFO 'Original source SHA-256 unchanged; legacy package, executable and files retained.'
    commit_transaction
}

backup_current() {
    local units
    units=$(systemctl list-units --all --plain --no-legend 'shadowsocks-libev*')
    if [[ -n $units ]]; then
        discover_legacy
    fi
    make_snapshot backup
}

list_backups() {
    local path
    shopt -s nullglob
    for path in "$BACKUPS"/*; do
        [[ -d $path && ! -L $path ]] || continue
        printf '\n%s\n' "$path"
        if ! helper describe "$BACKUPS" "$path"; then
            event WARN 'Backup is invalid; restoration will be refused.'
        fi
    done
}

rollback() {
    local selected=${1:-} service _enabled _active
    if [[ -z $selected ]]; then
        list_backups
        printf 'Enter the full backup path (empty cancels): '
        IFS= read -r selected
        [[ -n $selected ]] || return 1
    fi
    helper describe "$BACKUPS" "$selected"
    helper evidence "$BACKUPS" "$selected"
    helper services "$BACKUPS" "$selected" > "$WORK/selected-states.tsv"
    LEGACY=
    while IFS=$'\t' read -r service _enabled _active; do
        [[ $service == "$UNIT" ]] || LEGACY=$service
    done < "$WORK/selected-states.tsv"
    EVIDENCE=()
    # Evidence discovery is repeated for an active legacy service, never selected arbitrarily.
    if [[ -n $LEGACY && $(systemctl show "$LEGACY" -p ActiveState --value) == active ]]; then
        discover_legacy
    fi
    printf 'This restores managed files and recorded service states. Legacy evidence is never overwritten.\n'
    confirm ROLLBACK
    make_snapshot safety
    begin_transaction
    START_TIME=$(date -u +%FT%TZ)
    recover_snapshot "$selected"
    commit_transaction
}

diagnostics() {
    printf 'System: %s\nManager: %s\nArchitecture: %s\n' "$(detect_system)" "$VERSION" "$(uname -m)"
    if command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
        systemctl show "$UNIT" -p LoadState -p ActiveState -p UnitFileState
        dpkg-query -W -f='${Package} ${Version}\n' shadowsocks-libev 2>/dev/null || true
        printf 'Firewall: not modified. Inspect local rules and cloud policy manually.\n'
    else
        printf 'Administration unavailable: running systemd required.\n'
    fi
}

main() {
    local operation=${1:-} choice
    shift || true
    if [[ $operation == --help ]]; then
        printf '%s\n' 'Usage: shadowsocks-c-manager.sh [install [CONFIG|--stdin]|migrate|backup|rollback [BACKUP]|list|diagnose]' \
            'Interactive menu has three primary modes. Destructive operations always require typed confirmation.'
        return
    fi
    [[ $operation != diagnose ]] || { diagnostics; return; }
    if [[ -z $operation ]]; then
        printf '\nSHADOWSOCKS-C MANAGER\n\n1. Fresh Installation\n2. Migrate from Shadowsocks-Libev\n3. Backup & Rollback\n\n'
        diagnostics
        printf '\nSelect an operation [1-3], or empty to exit: '
        IFS= read -r choice
        case "$choice" in
            1) operation=install ;;
            2) operation=migrate ;;
            3)
                printf 'Backup & Rollback: [b] create backup, [l] list, [r] rollback: '
                IFS= read -r choice
                case "$choice" in b) operation=backup ;; l) operation=list ;; r) operation=rollback ;; *) return 2 ;; esac ;;
            '') return ;;
            *) fail 'Select one of the three modes.' ;;
        esac
    fi
    case "$operation" in install|migrate|backup|rollback|list) ;; *) fail 'Unknown operation. Use --help.' ;; esac
    initialize
    if [[ -s $STATE/pending && $operation != rollback && $operation != list ]]; then
        fail 'An incomplete transaction exists. Review /var/lib/shadowsocks-c-manager/pending and run rollback.'
    fi
    event INFO "Operation started: $operation"
    case "$operation" in
        install) fresh_install "${1:-}" ;;
        migrate) migrate ;;
        backup) backup_current ;;
        rollback) rollback "${1:-}" ;;
        list) list_backups ;;
    esac
}
