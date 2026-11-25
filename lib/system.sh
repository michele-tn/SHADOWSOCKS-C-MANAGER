#!/usr/bin/env bash
detect_system() {
    if [[ -r /etc/os-release ]]; then
        sed -n 's/^PRETTY_NAME="\(.*\)"$/\1/p' /etc/os-release
    else
        uname -s
    fi
}

preflight() {
    [[ $EUID == 0 ]] || fail 'Administrative operations require root on the Ubuntu target.'
    [[ $(uname -s) == Linux ]] || fail 'Administration requires Linux; Windows is inspection-only.'
    grep -qx 'ID=ubuntu' /etc/os-release || fail 'Only Ubuntu is supported.'
    grep -qx 'VERSION_ID="22.04"' /etc/os-release || fail 'Only Ubuntu 22.04 is supported.'
    grep -q '^DISTRIB_DESCRIPTION="Ubuntu 22.04.5 LTS"$' /etc/lsb-release || fail 'Ubuntu 22.04.5 LTS is required.'
    [[ $(uname -m) == x86_64 || $(uname -m) == aarch64 ]] || fail 'Only x86_64 and aarch64 are reviewed.'
    [[ -d /run/systemd/system ]] || fail 'A running systemd system instance is required.'
    local command
    for command in systemctl systemd-analyze ss flock sha256sum find stat timeout; do
        command -v "$command" >/dev/null || fail "Required system command missing: $command"
    done
    (( $(df -Pk /var | awk 'END {print $4}') >= 2097152 )) || fail 'At least 2 GiB free space is required in /var.'
    [[ ! -d /etc/systemd/system/$UNIT.d ]] || fail 'Replacement service drop-ins are unsupported.'
}

