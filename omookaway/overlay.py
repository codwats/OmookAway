import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


class OverlayProcess:
    """Lifecycle boundary for the dedicated Quickshell Break process."""

    def __init__(
        self,
        qml_path: Path,
        on_failure: Callable[[str], Awaitable[None]],
        *,
        spawn: Callable[..., Awaitable[Any]] = asyncio.create_subprocess_exec,
    ) -> None:
        self.qml_path = qml_path
        self.on_failure = on_failure
        self.spawn = spawn
        self.process: Any | None = None
        self.monitor: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def launch(self) -> None:
        await self.release()
        self.process = await self.spawn("qs", "--path", str(self.qml_path))
        self.monitor = asyncio.create_task(self._monitor(self.process))

    async def release(self) -> None:
        monitor, process = self.monitor, self.process
        self.monitor = None
        self.process = None
        if monitor is not None:
            monitor.cancel()
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        if monitor is not None:
            try:
                await monitor
            except asyncio.CancelledError:
                pass

    async def _monitor(self, process: Any) -> None:
        returncode = await process.wait()
        if process is not self.process:
            return
        self.process = None
        self.monitor = None
        await self.on_failure(f"Break overlay exited with status {returncode}")
