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
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


def ping(url: str, timeout: int = 10) -> int:
    request = Request(
        url,
        headers={
            "User-Agent": "MHXII-Keepalive/1.0",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        response.read()
        return response.status


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping a Render service on an interval.")
    parser.add_argument("--url", default=os.environ.get("KEEPALIVE_URL") or os.environ.get("MHXII_SERVICE_URL"), help="Base URL of the deployed service, e.g. https://your-service.onrender.com")
    parser.add_argument("--path", default="/keepalive", help="Primary path to request (default: /keepalive)")
    parser.add_argument(
        "--fallback-paths",
        default="/ping,/",
        help="Comma-separated fallback paths to try if the primary request fails (default: /ping, /)",
    )
    parser.add_argument("--interval", type=int, default=int(os.environ.get("KEEPALIVE_INTERVAL", "240")), help="Seconds between requests (default: 240)")
    parser.add_argument("--once", action="store_true", help="Send one request and exit")
    args = parser.parse_args()

    if not args.url:
        print("Missing keepalive URL. Set --url or KEEPALIVE_URL/MHXII_SERVICE_URL.", file=sys.stderr)
        return 2

    base_url = args.url.rstrip("/")
    paths = [args.path] + [path.strip() for path in args.fallback_paths.split(",") if path.strip()]

    while True:
        now = dt.datetime.now().isoformat(timespec="seconds")
        success = False
        last_error = None

        for path in paths:
            query = urlencode({"t": int(time.time())})
            target = f"{base_url}{path}?{query}"
            try:
                status = ping(target)
                print(f"[{now}] OK {status} {target}")
                success = True
                break
            except HTTPError as exc:
                last_error = f"HTTP error {exc.code} {target}"
                print(f"[{now}] {last_error}", file=sys.stderr)
            except URLError as exc:
                last_error = f"URL error {exc.reason} {target}"
                print(f"[{now}] {last_error}", file=sys.stderr)
            except Exception as exc:
                last_error = f"Error {exc} {target}"
                print(f"[{now}] {last_error}", file=sys.stderr)

        if not success and last_error:
            print(f"[{now}] keepalive failed after {len(paths)} attempt(s)", file=sys.stderr)

        if args.once:
            return 0

        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
