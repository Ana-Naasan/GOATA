"""Run one private processing service; remote listeners require TLS."""

import argparse
import ipaddress

import uvicorn

from processing.service import create_app
from processing.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    args = parser.parse_args()
    try:
        loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = args.host == "localhost"
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        parser.error("TLS requires both --ssl-certfile and --ssl-keyfile")
    if not loopback and not (args.ssl_certfile and args.ssl_keyfile):
        parser.error("Non-loopback listeners require --ssl-certfile and --ssl-keyfile")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1,
                ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile, access_log=False)


if __name__ == "__main__":
    main()
