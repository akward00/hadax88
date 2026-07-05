"""Async TCP client for the Dayton Audio DAX88."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .protocol import build_command_frame, build_query_frame, command_id, display_to_raw, parse_state, DaxState

_LOGGER = logging.getLogger(__name__)


class Dax88Error(Exception):
    """Base DAX88 client error."""


class Dax88ConnectionError(Dax88Error):
    """Raised when the DAX88 cannot be reached or parsed."""


class Dax88Client:
    """Small stateless async TCP client."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def query(self) -> DaxState:
        """Query the DAX88 for names and zone status."""

        data = await self._send_and_read(build_query_frame(), collect_until_timeout=True)
        state = parse_state(data)
        if not state.config and not state.zones:
            raise Dax88ConnectionError("Device did not return a valid DAX88 config/status response")
        return state

    async def send(self, zone: int, command: str, value: int | bool) -> bytes:
        """Send one zone command and return the echo/ack bytes if any."""

        frame = build_command_frame(zone, command_id(command), display_to_raw(command, value))
        return await self._send_and_read(frame, collect_until_timeout=False)

    async def set_power(self, zone: int, on: bool) -> None:
        """Turn a zone on or off."""

        await self.send(zone, "power", on)

    async def set_mute(self, zone: int, muted: bool) -> None:
        """Mute or unmute a zone."""

        await self.send(zone, "mute", muted)

    async def set_volume(self, zone: int, volume: int) -> None:
        """Set zone volume in display units 0..38."""

        await self.send(zone, "volume", volume)

    async def set_source(self, zone: int, source: int) -> None:
        """Select a source by 1-based source number."""

        await self.send(zone, "source", source)

    async def set_bass(self, zone: int, value: int) -> None:
        """Set zone bass in display units -12..12."""

        await self.send(zone, "bass", value)

    async def set_treble(self, zone: int, value: int) -> None:
        """Set zone treble in display units -12..12."""

        await self.send(zone, "treble", value)

    async def set_balance(self, zone: int, value: int) -> None:
        """Set zone balance in display units 0..20."""

        await self.send(zone, "balance", value)

    async def _send_and_read(self, frame: bytes, *, collect_until_timeout: bool) -> bytes:
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            writer.write(frame)
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)

            chunks: list[bytes] = []
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(8192), timeout=self.timeout)
                except TimeoutError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
                if not collect_until_timeout:
                    break
            return b"".join(chunks)
        except (OSError, TimeoutError, asyncio.TimeoutError) as err:
            raise Dax88ConnectionError(f"Could not communicate with DAX88 at {self.host}:{self.port}") from err
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError, TimeoutError, asyncio.TimeoutError):
                    _LOGGER.debug("Timed out closing DAX88 connection", exc_info=True)


async def with_retries(
    action: Callable[[], Awaitable[DaxState]],
    attempts: int = 2,
) -> DaxState:
    """Run a query action with a small retry budget."""

    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return await action()
        except Dax88Error as err:
            last_error = err
            await asyncio.sleep(0.2)
    raise Dax88ConnectionError("DAX88 query failed after retries") from last_error
