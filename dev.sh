#!/usr/bin/env bash
# The dev servers, in the background: Django on 127.0.0.1:8010 and Vite on localhost:5180
# (which proxies /api to Django). Open http://localhost:5180 (from the laptop, VS Code
# forwards the port).
#
#   ./dev.sh start | stop | status | logs
#
# Both listen on this machine only. Never add --host to Vite: a dev server open to the
# internet runs whatever it's asked to.
# Django reads .env, so DATA_DIR points it at the dev database (data/dev), never the live one.
# Their logs and process ids are in $RUN, private to you.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
RUN=${XDG_RUNTIME_DIR:-/tmp}/projects-gateway-dev-$(id -u)
BACKEND_PORT=8010
FRONTEND_PORT=5180

die() { echo "dev: $*" >&2; exit 1; }
listening() { ss -ltn "sport = :$1" | grep -q LISTEN; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

# Each server in a session of its own, so stopping it stops its children too (Django's
# autoreloader, Vite's esbuild).
launch() {      # name, folder, command…
  local name=$1 dir=$2; shift 2
  (cd "$dir" && exec setsid "$@" >"$RUN/$name.log" 2>&1 < /dev/null) &
  echo $! > "$RUN/$name.pid"
}

wait_for() {    # name, port
  for _ in $(seq 40); do
    listening "$2" && return 0
    alive "$1" || break
    sleep 0.5
  done
  echo "dev: $1 didn't start. The end of its log ($RUN/$1.log):" >&2
  tail -n 20 "$RUN/$1.log" >&2
  return 1
}

halt() {        # name
  alive "$1" || { rm -f "$RUN/$1.pid"; return 0; }
  local pid; pid=$(cat "$RUN/$1.pid")
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null || true
  rm -f "$RUN/$1.pid"
  echo "dev: $1 stopped"
}

status() {
  for pair in "backend $BACKEND_PORT" "frontend $FRONTEND_PORT"; do
    set -- $pair
    if alive "$1"; then echo "$1: running (pid $(cat "$RUN/$1.pid")), port $2"
    elif listening "$2"; then echo "$1: not started by dev.sh, but something listens on port $2"
    else echo "$1: stopped"; fi
  done
}

case ${1:-} in
  start)
    mkdir -p -m 700 "$RUN"
    alive backend && alive frontend && { status; exit 0; }
    halt backend; halt frontend          # a half-started pair: start both again
    for port in $BACKEND_PORT $FRONTEND_PORT; do
      listening "$port" && die "port $port is taken by something else: see  ss -ltnp 'sport = :$port'"
    done
    [ -x venv/bin/python ] || die "no venv: python3 -m venv venv && venv/bin/pip install -r backend/requirements.txt"
    [ -d frontend/node_modules ] || die "no node_modules: (cd frontend && npm ci)"
    launch backend backend ../venv/bin/python manage.py runserver "127.0.0.1:$BACKEND_PORT"
    wait_for backend $BACKEND_PORT || { halt backend; exit 1; }
    launch frontend frontend npm run dev
    wait_for frontend $FRONTEND_PORT || { halt frontend; halt backend; exit 1; }
    echo "dev: running. Open http://localhost:$FRONTEND_PORT  (stop: dev.sh stop, logs: dev.sh logs)"
    ;;
  stop)
    halt frontend; halt backend
    ;;
  status)
    status
    ;;
  logs)
    exec tail -n 30 -F "$RUN/backend.log" "$RUN/frontend.log"
    ;;
  *)
    echo "usage: $0 start | stop | status | logs" >&2
    exit 2
    ;;
esac