dependencies() {
    PHASE='dependency preparation'
    local package status
    local -a missing=()
    for package in build-essential cmake git ca-certificates; do
        status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) || status=missing
        [[ $status == 'install ok installed' ]] || missing+=("$package")
    done
    if (( ${#missing[@]} )); then
        printf 'Missing build packages: %s\n' "${missing[*]}"
        confirm DEPENDENCIES
        apt-get update > "$WORK/apt.log" 2>&1
        apt-get install --no-install-recommends --no-upgrade -y "${missing[@]}" >> "$WORK/apt.log" 2>&1
    fi
    event INFO 'Build dependencies available; no package upgrade was requested.'
}

discover_legacy() {
    PHASE='legacy discovery and compatibility'
    local row execstart dropins environment fragment candidate property value process_count
    local -a units=() configs=()
    while IFS= read -r row; do
        candidate=${row%% *}
        [[ $candidate == shadowsocks-libev.service || $candidate == shadowsocks-libev-server@*.service ]] || continue
        [[ $candidate == *@.service ]] || units+=("$candidate")
    done < <(systemctl list-units --all --type=service --plain --no-legend 'shadowsocks-libev*')
    (( ${#units[@]} == 1 )) || fail 'Migration requires exactly one discovered legacy server unit.'
    LEGACY=${units[0]}
    [[ $LEGACY =~ ^shadowsocks-libev(-server@[A-Za-z0-9_-]+)?\.service$ ]] || fail 'Unsupported legacy service name.'
    [[ $(systemctl show "$LEGACY" -p ActiveState --value) == active ]] || fail 'Legacy service must be active before migration.'
    dropins=$(systemctl show "$LEGACY" -p DropInPaths --value)
    [[ -z $dropins ]] || fail 'Legacy drop-ins require manual review; no changes made.'
    environment=$(systemctl show "$LEGACY" -p EnvironmentFiles --value)
    [[ -z $environment ]] || fail 'Legacy EnvironmentFiles require manual review; use an explicit instance unit.'
    [[ $(systemctl show "$LEGACY" -p Type --value) == simple ]] || fail 'Only simple foreground legacy services are supported.'
    for property in Environment ExecStartPre ExecStartPost ExecStop ExecStopPost RootDirectory RootImage; do
        value=$(systemctl show "$LEGACY" -p "$property" --value)
        [[ -z $value ]] || fail 'Legacy environment, hooks or filesystem isolation require manual review.'
    done
    process_count=$(pgrep -xc ss-server) || [[ $process_count == 0 ]]
    [[ $process_count == 1 ]] || fail 'Exactly one running ss-server process is required for migration.'
    execstart=$(systemctl show "$LEGACY" -p ExecStart --value)
    SOURCE=$(printf '%s' "$execstart" | helper legacy-exec)
    while IFS= read -r -d '' candidate; do configs+=("$candidate"); done < <(
        find /etc/shadowsocks-libev -maxdepth 1 -name '*.json' -print0)
    (( ${#configs[@]} == 1 )) && [[ ${configs[0]} == "$SOURCE" ]] || fail 'Multiple or mismatched legacy configuration files require manual review.'
    helper validate "$SOURCE"
    fragment=$(systemctl show "$LEGACY" -p FragmentPath --value)
    fragment=$(readlink -f "$fragment")
    EVIDENCE=("$SOURCE" "$fragment")
    event INFO 'One active, explicit legacy server configuration detected.'
}

assert_fresh() {
    PHASE='fresh installation preflight'
    local path units
    for path in "$BINARY" "$CONFIG" "$UNIT_FILE" /opt/shadowsocks-c/provenance.json; do
        [[ ! -e $path && ! -L $path ]] || fail 'A managed installation already exists; back it up and review before proceeding.'
    done
    [[ ! -e /opt/shadowsocks-c && ! -e /etc/shadowsocks-c ]] || fail 'Existing destination directories will not be overwritten.'
    units=$(systemctl list-units --all --plain --no-legend 'shadowsocks*')
    if [[ -n $units ]]; then
        fail 'Existing Shadowsocks services detected. Use migration or review them manually.'
    fi
    ! command -v ss-server >/dev/null || fail 'An existing ss-server executable was detected.'
    [[ ! -d /etc/shadowsocks-libev ]] || fail 'Existing legacy configuration directory detected.'
}

port_free() {
    local port=$1
    [[ -z $(ss -H -lnt "sport = :$port") && -z $(ss -H -lnu "sport = :$port") ]] || fail 'Selected TCP or UDP port is occupied.'
}

build_upstream() {
    PHASE='upstream build and test'
    printf 'Audited development snapshot: %s\nThis is not the published v3.3.6 release.\n' "$COMMIT"
    confirm SNAPSHOT
    dependencies
    PHASE='upstream build and test'
    event INFO '[build] Fetching the immutable audited upstream revision.'
    mkdir "$WORK/source"
    git -C "$WORK/source" init -q
    git -C "$WORK/source" -c core.hooksPath=/dev/null fetch -q --depth 1 "$REPOSITORY" "$COMMIT" > "$WORK/build.log" 2>&1
    git -C "$WORK/source" -c core.hooksPath=/dev/null checkout -q --detach FETCH_HEAD >> "$WORK/build.log" 2>&1
    [[ $(git -C "$WORK/source" rev-parse HEAD) == "$COMMIT" ]] || fail 'Upstream commit mismatch.'
    event INFO '[build] Source commit verified. Configuring bundled dependencies.'
    cmake -S "$WORK/source" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release \
        -DSS_DEPENDENCY_MODE=bundled -DWITH_STATIC=ON -DSS_BUILD_SHARED_LIBRARY=OFF >> "$WORK/build.log" 2>&1
    cmake --build "$WORK/build" --parallel 2 >> "$WORK/build.log" 2>&1
    [[ -x $WORK/build/bin/ss-server ]] || fail 'Build did not produce bin/ss-server.'
    ctest --test-dir "$WORK/build" --output-on-failure -L 'unit|vendor' >> "$WORK/build.log" 2>&1
    cmake --install "$WORK/build" --prefix "$WORK/stage" >> "$WORK/build.log" 2>&1
    tar -cf "$WORK/licenses.tar" -C "$WORK/stage/share/licenses" shadowsocks-c \
        -C "$WORK/source" COPYING third_party/manifest.json
    "$WORK/build/bin/ss-server" --version > "$WORK/version.txt" 2>&1
    event INFO '[build] Build, upstream tests and executable version invocation completed.'
    cp -- "$WORK/build.log" "$STATE/last-build.log"
}
