import argparse
import asyncio
import json
from pathlib import Path

from .daemon import paths


async def request(message: dict[str, object]) -> dict[str, object]:
    socket_path, _ = paths()
    reader, writer = await asyncio.open_unix_connection(socket_path)
    writer.write((json.dumps(message) + "\n").encode())
    await writer.drain()
    response = json.loads((await reader.readline()).decode())
    writer.close()
    await writer.wait_closed()
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the OmookAway break engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    activity = subparsers.add_parser("activity")
    activity.add_argument("state", choices=("active", "idle"))
    configure = subparsers.add_parser("configure")
    configure.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.command == "status":
        message = {"type": "status"}
    elif args.command == "activity":
        message = {"type": "activity", "active": args.state == "active"}
    else:
        message = {"type": "configure", "config": json.loads(args.file.read_text())}
    print(json.dumps(asyncio.run(request(message)), indent=2))


if __name__ == "__main__":
    main()
