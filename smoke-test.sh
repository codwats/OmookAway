#!/usr/bin/env bash
set -euo pipefail

state_dir=${XDG_STATE_HOME:-$HOME/.local/state}/omookaway
state_file=$state_dir/engine.json
test_dir=$(mktemp -d)
had_state=false
daemon_was_active=false
observer_was_active=false

systemctl --user is-active --quiet omookaway.service && daemon_was_active=true
systemctl --user is-active --quiet omookaway-activity.service && observer_was_active=true

if [[ -f $state_file ]]; then
  cp "$state_file" "$test_dir/engine.json"
  had_state=true
fi

restore() {
  systemctl --user stop omookaway-activity.service omookaway.service || true
  if $had_state; then
    install -Dm600 "$test_dir/engine.json" "$state_file"
  else
    rm -f "$state_file"
  fi
  $daemon_was_active && systemctl --user start omookaway.service || true
  $observer_was_active && systemctl --user start omookaway-activity.service || true
  rm -rf "$test_dir"
}
trap restore EXIT

wait_for_state() {
  local expected=$1
  local attempts=50
  while ((attempts--)); do
    [[ $(omookaway status | jq -r .state) == "$expected" ]] && return
    sleep 0.2
  done
  echo "FAIL: did not reach $expected" >&2
  omookaway status >&2
  exit 1
}

cat >"$test_dir/config.json" <<'EOF'
{"work_interval_seconds":1,"warning_seconds":2,"break_seconds":30,"idle_threshold_seconds":300,"snooze_seconds":2,"snooze_budget":1}
EOF

$daemon_was_active || { echo "FAIL: omookaway.service is not active" >&2; exit 1; }
$observer_was_active || { echo "FAIL: omookaway-activity.service is not active" >&2; exit 1; }
command -v omarchy-restart-shell >/dev/null || {
  echo "FAIL: omarchy-restart-shell is unavailable" >&2
  exit 1
}
omookaway configure "$test_dir/config.json" >/dev/null
omookaway activity active >/dev/null

# Warning from active use.
wait_for_state warning

# An enforced Break is reported only after every Quickshell display is covered.
wait_for_state break
display_count=$(hyprctl monitors -j | jq length)
((display_count > 1)) || {
  echo "FAIL: multi-display verification requires at least two connected displays" >&2
  exit 1
}
echo "PASS: enforced Break with multi-display coverage contract ($display_count display(s))"

# Two overlay crashes reach stable Enforcement Unavailable; each crash must fail open.
for attempt in 1 2; do
  pkill -TERM -f 'qs --path .*/break_overlay.qml'
  if ((attempt == 1)); then wait_for_state break; fi
done
wait_for_state enforcement_unavailable
pgrep -f 'qs --path .*/break_overlay.qml' >/dev/null && {
  echo "FAIL: fail-open release left a Break overlay running" >&2
  exit 1
}
if hyprctl layers -j | jq -e '.. | objects | select(.namespace? == "omookaway-break")' >/dev/null; then
  echo "FAIL: fail-open release left an input-inhibiting Break surface" >&2
  exit 1
fi
echo "PASS: fail-open release"

# The daemon, activity observer, and Shell may restart without replacing state.
systemctl --user restart omookaway.service
wait_for_state enforcement_unavailable
[[ $(omookaway status | jq -r .upcoming_break) == true ]]
systemctl --user restart omookaway-activity.service
wait_for_state enforcement_unavailable
omarchy-restart-shell
wait_for_state enforcement_unavailable
echo "PASS: restart continuity"
echo "PASS: real-environment Warning, enforced Break, fail-open release, restart continuity, and multi-display smoke test"
