import ipaddress
import os
import socket
from typing import Any


class NetworkBlocked(RuntimeError):
    pass


def install() -> None:
    """Block external TCP connections before DNS or socket connection in fake tests."""
    os.environ["AI_TEST_BLOCK_EXTERNAL"] = "1"
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection
    original_lookup = socket.getaddrinfo
    original_sendto = socket.socket.sendto

    def check(host: object) -> None:
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(str(host)).is_loopback:
                return
        except ValueError:
            pass
        raise NetworkBlocked("External network is blocked in fake tests")

    def connect(sock: socket.socket, address: Any) -> None:
        if isinstance(address, tuple):
            check(address[0])
        else:
            raise NetworkBlocked("Non-TCP sockets are blocked in fake tests")
        original_connect(sock, address)

    def create(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        check(address[0])
        return original_create(address, *args, **kwargs)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        check(address[0])
        return original_connect_ex(sock, address)

    def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None:
            check(host)
        return original_lookup(host, *args, **kwargs)

    def sendto(sock: socket.socket, *args: Any) -> int:
        check(args[-1][0])
        return original_sendto(sock, *args)

    socket.socket.connect = connect  # type: ignore[assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[assignment]
    socket.socket.sendto = sendto  # type: ignore[assignment]
    socket.create_connection = create
    socket.getaddrinfo = lookup
