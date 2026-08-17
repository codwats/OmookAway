from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
ALL_WEEK = tuple(((0, 24 * 60),) for _ in DAY_NAMES)


def _minute(value: str, *, end: bool = False) -> int:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Work Hours times must use HH:MM") from None
    if minute not in range(60) or hour not in range(24) and not (
        end and hour == 24 and minute == 0
    ):
        raise ValueError("invalid Work Hours time")
    return hour * 60 + minute


def _work_hours(value: Any) -> tuple[tuple[tuple[int, int], ...], ...]:
    if value is None:
        return ALL_WEEK
    if isinstance(value, (list, tuple)):
        days = value
    elif isinstance(value, dict):
        unknown = set(value) - set(DAY_NAMES)
        if unknown:
            raise ValueError(f"invalid Work Hours day: {min(unknown)}")
        days = [value.get(day, ()) for day in DAY_NAMES]
    else:
        raise ValueError("work_hours must be a weekly schedule")

    if len(days) != 7:
        raise ValueError("work_hours must contain seven days")
    result = []
    for windows in days:
        normalized = []
        for window in windows:
            if len(window) != 2:
                raise ValueError("Work Hours windows need a start and end")
            start = _minute(window[0]) if isinstance(window[0], str) else int(window[0])
            end = _minute(window[1], end=True) if isinstance(window[1], str) else int(window[1])
            if not 0 <= start < end <= 24 * 60:
                raise ValueError("Work Hours windows must stay within one day")
            normalized.append((start, end))
        normalized.sort()
        if any(left[1] > right[0] for left, right in zip(normalized, normalized[1:])):
            raise ValueError("Work Hours windows must not overlap")
        result.append(tuple(normalized))
    return tuple(result)


@dataclass(frozen=True)
class Config:
    work_interval_seconds: int = 30 * 60
    warning_seconds: int = 20
    break_seconds: int = 5 * 60
    idle_threshold_seconds: int = 5 * 60
    snooze_seconds: int = 5 * 60
    snooze_budget: int = 3
    work_hours: Any = None

    def __post_init__(self) -> None:
        for name in (
            "work_interval_seconds",
            "warning_seconds",
            "break_seconds",
            "idle_threshold_seconds",
            "snooze_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if (
            not isinstance(self.snooze_budget, int)
            or isinstance(self.snooze_budget, bool)
            or self.snooze_budget < 0
        ):
            raise ValueError("snooze_budget must be non-negative")
        object.__setattr__(self, "work_hours", _work_hours(self.work_hours))


