"""Standalone DAX88 TCP protocol helpers for the debug GUI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import socket
import struct
import time

MAGIC = bytes.fromhex("18 96 18 20")
PREFIX = b"MCU+PAS+"
TERMINATOR = bytes.fromhex("ff cc 26")
DEFAULT_PORT = 8899

COMMANDS = {
    "volume": 0x01,
    "treble": 0x02,
    "bass": 0x03,
    "balance": 0x05,
    "power": 0x08,
    "source": 0x0D,
    "mute": 0x0E,
}

MAX_VOLUME = 38


@dataclass(slots=True)
class DaxConfig:
    device_name: str | None
    zones: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ZoneStatus:
    zone: int
    name: str
    source: int
    source_name: str
    volume: int
    treble: int
    bass: int
    balance: int
    power_on: bool
    muted: bool
    source_raw: int
    volume_raw: int
    treble_raw: int
    bass_raw: int
    balance_raw: int
    power_raw: int
    mute_raw: int


@dataclass(slots=True)
class DaxState:
    device_name: str | None
    config: DaxConfig | None
    zones: list[ZoneStatus]
    raw_response_hex: str

    def to_dict(self) -> dict:
        return {
            "device_name": self.device_name,
            "config": asdict(self.config) if self.config else None,
            "zones": [asdict(zone) for zone in self.zones],
            "raw_response_hex": self.raw_response_hex,
        }


def wrap_payload(payload: bytes) -> bytes:
    checksum = sum(payload) & 0xFFFF
    return MAGIC + struct.pack("<I", len(payload)) + struct.pack("<H", checksum) + (b"\x00" * 10) + payload


def build_query_frame() -> bytes:
    return wrap_payload(PREFIX + bytes.fromhex("82 0a ff ff ff 89 26"))


def build_command_frame(zone: int, command: str, display_value: int | bool) -> bytes:
    if command not in COMMANDS:
        raise ValueError(f"unknown command: {command}")
    if not 1 <= zone <= 8:
        raise ValueError("zone must be 1..8")
    value = display_to_raw(command, display_value)
    zone_bytes = bytearray([0x02] * 8)
    zone_bytes[zone - 1] = 0x01
    payload = PREFIX + bytes([0x82, COMMANDS[command], value]) + bytes(zone_bytes) + TERMINATOR
    return wrap_payload(payload)


def display_to_raw(command: str, value: int | bool) -> int:
    if command == "power":
        return 0x02 if bool(value) else 0x01
    if command == "mute":
        return 0x02 if bool(value) else 0x01
    if command == "volume":
        value = int(value)
        if not 0 <= value <= 38:
            raise ValueError("volume must be 0..38")
        return value + 1
    if command in {"bass", "treble"}:
        value = int(value)
        if not -12 <= value <= 12:
            raise ValueError(f"{command} must be -12..12")
        return value + 13
    if command == "balance":
        value = int(value)
        if not 0 <= value <= 20:
            raise ValueError("balance must be 0..20")
        return 1 + (value * 3)
    if command == "source":
        value = int(value)
        if not 1 <= value <= 8:
            raise ValueError("source must be 1..8")
        return value
    raise ValueError(f"unknown command: {command}")


def raw_to_volume(value: int) -> int:
    return max(0, min(38, value - 1))


def raw_to_tone(value: int) -> int:
    return max(-12, min(12, value - 13))


def raw_to_balance(value: int) -> int:
    if value >= 1 and (value - 1) % 3 == 0:
        display = (value - 1) // 3
        if 0 <= display <= 20:
            return display
    return 10


def extract_payloads(data: bytes) -> list[bytes]:
    payloads: list[bytes] = []
    pos = 0
    while True:
        start = data.find(MAGIC, pos)
        if start < 0 or len(data) < start + 20:
            break
        payload_len = struct.unpack("<I", data[start + 4 : start + 8])[0]
        total = 20 + payload_len
        if len(data) < start + total:
            break
        payload = data[start + 20 : start + total]
        checksum = struct.unpack("<H", data[start + 8 : start + 10])[0]
        if (sum(payload) & 0xFFFF) == checksum:
            payloads.append(payload)
        pos = start + total
    return payloads


def parse_config(payload: bytes) -> DaxConfig | None:
    if not payload.startswith(PREFIX + bytes([0x82, 0x15])):
        return None

    rest = payload[len(PREFIX) + 2 :]
    names: list[str] = []
    index = 0
    while index < len(rest):
        if rest[index : index + 2] == b"\xcc&" or rest[index : index + 3] == TERMINATOR:
            break
        length = rest[index]
        index += 1
        if length == 0 or index + length > len(rest):
            break
        names.append(rest[index : index + length].decode("latin1", "replace"))
        index += length

    return DaxConfig(
        device_name=names[0] if names else None,
        zones=names[1:9],
        sources=names[9:],
        raw_names=names,
    )


def parse_status_payload(payload: bytes) -> bytes | None:
    if not payload.startswith(PREFIX + bytes([0x82, 0x0C])):
        return None
    raw = payload[len(PREFIX) + 2 :]
    if raw.endswith(TERMINATOR):
        return raw[:-3]
    if raw.endswith(b"\xcc&"):
        return raw[:-2]
    return raw


def safe_name(items: list[str], index1: int, fallback: str) -> str:
    if 1 <= index1 <= len(items):
        return items[index1 - 1]
    return fallback


def parse_state(data: bytes) -> DaxState:
    config: DaxConfig | None = None
    status: bytes | None = None

    for payload in extract_payloads(data):
        config = config or parse_config(payload)
        status = status or parse_status_payload(payload)

    zones: list[ZoneStatus] = []
    if status and len(status) >= 56:
        groups = [list(status[index : index + 8]) for index in range(0, 56, 8)]
        zone_names = config.zones if config else []
        sources = config.sources if config else []
        for index in range(8):
            zone = index + 1
            source = groups[0][index]
            zones.append(
                ZoneStatus(
                    zone=zone,
                    name=safe_name(zone_names, zone, f"Zone {zone}"),
                    source=source,
                    source_name=safe_name(sources, source, f"Source {source}"),
                    volume=raw_to_volume(groups[1][index]),
                    treble=raw_to_tone(groups[2][index]),
                    bass=raw_to_tone(groups[3][index]),
                    balance=raw_to_balance(groups[4][index]),
                    power_on=groups[5][index] == 0x02,
                    muted=groups[6][index] == 0x02,
                    source_raw=groups[0][index],
                    volume_raw=groups[1][index],
                    treble_raw=groups[2][index],
                    bass_raw=groups[3][index],
                    balance_raw=groups[4][index],
                    power_raw=groups[5][index],
                    mute_raw=groups[6][index],
                )
            )

    return DaxState(
        device_name=config.device_name if config else None,
        config=config,
        zones=zones,
        raw_response_hex=data.hex(" "),
    )


class Dax88Client:
    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def query(self) -> DaxState:
        response = self._send_and_read(build_query_frame(), collect_until_timeout=True)
        state = parse_state(response)
        if not state.config and not state.zones:
            raise RuntimeError("No valid DAX88 config/status response found")
        return state

    def send(self, zone: int, command: str, value: int | bool) -> bytes:
        return self._send_and_read(build_command_frame(zone, command, value), collect_until_timeout=False)

    def _send_and_read(self, frame: bytes, collect_until_timeout: bool) -> bytes:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(frame)
            chunks: list[bytes] = []
            end = time.time() + self.timeout
            while time.time() < end:
                try:
                    data = sock.recv(8192)
                except TimeoutError:
                    break
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
                if not collect_until_timeout:
                    break
            return b"".join(chunks)
