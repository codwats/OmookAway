from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Config:
    work_interval_seconds: int = 30 * 60
    warning_seconds: int = 20

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


class Engine:
    """Public deterministic seam shared by production adapters and tests."""

    STATES = {"idle", "work_interval", "warning"}

    def __init__(self, config: Config, now: float) -> None:
        self.config = config
        self.state = "idle"
        self.active = False
        self.active_elapsed = 0.0
        self.last_at = now
        self.warning_deadline: float | None = None

    def apply(self, event: dict[str, Any], now: float) -> dict[str, Any]:
        self._advance(now)
        if event.get("type") == "activity":
            self.active = event.get("active") is True
            if self.state not in {"warning"}:
                self.state = "work_interval" if self.active else "idle"
        elif event.get("type") != "time":
            raise ValueError("unsupported engine event")
        return self.status(now)

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

    def status(self, now: float) -> dict[str, Any]:
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
        }

    @classmethod
    def restore(cls, snapshot: dict[str, Any], now: float) -> "Engine":
        if snapshot.get("version") != 1:
            raise ValueError("unsupported state version")
        engine = cls(Config(**snapshot["config"]), now)
        state = snapshot["state"]
        if state not in cls.STATES:
            raise ValueError("invalid lifecycle state")
        engine.state = state
        engine.active = snapshot["active"] is True
        engine.active_elapsed = float(snapshot["active_elapsed_seconds"])
        remaining = snapshot.get("warning_remaining_seconds")
        engine.warning_deadline = now + float(remaining) if remaining is not None else None
        return engine
