#!/bin/sh
set -eu

current_uid="$(id -u)"

fail_permissions() {
    echo "ERROR: $1" >&2
    echo "Grant the mounted data to UID/GID 10001:10001 or run the image with its default entrypoint." >&2
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
    if ! run_as_app test -w /app/data; then
        fail_permissions "/app/data is not writable by UID $current_uid"
    fi

    readonly_path="$(run_as_app find /app/data ! -writable -print -quit 2>/dev/null || true)"
    if [ -n "$readonly_path" ]; then
        fail_permissions "$readonly_path is not writable by UID/GID 10001:10001"
    fi

    if ! run_as_app mkdir -p "$db_dir" || ! run_as_app test -w "$db_dir"; then
        fail_permissions "database directory $db_dir is not writable"
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
    if ! chown -R subly:subly /app/data; then
        fail_permissions "cannot repair ownership under /app/data"
    fi
fi

verify_writable_paths

if [ "$current_uid" = "0" ]; then
    exec gosu subly "$@"
fi

exec "$@"
