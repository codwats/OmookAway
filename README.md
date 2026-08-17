# OmookAway

OmookAway counts aggregate active use and publishes a 30-minute Work Interval
to an Omarchy Shell widget. Idle transitions come from Quickshell's
`ext-idle-notify-v1` monitor; the integration never receives raw input or
application context.

## Run from a checkout

```sh
python -m pip install --user .
mkdir -p ~/.local/share/omookaway/activity ~/.config/omarchy/plugins/omookaway.status
cp integrations/activity/shell.qml ~/.local/share/omookaway/activity/shell.qml
cp integrations/omarchy-shell/* ~/.config/omarchy/plugins/omookaway.status/
mkdir -p ~/.config/systemd/user
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now omookaway.service omookaway-activity.service
```

Add `omookaway.status` to an Omarchy Shell bar section through Bar Settings,
then restart the Shell. The daemon owns timing and persisted lifecycle state;
restarting or disconnecting the widget cannot reset the Work Interval.

Inspect the same authoritative status used by the widget with:

```sh
omookaway status
```

## Configure Work Hours

Configuration updates are atomic. Each window stays within one day; adjacent
windows are allowed, but overlapping windows are rejected. Omitted days are
dormant:

```json
{
  "work_interval_seconds": 1800,
  "warning_seconds": 20,
  "work_hours": {
    "monday": [["09:00", "12:00"], ["13:00", "17:00"]],
    "tuesday": [["09:00", "17:00"]]
  }
}
```

Apply the file through the daemon:

```sh
omookaway configure config.json
```

## Test

```sh
python -m unittest discover
```
