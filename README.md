# OmookAway

OmookAway counts aggregate active use and publishes a 30-minute Work Interval
to an Omarchy Shell widget. Idle transitions come from Quickshell's
`ext-idle-notify-v1` monitor; the integration never receives raw input or
application context. Screen-lock and suspend/resume transitions come from
systemd-logind and join Idle as one continuous away period. Away time at least
as long as a Break records a Satisfied Break and waits for active input before
starting a fresh Work Interval.

When a Warning expires, the daemon starts a separate Quickshell process for the
Break. Enforcement begins only after Quickshell reports a mapped overlay on
every current display with its Wayland exclusive-keyboard mode applied.
Quickshell exposes no separate compositor acknowledgement for that mode. The overlay reports its countdown and
offers one deliberate End Break control: before 20 percent it records an
Aborted Break, and at or after 20 percent it records a Satisfied Break. Natural
timer expiry is also Satisfied.

## Install from a checkout

```sh
./install.sh
```

Add `omookaway.status` to an Omarchy Shell bar section through Bar Settings,
then restart the Shell. The daemon owns timing and persisted lifecycle state;
restarting or disconnecting the widget cannot reset the Work Interval.

Inspect the same authoritative status used by the widget with:

```sh
omookaway status
```

During Work Hours, select the Shell widget or run `omookaway start-break` to
start a Manual Break immediately.

During a Warning, the widget shows the remaining Snooze Budget. Select it or
run `omookaway snooze` to postpone that Upcoming Break.

Pause an active Work Interval or Upcoming Break until a future ISO-8601 time
without consuming a Snooze:

```sh
omookaway pause 2026-08-17T14:30:00-07:00
```

The widget displays the Pause deadline. Right-click it to Pause for one hour,
or use the command above to choose an exact time. Resume early with
`omookaway resume`. When enforcement is unavailable, selecting the widget
retries the owed Break.

If aggregate activity observation cannot start or stops at runtime, Work
Interval progress becomes dormant and the Shell reports `Activity unavailable`.
OmookAway never substitutes wall time automatically. To deliberately continue
cadence by elapsed wall time during the current Work Hours Window, select the
Shell control or run:

```sh
omookaway degraded-wall-clock enter
```

Stop the fallback with `omookaway degraded-wall-clock leave`. Restoring the
activity observer also stops it automatically and waits for a fresh aggregate
activity sample. Existing Upcoming Breaks remain owed throughout.

## Configure Work Hours

Configuration updates are atomic. Each window stays within one day; adjacent
windows are allowed, but overlapping windows are rejected. Omitted days are
dormant:

```json
{
  "work_interval_seconds": 1800,
  "warning_seconds": 20,
  "break_seconds": 300,
  "idle_threshold_seconds": 300,
  "snooze_seconds": 300,
  "snooze_budget": 3,
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

After installing, verify the complete lifecycle in a real Omarchy session:

```sh
./smoke-test.sh
```

The guided smoke test checks a Warning, an enforced Break, fail-open release,
restart continuity, and coverage across every connected display. Normal
operation is entirely local and uses only aggregate activity, lock, and sleep
transitions; it does not inspect raw input, applications, or window titles.
