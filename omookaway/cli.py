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
    ready = subparsers.add_parser("overlay-ready")
    ready.add_argument("display_ids")
    ready.add_argument("covered_display_ids")
    ready.add_argument("input_inhibited", choices=("true", "false"))
    failed = subparsers.add_parser("overlay-failed")
    failed.add_argument("error")
    subparsers.add_parser("start-break")
    subparsers.add_parser("finish-break")
    subparsers.add_parser("retry-enforcement")
    args = parser.parse_args()
    if args.command == "status":
        message = {"type": "status"}
    elif args.command == "activity":
        message = {"type": "activity", "active": args.state == "active"}
    elif args.command == "overlay-ready":
        message = {
            "type": "overlay_ready",
            "display_ids": json.loads(args.display_ids),
            "covered_display_ids": json.loads(args.covered_display_ids),
            "input_inhibited": args.input_inhibited == "true",
        }
    elif args.command == "overlay-failed":
        message = {"type": "overlay_failed", "error": args.error}
    elif args.command == "start-break":
        message = {"type": "start_manual_break"}
    elif args.command == "finish-break":
        message = {"type": "finish_break"}
    elif args.command == "retry-enforcement":
        message = {"type": "retry_enforcement"}
    else:
        message = {"type": "configure", "config": json.loads(args.file.read_text())}
    print(json.dumps(asyncio.run(request(message)), indent=2))


if __name__ == "__main__":
    main()
