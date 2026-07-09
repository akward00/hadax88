"""Async TCP client for the Dayton Audio DAX88."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .protocol import (
    DaxState,
    apply_payload,
    build_command_frame,
    build_query_frame,
    command_id,
    display_to_raw,
    extract_first_frame,
    parse_state,
    extract_payloads,
)

_LOGGER = logging.getLogger(__name__)
StateCallback = Callable[[DaxState], None]
ConnectionCallback = Callable[[bool], None]


class Dax88Error(Exception):
    """Base DAX88 client error."""


class Dax88ConnectionError(Dax88Error):
    """Raised when the DAX88 cannot be reached or parsed."""


class Dax88Client:
    """Async TCP client with a persistent push socket."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.state: DaxState | None = None
        self.connected = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._state_callback: StateCallback | None = None
        self._connection_callback: ConnectionCallback | None = None
        self._ready_event = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._stopped = False

    async def async_start(
        self,
        state_callback: StateCallback,
        connection_callback: ConnectionCallback | None = None,
    ) -> None:
        """Start the persistent read loop."""

        self._state_callback = state_callback
        self._connection_callback = connection_callback
        self._stopped = False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._connection_loop(), name=f"dax88-{self.host}")

    async def async_wait_ready(self) -> DaxState:
        """Wait for the first valid state from the persistent socket."""

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=max(self.timeout * 3, 6.0))
        except TimeoutError as err:
            raise Dax88ConnectionError(f"DAX88 at {self.host}:{self.port} did not return initial state") from err
        if self.state is None:
            raise Dax88ConnectionError(f"DAX88 at {self.host}:{self.port} did not return initial state")
        return self.state

    async def async_stop(self) -> None:
        """Stop the persistent socket and reader task."""

        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_writer()
        self.connected = False
        self._notify_connection(False)

    async def async_send(self, zone: int, command: str, value: int | bool) -> None:
        """Send one zone command over the persistent socket."""

        frame = build_command_frame(zone, command_id(command), display_to_raw(command, value))
        async with self._send_lock:
            writer = self._writer
            if writer is None or writer.is_closing():
                raise Dax88ConnectionError(f"DAX88 socket is not connected to {self.host}:{self.port}")
            try:
                writer.write(frame)
                await asyncio.wait_for(writer.drain(), timeout=self.timeout)
            except (OSError, TimeoutError, asyncio.TimeoutError) as err:
                raise Dax88ConnectionError(f"Could not send DAX88 command to {self.host}:{self.port}") from err

    async def query(self) -> DaxState:
        """Query the DAX88 for names and zone status using a temporary socket."""

        data = await self._send_and_read(build_query_frame(), collect_until_timeout=True)
        state = parse_state(data)
        if not state.config and not state.zones:
            raise Dax88ConnectionError("Device did not return a valid DAX88 config/status response")
        return state

    async def send(self, zone: int, command: str, value: int | bool) -> bytes:
        """Send one zone command on a temporary socket and return echo/ack bytes if any."""

        frame = build_command_frame(zone, command_id(command), display_to_raw(command, value))
        return await self._send_and_read(frame, collect_until_timeout=False)

    async def set_power(self, zone: int, on: bool) -> None:
        """Turn a zone on or off."""

        await self.async_send(zone, "power", on)

    async def set_mute(self, zone: int, muted: bool) -> None:
        """Mute or unmute a zone."""

        await self.async_send(zone, "mute", muted)

    async def set_volume(self, zone: int, volume: int) -> None:
        """Set zone volume in display units 0..38."""

        await self.async_send(zone, "volume", volume)

    async def set_source(self, zone: int, source: int) -> None:
        """Select a source by 1-based source number."""

        await self.async_send(zone, "source", source)

    async def set_bass(self, zone: int, value: int) -> None:
        """Set zone bass in display units -12..12."""

        await self.async_send(zone, "bass", value)

    async def set_treble(self, zone: int, value: int) -> None:
        """Set zone treble in display units -12..12."""

        await self.async_send(zone, "treble", value)

    async def set_balance(self, zone: int, value: int) -> None:
        """Set zone balance in display units 0..20."""

        await self.async_send(zone, "balance", value)

    async def _connection_loop(self) -> None:
        backoff = 1.0
        while not self._stopped:
            try:
                await self._open_socket()
                backoff = 1.0
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the integration reconnecting.
                _LOGGER.debug("DAX88 socket loop failed for %s:%s", self.host, self.port, exc_info=True)
            finally:
                await self._close_writer()
                if self.connected:
                    self.connected = False
                    self._notify_connection(False)

            if not self._stopped:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _open_socket(self) -> None:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=self.timeout)
        self._reader = reader
        self._writer = writer
        self.connected = True
        self._notify_connection(True)
        writer.write(build_query_frame())
        await asyncio.wait_for(writer.drain(), timeout=self.timeout)

    async def _read_loop(self) -> None:
        if self._reader is None:
            raise Dax88ConnectionError("DAX88 read loop started without a socket")

        buffer = bytearray()
        while not self._stopped:
            chunk = await self._reader.read(8192)
            if not chunk:
                raise Dax88ConnectionError(f"DAX88 socket closed by {self.host}:{self.port}")
            buffer.extend(chunk)
            while frame := extract_first_frame(buffer):
                self._process_frame(frame)

    def _process_frame(self, frame: bytes) -> None:
        payloads = extract_payloads(frame)
        if not payloads:
            _LOGGER.debug("Ignoring DAX88 frame with invalid checksum from %s", self.host)
            return

        for payload in payloads:
            new_state = apply_payload(self.state, payload)
            if new_state is None:
                _LOGGER.debug("Ignoring unhandled DAX88 payload from %s: %s", self.host, payload.hex(" "))
                continue
            self.state = new_state
            if new_state.config is not None and new_state.zones:
                self._ready_event.set()
                if self._state_callback is not None:
                    self._state_callback(new_state)

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

    async def _close_writer(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, TimeoutError, asyncio.TimeoutError):
                _LOGGER.debug("Timed out closing DAX88 persistent connection", exc_info=True)

    def _notify_connection(self, connected: bool) -> None:
        if self._connection_callback is not None:
            self._connection_callback(connected)


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
