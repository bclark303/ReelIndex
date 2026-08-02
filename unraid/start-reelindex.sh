#!/usr/bin/env bash
set -Eeuo pipefail

PUID="${PUID:-99}"
PGID="${PGID:-100}"
UMASK_VALUE="${UMASK:-002}"

if ! [[ "$PUID" =~ ^[0-9]+$ ]] || ! [[ "$PGID" =~ ^[0-9]+$ ]]; then
    echo "PUID and PGID must be numeric." >&2
    exit 2
fi

umask "$UMASK_VALUE"
mkdir -p \
    /data/posters \
    /data/logs \
    /tmp/nginx/client_temp \
    /tmp/nginx/proxy_temp \
    /tmp/nginx/fastcgi_temp \
    /tmp/nginx/uwsgi_temp \
    /tmp/nginx/scgi_temp
chown -R "$PUID:$PGID" /data /tmp/nginx

cleanup() {
    local status=$?
    trap - TERM INT EXIT
    if [[ -n "${nginx_pid:-}" ]]; then kill -TERM "$nginx_pid" 2>/dev/null || true; fi
    if [[ -n "${backend_pid:-}" ]]; then kill -TERM "$backend_pid" 2>/dev/null || true; fi
    wait 2>/dev/null || true
    exit "$status"
}
trap cleanup TERM INT EXIT

gosu "$PUID:$PGID" uvicorn app.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

backend_ready=false
for _ in {1..60}; do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        backend_ready=true
        break
    fi
    if ! kill -0 "$backend_pid" 2>/dev/null; then
        echo "ReelIndex backend exited during startup." >&2
        wait "$backend_pid"
        exit $?
    fi
    sleep 1
done

if [[ "$backend_ready" != true ]]; then
    echo "ReelIndex backend did not become healthy within 60 seconds." >&2
    exit 1
fi

gosu "$PUID:$PGID" nginx -c /etc/nginx/nginx.conf -g 'daemon off;' &
nginx_pid=$!

set +e
wait -n "$backend_pid" "$nginx_pid"
status=$?
set -e
exit "$status"