class Engine:
    """Public deterministic seam shared by production adapters and tests."""

    STATES = {
        "dormant",
        "idle",
        "work_interval",
        "warning",
        "snooze",
        "pause",
        "starting_break",
        "break",
        "enforcement_unavailable",
    }
    UPCOMING_BREAK_STATES = {
        "warning",
        "snooze",
        "starting_break",
        "break",
        "enforcement_unavailable",
    }

    def __init__(self, config: Config, now: float, civil_now: datetime | None = None) -> None:
        self.config = config
        self.window = self._window_at(civil_now or datetime.now().astimezone())
        self.state = "idle" if self.window is not None else "dormant"
        self.active = False
        self.input_active = False
        self.active_elapsed = 0.0
        self.away_sources: set[str] = set()
        self.away_started_at: float | None = None
        self.away_started_civil: datetime | None = None
        self.away_satisfied = False
        self.last_at = now
        self.warning_deadline: float | None = None
        self.snooze_deadline: float | None = None
        self.pause_deadline: datetime | None = None
        self.paused_upcoming_break = False
        self.snoozes_remaining: int | None = None
        self.upcoming_break_snooze_seconds: int | None = None
        self.break_started_at: float | None = None
        self.break_deadline: float | None = None
        self.requested_effects: list[dict[str, Any]] = []
        self.last_break_outcome: str | None = None
        self.today_satisfied_breaks = 0
        self.today_aborted_breaks = 0
        self.count_date = (civil_now or datetime.now().astimezone()).date().isoformat()
        self.enforcement_error: str | None = None
        self.consecutive_enforcement_failures = 0
        self.activity_observation_available = False
        self.degraded_wall_clock_mode = False
        self.state_error: str | None = None

    def apply(
        self, event: dict[str, Any], now: float, civil_now: datetime | None = None
    ) -> dict[str, Any]:
        civil_now = civil_now or datetime.now().astimezone()
        self.requested_effects = []
        self._reconcile_count_date(civil_now)
        new_config = None
        if event.get("type") == "configure":
            values = asdict(self.config)
            values.update(event["config"])
            new_config = Config(**values)
        if self._reconcile_window(civil_now):
            self.last_at = now
        else:
            self._advance(now)
        if (
            self.state == "pause"
            and self.pause_deadline is not None
            and civil_now >= self.pause_deadline
        ):
            self._resume(now)
        if new_config is not None:
            old_warning_seconds = self.config.warning_seconds
            self.config = new_config
            changed_window = self._reconcile_window(civil_now)
            if not changed_window and self.state == "warning" and (
                self.config.warning_seconds != old_warning_seconds
            ):
                self.warning_deadline = now + self.config.warning_seconds
            elif (
                not changed_window
                and self.state == "work_interval"
                and self.active_elapsed >= self.config.work_interval_seconds
            ):
                self.active_elapsed = 0.0
        elif event.get("type") == "activity_observation":
            available = event.get("available") is True
            self.activity_observation_available = available
            if available:
                self.degraded_wall_clock_mode = False
            self.input_active = False
            self.active = False
            if self.window is not None and self.state not in self.UPCOMING_BREAK_STATES:
                self.state = "idle"
            self.last_at = now
        elif event.get("type") == "enter_degraded_wall_clock_mode":
            if (
                self.activity_observation_available
                or self.window is None
                or self.state not in {"idle", "work_interval", "warning", "snooze"}
            ):
                raise ValueError("Degraded Wall-Clock Mode is not available")
            self.degraded_wall_clock_mode = True
            if self.state not in self.UPCOMING_BREAK_STATES and self.state != "pause":
                self.state = "work_interval"
            self.last_at = now
        elif event.get("type") == "leave_degraded_wall_clock_mode":
            if not self.degraded_wall_clock_mode:
                raise ValueError("Degraded Wall-Clock Mode is not active")
            self.degraded_wall_clock_mode = False
            if self.state not in self.UPCOMING_BREAK_STATES and self.state != "pause":
                self.state = "idle"
            self.last_at = now
        elif event.get("type") == "activity":
            self.activity_observation_available = True
            self.degraded_wall_clock_mode = False
            observed_active = event.get("active") is True
            self.input_active = observed_active
            if observed_active:
                self.away_sources.discard("idle")
            else:
                self.away_sources.add("idle")
            self.active = self.input_active and not self.away_sources
            if self.active:
                self.away_started_at = None
                self.away_started_civil = None
                self.away_satisfied = False
            else:
                self._begin_away(now, civil_now)
            if self.window is None:
                self.state = "dormant"
            elif self.state == "pause":
                pass
            elif self.state not in self.UPCOMING_BREAK_STATES:
                self.state = "work_interval" if self.active else "idle"
        elif event.get("type") in {"lock", "suspend"}:
            source = event["type"]
            away = event.get("locked" if source == "lock" else "suspended") is True
            if away:
                self.away_sources.add(source)
                self.active = False
                self._begin_away(now, civil_now)
            else:
                self.away_sources.discard(source)
                self.active = self.input_active and not self.away_sources
            if (
                self.window is not None
                and self.state != "pause"
                and self.state not in self.UPCOMING_BREAK_STATES
            ):
                self.state = "work_interval" if self.active else "idle"
        elif event.get("type") == "overlay_ready":
            if self.state not in {"starting_break", "break"}:
                raise ValueError("no Break is awaiting overlay readiness")
            displays = set(event.get("display_ids", ()))
            covered = set(event.get("covered_display_ids", ()))
            if displays and displays == covered and event.get("input_inhibited") is True:
                if self.state == "starting_break":
                    self.state = "break"
                    self.break_started_at = now
                    self.break_deadline = now + self.config.break_seconds
                self.consecutive_enforcement_failures = 0
                self.enforcement_error = None
            else:
                self._fail_enforcement(
                    "complete display coverage and input inhibition were not established", now
                )
        elif event.get("type") == "overlay_failed":
            if self.state not in {"starting_break", "break"}:
                raise ValueError("no Break overlay is active")
            self._fail_enforcement(str(event.get("error") or "Break overlay failed"), now)
        elif event.get("type") == "retry_enforcement":
            if self.state != "enforcement_unavailable":
                raise ValueError("enforcement retry is not available")
            self.state = "starting_break"
            self.enforcement_error = None
            self.requested_effects.append({"type": "launch_break"})
        elif event.get("type") == "snooze":
            if self.state != "warning" or not self.snoozes_remaining:
                raise ValueError("Snooze is not available")
            self.snoozes_remaining -= 1
            self.state = "snooze"
            assert self.upcoming_break_snooze_seconds is not None
            self.warning_deadline = None
            self.snooze_deadline = now + self.upcoming_break_snooze_seconds
        elif event.get("type") == "pause":
            try:
                resume_at = datetime.fromisoformat(event["resume_at"])
                if civil_now.tzinfo is not None and resume_at.tzinfo is None:
                    resume_at = resume_at.replace(tzinfo=civil_now.tzinfo)
                elif civil_now.tzinfo is None and resume_at.tzinfo is not None:
                    resume_at = resume_at.replace(tzinfo=None)
            except (KeyError, TypeError, ValueError):
                raise ValueError("Pause requires a valid future resume time") from None
            if resume_at <= civil_now:
                raise ValueError("Pause requires a valid future resume time")
            if self.state not in {"work_interval", "warning", "snooze"}:
                raise ValueError("Pause is not available")
            self.paused_upcoming_break = self.state in {"warning", "snooze"}
            self.state = "pause"
            self.pause_deadline = resume_at
            self.warning_deadline = None
            self.snooze_deadline = None
        elif event.get("type") == "resume":
            if self.state != "pause":
                raise ValueError("Resume is not available")
            self._resume(now)
        elif event.get("type") == "start_manual_break":
            if self.state not in {"idle", "work_interval"}:
                raise ValueError("Manual Break is not available")
            self.state = "starting_break"
            self.requested_effects.append({"type": "launch_break"})
        elif event.get("type") == "finish_break":
            if self.state != "break":
                raise ValueError("no Break is active")
            assert self.break_started_at is not None
            satisfied = now - self.break_started_at >= self.config.break_seconds * 0.2
            self._finish_break("satisfied" if satisfied else "aborted")
        elif event.get("type") != "time":
            raise ValueError("unsupported engine event")
        return self.status(now, civil_now)

    def _advance(self, now: float) -> None:
        if now < self.last_at:
            raise ValueError("monotonic time moved backwards")
        advancing_work_interval = (
            self.activity_observation_available and self.active
        ) or self.degraded_wall_clock_mode and not self.away_sources
        if advancing_work_interval and self.state == "work_interval":
            due_in = self.config.work_interval_seconds - self.active_elapsed
            elapsed = now - self.last_at
            if elapsed >= due_in:
                self.active_elapsed = float(self.config.work_interval_seconds)
                self.state = "warning"
                self.snoozes_remaining = self.config.snooze_budget
                self.upcoming_break_snooze_seconds = self.config.snooze_seconds
                self.warning_deadline = self.last_at + due_in + self.config.warning_seconds
            else:
                self.active_elapsed += elapsed
        if (
            self.away_started_at is not None
            and not self.away_satisfied
            and now - self.away_started_at >= self.config.break_seconds
            and (
                self.state in {"idle", "pause"}
                or self.state in self.UPCOMING_BREAK_STATES
            )
        ):
            release_break = self.state in {"starting_break", "break"}
            self.away_satisfied = True
            self.active_elapsed = 0.0
            self.last_break_outcome = "satisfied"
            self.today_satisfied_breaks += 1
            self.warning_deadline = None
            self.snooze_deadline = None
            self.pause_deadline = None
            self.paused_upcoming_break = False
            self.snoozes_remaining = None
            self.upcoming_break_snooze_seconds = None
            self.break_started_at = None
            self.break_deadline = None
            self.enforcement_error = None
            self.state = "idle"
            if release_break:
                self.requested_effects.append({"type": "release_break"})
        if self.state == "warning" and self.warning_deadline is not None:
            if now >= self.warning_deadline:
                self.state = "starting_break"
                self.warning_deadline = None
                self.requested_effects.append({"type": "launch_break"})
        elif self.state == "snooze" and self.snooze_deadline is not None:
            if now >= self.snooze_deadline:
                warning_deadline = self.snooze_deadline + self.config.warning_seconds
                self.snooze_deadline = None
                if now >= warning_deadline:
                    self.state = "starting_break"
                    self.requested_effects.append({"type": "launch_break"})
                else:
                    self.state = "warning"
                    self.warning_deadline = warning_deadline
        elif self.state == "break" and self.break_deadline is not None:
            if now >= self.break_deadline:
                self._finish_break("satisfied")
        self.last_at = now

    def _begin_away(self, now: float, civil_now: datetime) -> None:
        if self.away_started_at is None:
            self.input_active = False
            self.away_started_at = now
            self.away_started_civil = civil_now

    def _resume(self, now: float) -> None:
        if self.paused_upcoming_break:
            self.state = "warning"
            self.warning_deadline = now + self.config.warning_seconds
        else:
            self.state = "work_interval" if self.active else "idle"
        self.pause_deadline = None
        self.paused_upcoming_break = False
        self.last_at = now

    def _finish_break(self, outcome: str) -> None:
        self.last_break_outcome = outcome
        if outcome == "satisfied":
            self.today_satisfied_breaks += 1
        else:
            self.today_aborted_breaks += 1
        self.active_elapsed = 0.0
        self.warning_deadline = None
        self.snooze_deadline = None
        self.pause_deadline = None
        self.paused_upcoming_break = False
        self.snoozes_remaining = None
        self.upcoming_break_snooze_seconds = None
        self.break_started_at = None
        self.break_deadline = None
        self.enforcement_error = None
        self.state = "work_interval" if self.active else "idle"
        self.requested_effects.append({"type": "release_break"})

    def _fail_enforcement(self, error: str, now: float) -> None:
        self.consecutive_enforcement_failures += 1
        self.state = (
            "warning" if self.consecutive_enforcement_failures == 1
            else "enforcement_unavailable"
        )
        self.warning_deadline = now if self.state == "warning" else None
        self.break_started_at = None
        self.break_deadline = None
        self.enforcement_error = error
        self.requested_effects.append({"type": "release_break"})

    def _reconcile_count_date(self, civil_now: datetime) -> None:
        today = civil_now.date().isoformat()
        if today != self.count_date:
            self.count_date = today
            self.today_satisfied_breaks = 0
            self.today_aborted_breaks = 0

    def _window_at(self, civil_now: datetime) -> tuple[str, int, int] | None:
        minute = civil_now.hour * 60 + civil_now.minute
        for start, end in self.config.work_hours[civil_now.weekday()]:
            if start <= minute < end:
                return civil_now.date().isoformat(), start, end
        return None

    def _reconcile_window(self, civil_now: datetime) -> bool:
        window = self._window_at(civil_now)
        if window == self.window:
            return False
        self.window = window
        self.active = False
        self.input_active = False
        self.active_elapsed = 0.0
        self.away_started_at = None
        self.away_started_civil = None
        self.away_satisfied = False
        self.warning_deadline = None
        self.snooze_deadline = None
        self.pause_deadline = None
        self.paused_upcoming_break = False
        self.snoozes_remaining = None
        self.upcoming_break_snooze_seconds = None
        self.break_started_at = None
        self.break_deadline = None
        self.enforcement_error = None
        self.consecutive_enforcement_failures = 0
        self.degraded_wall_clock_mode = False
        if window is None:
            self.state = "dormant"
        else:
            self.state = "idle"
        return True

    def status(self, now: float, civil_now: datetime | None = None) -> dict[str, Any]:
        civil_now = civil_now or datetime.now().astimezone()
        self._reconcile_count_date(civil_now)
        if self._reconcile_window(civil_now):
            self.last_at = now
        elif (
            self.state == "pause"
            and self.pause_deadline is not None
            and civil_now >= self.pause_deadline
        ):
            self._resume(now)
        elapsed = min(self.active_elapsed, self.config.work_interval_seconds)
        reported_state = self.state
        if (
            self.window is not None
            and not self.activity_observation_available
            and not self.degraded_wall_clock_mode
            and self.state in {"idle", "work_interval"}
        ):
            reported_state = "activity_unavailable"
        result: dict[str, Any] = {
            "state": reported_state,
            "work_interval_seconds": self.config.work_interval_seconds,
            "idle_threshold_seconds": self.config.idle_threshold_seconds,
            "active_elapsed_seconds": round(elapsed, 3),
            "progress": elapsed / self.config.work_interval_seconds,
            "upcoming_break": self.state in self.UPCOMING_BREAK_STATES
            or self.state == "pause" and self.paused_upcoming_break,
            "permitted_commands": [],
            "requested_effects": list(self.requested_effects),
            "today_satisfied_breaks": self.today_satisfied_breaks,
            "today_aborted_breaks": self.today_aborted_breaks,
            "consecutive_enforcement_failures": self.consecutive_enforcement_failures,
            "activity_observation_available": self.activity_observation_available,
            "degraded_wall_clock_mode": self.degraded_wall_clock_mode,
        }
        if self.warning_deadline is not None:
            result["deadline_in_seconds"] = max(0, round(self.warning_deadline - now, 3))
        elif self.snooze_deadline is not None:
            result["deadline_in_seconds"] = max(0, round(self.snooze_deadline - now, 3))
        if self.break_deadline is not None:
            result["break_remaining_seconds"] = max(0, round(self.break_deadline - now, 3))
        if self.state == "break":
            result["permitted_commands"] = ["finish_break"]
        elif self.state == "warning" and self.snoozes_remaining:
            result["permitted_commands"] = ["snooze", "pause"]
        elif self.state == "warning":
            result["permitted_commands"] = ["pause"]
        elif self.state == "snooze":
            result["permitted_commands"] = ["pause"]
        elif self.state == "pause":
            result["permitted_commands"] = ["resume"]
        elif self.state == "enforcement_unavailable":
            result["permitted_commands"] = ["retry_enforcement"]
        elif reported_state == "activity_unavailable":
            result["permitted_commands"] = ["start_manual_break"]
        elif self.state in {"idle", "work_interval"}:
            result["permitted_commands"] = ["start_manual_break"]
            if self.state == "work_interval":
                result["permitted_commands"].append("pause")
        if self.pause_deadline is not None:
            result["pause_deadline"] = self.pause_deadline.isoformat()
        if self.last_break_outcome is not None:
            result["last_break_outcome"] = self.last_break_outcome
        if result["upcoming_break"]:
            result["snoozes_remaining"] = self.snoozes_remaining
        if self.enforcement_error is not None:
            result["enforcement_error"] = self.enforcement_error
        if (
            self.window is not None
            and not self.activity_observation_available
            and not self.degraded_wall_clock_mode
        ):
            result["activity_observation_error"] = "Activity observation unavailable"
            if (
                self.state in {"idle", "work_interval"}
                and "enter_degraded_wall_clock_mode" not in result["permitted_commands"]
            ):
                result["permitted_commands"].append("enter_degraded_wall_clock_mode")
        if self.degraded_wall_clock_mode:
            result["permitted_commands"].append("leave_degraded_wall_clock_mode")
        if self.state_error is not None:
            result["state_error"] = self.state_error
        return result

    def snapshot(
        self, now: float, civil_now: datetime | None = None
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "config": asdict(self.config),
            "state": self.state,
            "active_elapsed_seconds": self.active_elapsed,
            "away": bool(self.away_sources),
            "away_started_civil": (
                self.away_started_civil.isoformat()
                if self.away_started_civil is not None
                else None
            ),
            "away_satisfied": self.away_satisfied,
            "warning_remaining_seconds": (
                max(0, self.warning_deadline - now) if self.warning_deadline is not None else None
            ),
            "snooze_remaining_seconds": (
                max(0, self.snooze_deadline - now)
                if self.snooze_deadline is not None
                else None
            ),
            "pause_deadline": (
                self.pause_deadline.isoformat() if self.pause_deadline is not None else None
            ),
            "paused_upcoming_break": self.paused_upcoming_break,
            "snoozes_remaining": self.snoozes_remaining,
            "upcoming_break_snooze_seconds": self.upcoming_break_snooze_seconds,
            "break_started_elapsed_seconds": (
                now - self.break_started_at if self.break_started_at is not None else None
            ),
            "break_remaining_seconds": (
                max(0, self.break_deadline - now) if self.break_deadline is not None else None
            ),
            "last_break_outcome": self.last_break_outcome,
            "today_satisfied_breaks": self.today_satisfied_breaks,
            "today_aborted_breaks": self.today_aborted_breaks,
            "count_date": self.count_date,
            "enforcement_error": self.enforcement_error,
            "consecutive_enforcement_failures": self.consecutive_enforcement_failures,
            "work_hours_window": self.window,
        }

    @classmethod
    def restore(
        cls, snapshot: dict[str, Any], now: float, civil_now: datetime | None = None
    ) -> "Engine":
        if snapshot.get("version") != 1:
            raise ValueError("unsupported state version")
        engine = cls(Config(**snapshot["config"]), now, civil_now)
        saved_window = snapshot.get("work_hours_window")
        saved_window = tuple(saved_window) if saved_window is not None else engine.window
        if saved_window != engine.window:
            return engine
        state = snapshot["state"]
        if state not in cls.STATES:
            raise ValueError("invalid lifecycle state")
        engine.state = state
        engine.active = False
        engine.input_active = False
        engine.active_elapsed = float(snapshot["active_elapsed_seconds"])
        engine.away_sources = {"idle"} if snapshot.get("away") is True else set()
        away_started_civil = snapshot.get("away_started_civil")
        engine.away_started_civil = (
            datetime.fromisoformat(away_started_civil)
            if away_started_civil is not None
            else None
        )
        engine.away_satisfied = snapshot.get("away_satisfied") is True
        if engine.away_started_civil is not None:
            restored_at = civil_now or datetime.now().astimezone()
            elapsed = max(
                0.0,
                (restored_at - engine.away_started_civil).total_seconds(),
            )
            engine.away_started_at = now - elapsed
        remaining = snapshot.get("warning_remaining_seconds")
        engine.warning_deadline = now + float(remaining) if remaining is not None else None
        snooze_remaining = snapshot.get("snooze_remaining_seconds")
        engine.snooze_deadline = (
            now + float(snooze_remaining) if snooze_remaining is not None else None
        )
        pause_deadline = snapshot.get("pause_deadline")
        engine.pause_deadline = (
            datetime.fromisoformat(pause_deadline) if pause_deadline is not None else None
        )
        engine.paused_upcoming_break = snapshot.get("paused_upcoming_break") is True
        engine.snoozes_remaining = snapshot.get("snoozes_remaining")
        engine.upcoming_break_snooze_seconds = snapshot.get(
            "upcoming_break_snooze_seconds"
        )
        started_elapsed = snapshot.get("break_started_elapsed_seconds")
        engine.break_started_at = (
            now - float(started_elapsed) if started_elapsed is not None else None
        )
        break_remaining = snapshot.get("break_remaining_seconds")
        engine.break_deadline = (
            now + float(break_remaining) if break_remaining is not None else None
        )
        engine.last_break_outcome = snapshot.get("last_break_outcome")
        engine.today_satisfied_breaks = int(snapshot.get("today_satisfied_breaks", 0))
        engine.today_aborted_breaks = int(snapshot.get("today_aborted_breaks", 0))
        engine.count_date = snapshot.get("count_date", engine.count_date)
        engine.enforcement_error = snapshot.get("enforcement_error")
        engine.consecutive_enforcement_failures = int(
            snapshot.get("consecutive_enforcement_failures", 0)
        )
        engine.activity_observation_available = False
        engine.degraded_wall_clock_mode = False
        if engine.state in {"starting_break", "break", "enforcement_unavailable"}:
            engine.state = "warning"
            engine.warning_deadline = now
            engine.snooze_deadline = None
            engine.break_started_at = None
            engine.break_deadline = None
        engine._reconcile_count_date(civil_now or datetime.now().astimezone())
        return engine
