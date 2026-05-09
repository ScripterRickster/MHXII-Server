"""Simple keepalive pinger for a Raspberry Pi.

Run this script on a machine that stays online (for example, the Pi) to
periodically request the Render service and reduce the chance of idle spin-down.

Example:
    python keepalive.py --url https://your-service.onrender.com --interval 240
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


def ping(url: str, timeout: int = 10) -> int:
    request = Request(url, headers={"User-Agent": "MHXII-Keepalive/1.0"})
    with urlopen(request, timeout=timeout) as response:
        response.read()
        return response.status


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping a Render service on an interval.")
    parser.add_argument("--url", default=os.environ.get("KEEPALIVE_URL") or os.environ.get("MHXII_SERVICE_URL"), help="Base URL of the deployed service, e.g. https://your-service.onrender.com")
    parser.add_argument("--path", default="/ping", help="Path to request (default: /ping)")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("KEEPALIVE_INTERVAL", "240")), help="Seconds between requests (default: 240)")
    parser.add_argument("--once", action="store_true", help="Send one request and exit")
    args = parser.parse_args()

    if not args.url:
        print("Missing keepalive URL. Set --url or KEEPALIVE_URL/MHXII_SERVICE_URL.", file=sys.stderr)
        return 2

    target = args.url.rstrip("/") + args.path

    while True:
        now = dt.datetime.now().isoformat(timespec="seconds")
        try:
            status = ping(target)
            print(f"[{now}] OK {status} {target}")
        except HTTPError as exc:
            print(f"[{now}] HTTP error {exc.code} {target}", file=sys.stderr)
        except URLError as exc:
            print(f"[{now}] URL error {exc.reason} {target}", file=sys.stderr)
        except Exception as exc:
            print(f"[{now}] Error {exc} {target}", file=sys.stderr)

        if args.once:
            return 0

        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
