"""Active TCP discovery for DAX88 devices."""

from __future__ import annotations

import asyncio
import ipaddress
import socket

from .client import Dax88Client, Dax88Error
from .const import DEFAULT_PORT, DEFAULT_SCAN_PREFIX, DEFAULT_SCAN_TIMEOUT
from .protocol import DaxState


def local_subnet_guess(prefix: int = DEFAULT_SCAN_PREFIX) -> str | None:
    """Guess the primary IPv4 subnet."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()

    return str(ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False))


async def verify_host(host: str, port: int = DEFAULT_PORT, timeout: float = DEFAULT_SCAN_TIMEOUT) -> DaxState:
    """Verify a host by sending the DAX88 query and parsing a real response."""

    return await Dax88Client(host, port, timeout).query()


async def scan_subnet(
    subnet: str,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_SCAN_TIMEOUT,
    max_hosts: int = 512,
    concurrency: int = 64,
) -> list[tuple[str, DaxState]]:
    """Scan a subnet for DAX88 devices on TCP 8899."""

    network = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(host) for host in network.hosts()]
    if len(hosts) > max_hosts:
        raise ValueError(f"Refusing to scan {len(hosts)} hosts; use a /23 or smaller subnet")

    semaphore = asyncio.Semaphore(concurrency)
    results: list[tuple[str, DaxState]] = []

    async def _check(host: str) -> None:
        async with semaphore:
            try:
                state = await verify_host(host, port, timeout)
            except (Dax88Error, OSError, TimeoutError, asyncio.TimeoutError):
                return
            results.append((host, state))

    await asyncio.gather(*(_check(host) for host in hosts))
    return results
