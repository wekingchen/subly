#!/bin/sh
set -eu

APP_UID=10001
APP_GID=10001
current_uid="$(id -u)"

fail_permissions() {
    echo "ERROR: $1" >&2
    echo "Run the image with its default entrypoint so /app/data can be repaired," >&2
    echo "or grant the data directory and database files to UID/GID ${APP_UID}:${APP_GID}." >&2
    exit 1
}

run_as_app() {
    if [ "$current_uid" = "0" ]; then
        gosu subly "$@"
    else
        "$@"
    fi
}

resolve_database_path() {
    db_path="${DB_PATH:-data/subly.db}"
    case "$db_path" in
        /*) db_file="$db_path" ;;
        *) db_file="/app/$db_path" ;;
    esac
    db_dir="$(dirname "$db_file")"
}

verify_writable_paths() {
    if ! run_as_app test -w /app/data || ! run_as_app test -x /app/data; then
        fail_permissions "/app/data is not writable/searchable by UID ${APP_UID}"
    fi

    readonly_path="$(run_as_app find /app/data ! -writable -print -quit)"
    if [ -n "$readonly_path" ]; then
        fail_permissions "$readonly_path is not writable by UID/GID ${APP_UID}:${APP_GID}"
    fi
    unsearchable_path="$(run_as_app find /app/data -type d ! -executable -print -quit)"
    if [ -n "$unsearchable_path" ]; then
        fail_permissions "$unsearchable_path is not searchable by UID/GID ${APP_UID}:${APP_GID}"
    fi

    if ! run_as_app mkdir -p "$db_dir" || ! run_as_app test -w "$db_dir" || ! run_as_app test -x "$db_dir"; then
        fail_permissions "database directory $db_dir is not writable/searchable"
    fi

    for path in "$db_file" "$db_file-wal" "$db_file-shm"; do
        if [ -e "$path" ] && ! run_as_app test -w "$path"; then
            fail_permissions "database file $path is not writable"
        fi
    done
}

resolve_database_path

if [ "$current_uid" = "0" ]; then
    mkdir -p /app/data
    # 只对与 /app/data 同一设备号的路径改 owner，不跨文件系统；
    # 同一文件系统上的嵌套 bind mount 无法仅凭设备号识别，Subly 部署不预期该布局。
    # 路径作为 argv 传入（不走换行分隔文本），对含空格/换行的文件名也安全。
    root_dev="$(find /app/data -maxdepth 0 -printf '%D')"
    if ! find /app/data -xdev -exec sh -c '
        root_dev="$1"
        shift
        for path in "$@"; do
            dev="$(find "$path" -maxdepth 0 -printf "%D")"
            [ "$dev" = "$root_dev" ] || continue
            chown -h subly:subly "$path" || exit 1
        done
    ' _ "$root_dev" {} +; then
        fail_permissions "cannot repair ownership under /app/data"
    fi
elif [ "$current_uid" != "$APP_UID" ]; then
    echo "ERROR: Subly must run as UID ${APP_UID} (got ${current_uid})." >&2
    echo "Use the default entrypoint or set user: \"${APP_UID}:${APP_GID}\"." >&2
    exit 1
fi

verify_writable_paths

if [ "$current_uid" = "0" ]; then
    exec gosu subly "$@"
fi

exec "$@"
