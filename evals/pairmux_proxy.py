#!/usr/bin/env python3
"""PATH-fronted client for the eval runner's pairmux execution broker.

The client can request an execution, but it cannot report evidence. The runner-owned broker chooses
the executable and environment, launches pairmux, and records the real child lifecycle.
"""

from __future__ import annotations

from array import array
import json
import os
from pathlib import Path
import socket
import struct
import sys


REQUEST_SCHEMA = "pairmux.eval.exec.v1"
RESPONSE_SCHEMA = "pairmux.eval.exec-result.v1"
MAX_FRAME_BYTES = 32 * 1024


def encode_frame(payload: dict[str, object]) -> bytes:
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    if len(encoded) > MAX_FRAME_BYTES:
        raise ValueError("pairmux eval broker request exceeds 32 KiB")
    return struct.pack("!I", len(encoded)) + encoded


def recv_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("pairmux eval broker closed before returning a result")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(connection: socket.socket) -> dict[str, object]:
    length = struct.unpack("!I", recv_exact(connection, 4))[0]
    if length > MAX_FRAME_BYTES:
        raise ValueError("pairmux eval broker response exceeds 32 KiB")
    payload = json.loads(recv_exact(connection, length))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "returncode", "error"}
        or payload.get("schema") != RESPONSE_SCHEMA
        or not isinstance(payload.get("returncode"), int)
        or payload.get("error") is not None
        and not isinstance(payload.get("error"), str)
    ):
        raise ValueError("pairmux eval broker returned an invalid result")
    return payload


def main() -> int:
    if os.name != "posix" or not hasattr(socket, "SCM_RIGHTS"):
        print("pairmux eval proxy: Unix descriptor passing is required", file=sys.stderr)
        return 125

    broker_socket = Path(sys.argv[0]).resolve().parent.parent / "broker.sock"
    request = encode_frame(
        {
            "schema": REQUEST_SCHEMA,
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
        }
    )
    descriptors = array("i", (0, 1, 2))

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(broker_socket))
            sent = connection.sendmsg(
                [request],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors.tobytes())],
            )
            if sent < len(request):
                connection.sendall(request[sent:])
            result = recv_frame(connection)
    except KeyboardInterrupt:
        return 130
    except (ConnectionError, json.JSONDecodeError, OSError, ValueError) as error:
        print(f"pairmux eval proxy: {error}", file=sys.stderr)
        return 125

    if result["error"]:
        print(f"pairmux eval broker: {result['error']}", file=sys.stderr)
    returncode = int(result["returncode"])
    return 128 + (-returncode) if returncode < 0 else returncode


if __name__ == "__main__":
    raise SystemExit(main())
