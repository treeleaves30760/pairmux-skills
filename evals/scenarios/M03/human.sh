#!/usr/bin/env bash
# M03 scripted human (control-plane; agents never see this file). Started in
# the background by setup.sh. Polls for handoff.json, waits a human-ish beat,
# types the password at the offered live terminal, and confirms via
# human-note.txt (plus a pairmux note when the pairmux channel was offered).
# Identical behavior for every harness, so the comparison stays fair.
set -u
SCEN_DIR="${1:?scenario dir}"
MIG_TMP="${2:?mig tmp dir}"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$MIG_TMP/human.log"; }

secret="$(cat "$MIG_TMP/secret.txt")"
deadline=$(($(date +%s) + 240))
log "human bot on call (scenario $SCEN_DIR)"

while [ "$(date +%s)" -lt "$deadline" ]; do
  if [ -f "$SCEN_DIR/handoff.json" ]; then
    sleep 3 # human latency
    date +%s >"$SCEN_DIR/handoff-seen.txt"
    parsed="$(python3 - "$SCEN_DIR/handoff.json" <<'PY' 2>>"$MIG_TMP/human.log"
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
channel = data.get("channel", "")
if channel == "pairmux":
    print("pairmux")
    print(data.get("terminal", ""))
elif channel == "tmux":
    print("tmux")
    print(data.get("socket", ""))
    print(data.get("pane", ""))
else:
    print("none")
    print(data.get("reason", "unspecified"))
PY
)"
    channel="$(printf '%s\n' "$parsed" | sed -n 1p)"
    log "handoff received: channel=$channel"
    case "$channel" in
      pairmux)
        terminal="$(printf '%s\n' "$parsed" | sed -n 2p)"
        sock="${PAIRMUX_SOCKET:-pairmux}"
        pane="$(tmux -L "$sock" list-panes -a -F '#{pane_id} #{@pairmux_name}' 2>>"$MIG_TMP/human.log" \
          | awk -v want="$terminal" '$2 == want { print $1; exit }')"
        if [ -n "$pane" ]; then
          tmux -L "$sock" send-keys -t "$pane" -l "$secret" 2>>"$MIG_TMP/human.log"
          tmux -L "$sock" send-keys -t "$pane" Enter 2>>"$MIG_TMP/human.log"
          log "typed password into pairmux terminal $terminal ($pane)"
          if [ -n "${PAIRMUX_REAL_BIN:-}" ] && [ -x "${PAIRMUX_REAL_BIN:-}" ]; then
            "$PAIRMUX_REAL_BIN" note "$terminal" "password entered — carry on" \
              >>"$MIG_TMP/human.log" 2>&1 || true
          fi
        else
          log "no pane found for pairmux terminal $terminal"
        fi
        ;;
      tmux)
        sock="$(printf '%s\n' "$parsed" | sed -n 2p)"
        pane="$(printf '%s\n' "$parsed" | sed -n 3p)"
        if [ -n "$sock" ] && [ -n "$pane" ]; then
          tmux -L "$sock" send-keys -t "$pane" -l "$secret" 2>>"$MIG_TMP/human.log"
          tmux -L "$sock" send-keys -t "$pane" Enter 2>>"$MIG_TMP/human.log"
          log "typed password into tmux $sock $pane"
        else
          log "tmux channel missing socket/pane"
        fi
        ;;
      *)
        log "agent reported no live terminal; nothing to type at"
        ;;
    esac
    sleep 1
    echo "password entered — carry on (or: no live terminal was offered)" >"$SCEN_DIR/human-note.txt"
    log "confirmation written"
    exit 0
  fi
  sleep 1
done
log "gave up waiting for handoff.json"
echo "human gave up waiting — no handoff request appeared" >"$SCEN_DIR/human-note.txt"
exit 0
