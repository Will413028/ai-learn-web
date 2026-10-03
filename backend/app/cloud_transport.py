"""One-shot isolated HTTP/DNS transport. Credentials arrive on stdin, never argv/env."""
import json
import os
import socket
import sys

import httpx

from app.network_guard import NetworkBlocked, install

if os.getenv("AI_TEST_BLOCK_EXTERNAL") == "1":
    install()

LIMIT = 32 * 1024 * 1024


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read(4 * 1024 * 1024 + 1))
        if data.get("operation") == "resolve":
            addresses = socket.getaddrinfo(data["host"], data["port"], type=socket.SOCK_STREAM)
            sys.stdout.write(json.dumps(sorted({str(row[4][0]) for row in addresses})))
            return 0
        with httpx.Client(trust_env=False, follow_redirects=False,
                          timeout=httpx.Timeout(data["timeout"], connect=min(5, data["timeout"]))) as client:
            with client.stream("POST", data["url"], json=data["payload"],
                               headers={"Authorization": "Bearer " + data["key"]}) as response:
                if response.status_code == 429:
                    return 4
                if response.status_code != 200:
                    return 5
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > LIMIT:
                        return 6
                parsed = json.loads(result)
                if not isinstance(parsed, dict):
                    return 6
                sys.stdout.buffer.write(result)
                return 0
    except NetworkBlocked:
        return 7
    except httpx.TimeoutException:
        return 2
    except Exception:
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
