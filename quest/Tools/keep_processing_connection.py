"""Keep Quest's existing private processing route available over wireless ADB.

Run with --serial IP:port and optionally --adb /path/to/adb. Leave running
while using the headset; --once checks/repairs once and returns 0 on success.
This maintains only ADB reverse forwarding, not the SSH tunnel or app session.
"""

import argparse
import ipaddress
import subprocess
import sys
import time

PORT = "tcp:8443"


class RouteError(Exception):
    """A transient connection or forwarding failure that can be retried."""


def wireless_serial(value: str) -> str:
    """Require an explicit IP endpoint, including brackets around IPv6."""
    try:
        if not isinstance(value, str):
            raise TypeError
        host, port = value.rsplit(":", 1)
        address = ipaddress.ip_address(host.strip("[]"))
        if address.version == 6 and host != f"[{address}]":
            raise ValueError
        if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("Use an IP:port, e.g. 192.0.2.10:5555") from error
    return value


def run_adb(adb: str, *arguments: str) -> str:
    """Run one bounded ADB command; do not include raw device output in logs."""
    try:
        return subprocess.run(
            [adb, *arguments], capture_output=True, text=True, check=True, timeout=8,
        ).stdout.strip()
    except subprocess.TimeoutExpired as error:
        raise RouteError("ADB timed out after 8 seconds; check headset Wi-Fi and debugging.") from error
    except subprocess.CalledProcessError as error:
        raise RouteError("ADB command failed; check headset Wi-Fi and authorize debugging.") from error


def has_mapping(output: str) -> bool:
    """ADB --list gives one device/source/destination triple per route."""
    return any(len(parts) == 3 and parts[1:] == [PORT, PORT]
               for parts in (line.split() for line in output.splitlines()))


def ensure_route(adb: str, serial: str) -> None:
    """Reconnect only when needed, then restore and verify this single route."""
    try:
        connected = run_adb(adb, "-s", serial, "get-state") == "device"
    except RouteError:
        connected = False
    if not connected:
        run_adb(adb, "connect", serial)
        if run_adb(adb, "-s", serial, "get-state") != "device":
            raise RouteError("Headset unavailable; check its IP, Wi-Fi and debugging authorization.")
    if not has_mapping(run_adb(adb, "-s", serial, "reverse", "--list")):
        # ADB replaces an existing destination unless --no-rebind is specified.
        run_adb(adb, "-s", serial, "reverse", PORT, PORT)
        if not has_mapping(run_adb(adb, "-s", serial, "reverse", "--list")):
            raise RouteError("ADB reverse mapping missing after repair; check headset connection.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, type=wireless_serial)
    parser.add_argument("--adb", default="adb", help="ADB executable (default: adb on PATH)")
    parser.add_argument("--once", action="store_true", help="Check/repair once; exit 1 if unavailable")
    args = parser.parse_args(argv)
    previous = None
    try:
        while True:
            try:
                ensure_route(args.adb, args.serial)
                status = f"ADB route ready for {args.serial}: {PORT} -> {PORT}"
                result = 0
            except RouteError as error:
                status = f"Waiting for ADB route: {error}"
                result = 1
            if status != previous:
                print(status, flush=True)
                previous = status
            if args.once:
                return result
            time.sleep(5)
    except FileNotFoundError:
        print("ADB executable missing. Install Android SDK Platform-Tools or pass --adb /path/to/adb.",
              file=sys.stderr)
        return 2
    except OSError:
        print("Cannot execute ADB. Check the --adb path and executable permissions.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ADB route keeper stopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
