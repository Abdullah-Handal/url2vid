#!/usr/bin/env bash
#
# One-tap launcher for the url2vid web UI.
#
# Sets up whatever is missing (virtualenv, Python packages, node modules, the
# built frontend), starts the server, and opens a browser at it. Safe to run
# repeatedly: everything already in place is skipped, so the second run is
# just a start.

set -Eeuo pipefail

# Run from the project regardless of where the launcher was invoked from --
# double-clicking in a file manager rarely sets the working directory.
cd "$(dirname "$(readlink -f "$0")")"

PORT="${PORT:-8000}"
VENV=".venv"
PY="$VENV/bin/python"

bold=$'\e[1m'; dim=$'\e[2m'; red=$'\e[31m'; green=$'\e[32m'; cyan=$'\e[36m'; off=$'\e[0m'
say()  { printf '%s\n' "${cyan}▸${off} $*"; }
ok()   { printf '%s\n' "${green}✓${off} $*"; }
warn() { printf '%s\n' "${red}✗${off} $*" >&2; }

# A launcher opened by double-click closes the moment it exits, taking the
# error with it. Hold the window open so the message can actually be read.
on_error() {
  warn "Startup failed on line $1."
  if [ -t 0 ]; then
    printf '%s' "${dim}Press Enter to close…${off}"
    read -r _
  fi
}
trap 'on_error $LINENO' ERR

need() {
  command -v "$1" >/dev/null 2>&1 || {
    warn "$1 is not installed. $2"
    exit 1
  }
}

say "${bold}url2vid${off} — starting up"

# nvm, fnm and volta install node under the user's home and only put it on
# PATH from ~/.bashrc, which an interactive terminal reads and a double-clicked
# launcher does not. Go looking for it before claiming it is missing, or this
# script tells people to install software they already have.
ensure_node() {
  have_node && return 0

  local nvm_dir="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$nvm_dir/nvm.sh" ]; then
    # nvm.sh is not written for `set -eu`, and its exit status is not ours.
    set +eu
    # shellcheck source=/dev/null
    . "$nvm_dir/nvm.sh" >/dev/null 2>&1 || true
    set -eu
    have_node && return 0
  fi

  # No nvm script, or it selected nothing: take the newest version on disk.
  local newest
  newest="$(find "$nvm_dir/versions/node" -maxdepth 2 -type d -name bin 2>/dev/null | sort -V | tail -1)"
  [ -n "$newest" ] && PATH="$newest:$PATH"

  local dir
  for dir in "$HOME/.volta/bin" "$HOME/.local/share/fnm/aliases/default/bin" \
             "$HOME/.asdf/shims" /snap/bin /usr/local/bin; do
    [ -x "$dir/node" ] && PATH="$dir:$PATH"
  done
  export PATH

  have_node
}

have_node() { command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; }

need python3 "Install it with: sudo apt install python3 python3-venv"

if ! ensure_node; then
  warn "Node.js is not installed, or not where this script can see it."
  warn "Install it with: sudo apt install nodejs npm"
  warn "Already have it through nvm? Run this from a terminal instead, or run:"
  warn "  ${dim}source ~/.nvm/nvm.sh && ./start-web.sh${off}"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg is missing — video and audio cannot be merged into one file."
  warn "Install it with: sudo apt install ffmpeg"
fi

# Already running? Just point the browser at it instead of failing on a
# port clash.
if curl -fsS -m 2 "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1; then
  ok "Already running on port $PORT — opening it."
  xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
  exit 0
fi

if [ ! -x "$PY" ]; then
  say "Creating the Python environment (first run only)…"
  python3 -m venv "$VENV"
fi

# Cheap presence check rather than a pip install on every launch.
if ! "$PY" -c 'import fastapi, uvicorn, yt_dlp' >/dev/null 2>&1; then
  say "Installing Python packages (first run only)…"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
fi

if [ ! -d web/node_modules ]; then
  say "Installing frontend packages (first run only)…"
  ( cd web && npm install --silent )
fi

# Rebuild when any source file is newer than the built bundle, so edits are
# picked up without having to remember to build.
needs_build=0
if [ ! -f web/dist/index.html ]; then
  needs_build=1
elif [ -n "$(find web/src web/index.html web/vite.config.ts -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
  needs_build=1
fi

if [ "$needs_build" -eq 1 ]; then
  say "Building the page…"
  ( cd web && npm run build --silent )
fi

say "Starting the server on port $PORT…"
"$PY" run_web.py --port "$PORT" &
server=$!

# Stop the server when this window is closed or Ctrl+C is pressed, rather
# than orphaning it to hold the port against the next launch.
cleanup() { kill "$server" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -fsS -m 1 "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1; then
    ok "Ready at ${bold}http://127.0.0.1:$PORT${off}"
    xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
    break
  fi
  # The server dying during startup should not cost a 30-second wait.
  kill -0 "$server" 2>/dev/null || { warn "The server stopped while starting."; exit 1; }
  sleep 0.5
done

printf '%s\n' "${dim}Press Ctrl+C to stop.${off}"
wait "$server"
