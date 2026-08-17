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
    work_hours: Any = None

    def __post_init__(self) -> None:
        for name in ("work_interval_seconds", "warning_seconds"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be positive")
        object.__setattr__(self, "work_hours", _work_hours(self.work_hours))


class Engine:
    """Public deterministic seam shared by production adapters and tests."""

    STATES = {"dormant", "idle", "work_interval", "warning"}

    def __init__(self, config: Config, now: float, civil_now: datetime | None = None) -> None:
        self.config = config
        self.window = self._window_at(civil_now or datetime.now().astimezone())
        self.state = "idle" if self.window is not None else "dormant"
        self.active = False
        self.active_elapsed = 0.0
        self.last_at = now
        self.warning_deadline: float | None = None

    def apply(
        self, event: dict[str, Any], now: float, civil_now: datetime | None = None
    ) -> dict[str, Any]:
        civil_now = civil_now or datetime.now().astimezone()
        new_config = None
        if event.get("type") == "configure":
            values = asdict(self.config)
            values.update(event["config"])
            new_config = Config(**values)
        if self._reconcile_window(civil_now):
            self.last_at = now
        else:
            self._advance(now)
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
        elif event.get("type") == "activity":
            self.active = event.get("active") is True
            if self.window is None:
                self.state = "dormant"
            elif self.state not in {"warning"}:
                self.state = "work_interval" if self.active else "idle"
        elif event.get("type") != "time":
            raise ValueError("unsupported engine event")
        return self.status(now, civil_now)

    def _advance(self, now: float) -> None:
        if now < self.last_at:
            raise ValueError("monotonic time moved backwards")
        if self.active and self.state == "work_interval":
            due_in = self.config.work_interval_seconds - self.active_elapsed
            elapsed = now - self.last_at
            if elapsed >= due_in:
                self.active_elapsed = float(self.config.work_interval_seconds)
                self.state = "warning"
                self.warning_deadline = self.last_at + due_in + self.config.warning_seconds
            else:
                self.active_elapsed += elapsed
        self.last_at = now

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
        self.active_elapsed = 0.0
        self.warning_deadline = None
        if window is None:
            self.state = "dormant"
        else:
            self.state = "idle"
        return True

    def status(self, now: float, civil_now: datetime | None = None) -> dict[str, Any]:
        if self._reconcile_window(civil_now or datetime.now().astimezone()):
            self.last_at = now
        elapsed = min(self.active_elapsed, self.config.work_interval_seconds)
        result: dict[str, Any] = {
            "state": self.state,
            "work_interval_seconds": self.config.work_interval_seconds,
            "active_elapsed_seconds": round(elapsed, 3),
            "progress": elapsed / self.config.work_interval_seconds,
            "upcoming_break": self.state == "warning",
            "permitted_commands": [],
        }
        if self.warning_deadline is not None:
            result["deadline_in_seconds"] = max(0, round(self.warning_deadline - now, 3))
        return result

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            "version": 1,
            "config": asdict(self.config),
            "state": self.state,
            "active": self.active,
            "active_elapsed_seconds": self.active_elapsed,
            "warning_remaining_seconds": (
                max(0, self.warning_deadline - now) if self.warning_deadline is not None else None
            ),
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
        engine.active = snapshot["active"] is True
        engine.active_elapsed = float(snapshot["active_elapsed_seconds"])
        remaining = snapshot.get("warning_remaining_seconds")
        engine.warning_deadline = now + float(remaining) if remaining is not None else None
        return engine
