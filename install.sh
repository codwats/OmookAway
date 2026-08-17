#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "$0")" && pwd)

python -m pip install --user "$repo_dir"
install -Dm644 "$repo_dir/integrations/activity/shell.qml" \
  "$HOME/.local/share/omookaway/activity/shell.qml"
install -Dm644 "$repo_dir/integrations/omarchy-shell/BarWidget.qml" \
  "$HOME/.config/omarchy/plugins/omookaway.status/BarWidget.qml"
install -Dm644 "$repo_dir/integrations/omarchy-shell/manifest.json" \
  "$HOME/.config/omarchy/plugins/omookaway.status/manifest.json"
install -Dm644 "$repo_dir/systemd/omookaway.service" \
  "$HOME/.config/systemd/user/omookaway.service"
install -Dm644 "$repo_dir/systemd/omookaway-activity.service" \
  "$HOME/.config/systemd/user/omookaway-activity.service"

systemctl --user daemon-reload
systemctl --user enable --now omookaway.service omookaway-activity.service

echo "OmookAway installed. Add omookaway.status in Omarchy Bar Settings, then restart the Shell."
