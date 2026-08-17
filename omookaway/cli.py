import argparse
import asyncio
import json

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
    args = parser.parse_args()
    message = (
        {"type": "status"}
        if args.command == "status"
        else {"type": "activity", "active": args.state == "active"}
    )
    print(json.dumps(asyncio.run(request(message)), indent=2))


if __name__ == "__main__":
    main()
