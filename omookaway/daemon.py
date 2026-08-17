import argparse
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .engine import Config, Engine


def xdg_path(variable: str, fallback: str, name: str) -> Path:
    return Path(os.environ.get(variable, str(Path.home() / fallback))) / "omookaway" / name


class StateFiles:
    def __init__(self, state_path: Path, status_path: Path) -> None:
        self.state_path = state_path
        self.status_path = status_path

    def load(self, now: float, civil_now: datetime | None = None) -> Engine:
        try:
            return Engine.restore(json.loads(self.state_path.read_text()), now, civil_now)
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return Engine(Config(), now, civil_now)

    def publish(self, engine: Engine, now: float, civil_now: datetime | None = None) -> None:
        self._write(self.state_path, engine.snapshot(now), private=True)
        self._write(self.status_path, engine.status(now, civil_now), private=False)

    @staticmethod
    def _write(path: Path, value: dict[str, Any], private: bool) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, separators=(",", ":"))
                stream.write("\n")
            os.chmod(temporary, 0o600 if private else 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class Daemon:
    def __init__(self, socket_path: Path, files: StateFiles) -> None:
        self.socket_path = socket_path
        self.files = files
        self.engine = files.load(time.monotonic(), datetime.now().astimezone())

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = json.loads((await reader.readline()).decode())
            now = time.monotonic()
            civil_now = datetime.now().astimezone()
            if request.get("type") == "status":
                response = self.engine.status(now, civil_now)
            else:
                response = self.engine.apply(request, now, civil_now)
                self.files.publish(self.engine, now, civil_now)
            writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode())
            await writer.drain()
        except (ValueError, json.JSONDecodeError) as error:
            writer.write((json.dumps({"error": str(error)}) + "\n").encode())
        finally:
            writer.close()
            await writer.wait_closed()

    async def tick(self) -> None:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            civil_now = datetime.now().astimezone()
            self.engine.apply({"type": "time"}, now, civil_now)
            self.files.publish(self.engine, now, civil_now)

    async def run(self) -> None:
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        self.files.publish(self.engine, time.monotonic(), datetime.now().astimezone())
        server = await asyncio.start_unix_server(self.handle, path=self.socket_path)
        os.chmod(self.socket_path, 0o600)
        try:
            async with server:
                await asyncio.gather(server.serve_forever(), self.tick())
        finally:
            self.socket_path.unlink(missing_ok=True)


def paths() -> tuple[Path, StateFiles]:
    socket_path = xdg_path("XDG_RUNTIME_DIR", ".cache", "engine.sock")
    state_path = xdg_path("XDG_STATE_HOME", ".local/state", "engine.json")
    status_path = xdg_path("XDG_RUNTIME_DIR", ".cache", "status.json")
    return socket_path, StateFiles(state_path, status_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="OmookAway break engine daemon")
    parser.parse_args()
    socket_path, files = paths()
    asyncio.run(Daemon(socket_path, files).run())


if __name__ == "__main__":
    main()
