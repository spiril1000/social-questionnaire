#!/bin/sh
# Runs the app as PUID:PGID (default 1000:1000) instead of root. Bind-mounted volumes are often
# created by Docker as root, so first hand /config and /data to that user.
# If the container is already started as a non-root user (compose `user:`), it just runs.
set -e

if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"
    mkdir -p "$CONFIG_DIR" "$DATA_DIR"
    chown -R "$PUID:$PGID" "$CONFIG_DIR" "$DATA_DIR"
    exec su-exec "$PUID:$PGID" "$@"
fi

exec "$@"
