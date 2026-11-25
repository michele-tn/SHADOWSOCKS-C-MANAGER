#!/usr/bin/env bash
prepare_unit() {
    cat > "$WORK/$UNIT" <<'UNIT'
[Unit]
Description=Shadowsocks-C managed server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
LoadCredential=config.json:/etc/shadowsocks-c/config.json
ExecStart=/opt/shadowsocks-c/bin/ss-server -c %d/config.json
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
    mkdir "$WORK/unit-check"
    sed "s|ExecStart=/opt/shadowsocks-c/bin/ss-server|ExecStart=$WORK/build/bin/ss-server|" \
        "$WORK/$UNIT" > "$WORK/unit-check/$UNIT"
    systemd-analyze verify "$WORK/unit-check/$UNIT" > "$WORK/unit-check.log" 2>&1
    event INFO 'Prepared unit verified against the staged executable before cutover.'
}

write_installation() {
    PHASE='managed file installation and systemd reload'
    private_dir /opt/shadowsocks-c
    private_dir /opt/shadowsocks-c/bin
    chmod 755 /opt/shadowsocks-c /opt/shadowsocks-c/bin
    private_dir /etc/shadowsocks-c
    install -m 755 -- "$WORK/build/bin/ss-server" "$BINARY"
    install -m 600 -- "$WORK/target.json" "$CONFIG"
    install -m 644 -- "$WORK/$UNIT" "$UNIT_FILE"
    printf '{"commit":"%s","repository":"%s","profile":"reviewed-aead","stable_release":false}\n' \
        "$COMMIT" "$REPOSITORY" > /opt/shadowsocks-c/provenance.json
    install -m 600 -- "$WORK/licenses.tar" /opt/shadowsocks-c/licenses.tar
    systemd-analyze verify "$UNIT_FILE" > "$WORK/unit-check.log" 2>&1
    systemctl daemon-reload
}

health() {
    PHASE='service and local socket health checks'
    local service=$1 config=$2 binary=$3 address port _cipher mode pid protocol errors family sockets
    [[ -x $binary && ! -L $binary ]] || { fail 'Expected executable is missing or unsafe.'; return 1; }
    helper validate "$config" || return 1
    IFS=$'\t' read -r address port _cipher mode < <(helper facts "$config") || return 1
    family=-4
    [[ $address != *:* ]] || family=-6
    for _ in {1..10}; do
        if systemctl is-active --quiet "$service"; then
            pid=$(systemctl show "$service" -p MainPID --value) || return 1
            [[ $pid =~ ^[1-9][0-9]*$ && -d /proc/$pid ]] || { sleep 1; continue; }
            [[ $(readlink -f "/proc/$pid/exe") == "$binary" ]] || { fail 'Service PID does not execute the expected binary.'; return 1; }
            local sockets_ok=1
            for protocol in tcp udp; do
                if [[ $protocol == tcp ]]; then
                    sockets=$(ss "$family" -H -lntp "sport = :$port") || return 1
                else
                    sockets=$(ss "$family" -H -lnup "sport = :$port") || return 1
                fi
                if [[ $protocol == tcp && $mode == udp_only || $protocol == udp && $mode == tcp_only ]]; then
                    if printf '%s' "$sockets" | helper socket "$address" "$port" "$pid" > /dev/null 2>&1; then
                        fail 'Service owns an unexpected listener for a disabled protocol.'
                        return 1
                    fi
                else
                    printf '%s' "$sockets" | helper socket "$address" "$port" "$pid" > /dev/null 2>&1 || sockets_ok=0
                fi
            done
            if (( sockets_ok )); then
                sleep 2
                systemctl is-active --quiet "$service" || { fail 'Service did not remain active.'; return 1; }
                errors=$(journalctl -u "$service" --since "$START_TIME" -p err --no-pager -q | wc -l) || return 1
                (( errors == 0 )) || { fail 'Service journal contains error entries; inspect locally without sharing secrets.'; return 1; }
                event INFO 'Health VERIFIED: active process and selected local listening sockets. Client relay untested.'
                return 0
            fi
        fi
        sleep 1
    done
    fail 'Expected service process/socket health was not established.'
}

recover_snapshot() {
    PHASE='snapshot restoration'
    local backup=$1 service enabled active legacy_config
    helper verify "$BACKUPS" "$backup" || return 1
    helper evidence "$BACKUPS" "$backup" || return 1
    helper services "$BACKUPS" "$backup" > "$WORK/restore-states.tsv" || return 1
    while IFS=$'\t' read -r service enabled active; do
        if [[ $(systemctl show "$service" -p LoadState --value) != not-found ]]; then
            systemctl stop "$service" || return 1
            if [[ $service == "$UNIT" ]]; then
                systemctl disable "$service" > /dev/null || return 1
            fi
        fi
    done < "$WORK/restore-states.tsv"
    helper restore "$BACKUPS" "$backup" || return 1
    systemctl daemon-reload || return 1
    while IFS=$'\t' read -r service enabled active; do
        case "$enabled" in
            enabled) systemctl enable "$service" > /dev/null || return 1 ;;
            disabled) systemctl disable "$service" > /dev/null || return 1 ;;
            not-found)
                [[ $(systemctl show "$service" -p LoadState --value) == not-found ]] || { fail 'Previously absent service still exists.'; return 1; }
                continue ;;
        esac
        if [[ $active == active ]]; then
            systemctl start "$service" || return 1
            if [[ $service == "$UNIT" ]]; then
                health "$service" "$CONFIG" "$BINARY" || return 1
            else
                legacy_config=$(systemctl show "$service" -p ExecStart --value | helper legacy-exec) || return 1
                health "$service" "$legacy_config" /usr/bin/ss-server || return 1
            fi
        else
            [[ $(systemctl show "$service" -p ActiveState --value) == inactive ]] || { fail 'Service is not inactive after restore.'; return 1; }
        fi
        [[ $(systemctl is-enabled "$service" 2>/dev/null || true) == "$enabled" ]] || { fail 'Service enablement restoration failed.'; return 1; }
    done < "$WORK/restore-states.tsv"
}
