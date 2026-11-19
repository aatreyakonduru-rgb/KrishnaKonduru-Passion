#!/usr/bin/env bash
# Supervised launcher for Argus (the /workbench page). Team values: .devin/rules/sdlc-profile.json.
#   run.sh start [port] [--user <id>]    detach, restart the server whenever it exits, log to ~/.sdlc/console/server.log
#   run.sh restart [port] [--user <id>]  stop, then start (use when the person or port changes)
#   run.sh stop                          stop supervisor and server
#   run.sh status                        show pid / port / last log lines
# --user is who is using the page (Jira username, e-mail or Devin user id on people.yaml);
# without it SDLC_CONSOLE_JIRA_USER is used, and without that the page asks.
# Reaches Devin through the host Devin Cloud session (bridge, the default). On a PC, set SDLC_DEVIN_TRANSPORT=api
# and give it a Devin API key: DEVIN_API_KEY, or the one saved on the page. The Jira token (jira.token_env in sdlc-profile.json) is optional;
# without it the ticket lists are read through Devin Cloud.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# A working Python 3, also on Windows where python3 is often only the Store alias in WindowsApps.
# Kept here so the Workbench runs from any repo. SDLC_PYTHON overrides the choice.
sdlc_python() {
  local py
  if [ -n "${SDLC_PYTHON:-}" ]; then "$SDLC_PYTHON" "$@"; return; fi
  for py in python3 python; do
    case "$(command -v "$py" 2>/dev/null)" in
      "" | *WindowsApps*) ;;
      *) "$py" "$@"; return ;;
    esac
  done
  if command -v py >/dev/null 2>&1; then py -3 "$@"; return; fi
  printf 'no Python 3 on PATH (tried python3, python, py); set SDLC_PYTHON\n' >&2
  return 127
}
HOME_DIR="${SDLC_CONSOLE_HOME:-$HOME/.sdlc/console}"
mkdir -p "$HOME_DIR"
PIDFILE="$HOME_DIR/supervisor.pid"
LOG="$HOME_DIR/server.log"
CMD="${1:-start}"
[ $# -gt 0 ] && shift
PORT="${SDLC_CONSOLE_PORT:-8787}"
VIEWER="${SDLC_CONSOLE_JIRA_USER:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) VIEWER="${2:-}"; shift 2 || shift ;;
    --user=*) VIEWER="${1#--user=}"; shift ;;
    *) PORT="$1"; shift ;;
  esac
done

supervise() {
  while true; do
    echo "[$(date -u +%FT%TZ)] starting server on :$PORT${VIEWER:+ as $VIEWER}" >>"$LOG"
    sdlc_python "$HERE/server.py" --port "$PORT" ${VIEWER:+--user "$VIEWER"} >>"$LOG" 2>&1
    echo "[$(date -u +%FT%TZ)] server exited ($?), restarting in 3s" >>"$LOG"
    sleep 3
  done
}

stop_all() {
  [ -f "$PIDFILE" ] && { pkill -TERM -s "$(cat "$PIDFILE")" 2>/dev/null; rm -f "$PIDFILE"; }
  pkill -f "$HERE/server.py" 2>/dev/null
  echo stopped
}

start_all() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "already running (supervisor pid $(cat "$PIDFILE")); use restart to change port or --user"; exit 0
  fi
      setsid nohup env HERE="$HERE" PORT="$PORT" LOG="$LOG" VIEWER="$VIEWER" \
    bash -c "$(declare -f sdlc_python supervise); supervise" >/dev/null 2>&1 &
  echo $! >"$PIDFILE"
  sleep 2
  TITLE="$(sdlc_python "$HERE/sdlc_profile.py" workbench_title 2>/dev/null || echo "Argus")"
  echo "$TITLE on http://127.0.0.1:$PORT${VIEWER:+ as $VIEWER}  (log: $LOG)"
}

case "$CMD" in
  start) start_all ;;
  restart) stop_all; sleep 1; start_all ;;
  stop) stop_all ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "supervisor pid $(cat "$PIDFILE")"; else echo "not running"; fi
    pgrep -af "$HERE/server.py" || true
    tail -n 5 "$LOG" 2>/dev/null
    ;;
  *) echo "usage: run.sh start|restart|stop|status [port] [--user <id>]"; exit 1 ;;
esac
