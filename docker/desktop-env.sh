#!/usr/bin/env sh

if [ "$(id -u)" = "1000" ] || [ "$(id -un 2>/dev/null)" = "vm" ]; then
  export DISPLAY="${DISPLAY:-:1}"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  export NO_AT_BRIDGE="${NO_AT_BRIDGE:-0}"
  export BROWSER="${BROWSER:-chrome}"
  export CDP_URL="${CDP_URL:-http://127.0.0.1:9222}"
fi
