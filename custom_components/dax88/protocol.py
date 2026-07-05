"""DAX88 TCP frame building and parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .const import (
    CENTER_BALANCE,
    COMMANDS,
    MAGIC,
    MAX_BALANCE,
    MAX_TONE,
    MAX_VOLUME,
    MIN_BALANCE,
    MIN_TONE,
    MUTE_OFF,
    MUTE_ON,
    POWER_OFF,
    POWER_ON,
    PREFIX,
    TERMINATOR,
)


@dataclass(slots=True)
class DaxConfig:
    """Names discovered from the DAX88 config response."""

    device_name: str | None
    zones: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    raw_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ZoneStatus:
    """Current state for one DAX88 zone."""

    zone: int
    name: str
    source: int
    source_name: str
    volume: int
    treble: int
    bass: int
    balance: int | None
    power_on: bool
    muted: bool
    power_raw: int
    mute_raw: int


@dataclass(slots=True)
class DaxState:
    """Parsed device state."""

    device_name: str | None
    config: DaxConfig | None
    zones: list[ZoneStatus]


def wrap_payload(payload: bytes) -> bytes:
    """Wrap a DAX88 payload in the observed Matrio TCP frame."""

    checksum = sum(payload) & 0xFFFF
    return MAGIC + struct.pack("<I", len(payload)) + struct.pack("<H", checksum) + (b"\x00" * 10) + payload


def build_command_frame(zone: int, command: int, value: int) -> bytes:
    """Build a command frame for one zone."""

    if not 1 <= zone <= 8:
        raise ValueError("zone must be 1..8")
    if not 0 <= command <= 255 or not 0 <= value <= 255:
        raise ValueError("command and value must be bytes")

    zone_bytes = bytearray([0x02] * 8)
    zone_bytes[zone - 1] = 0x01
    payload = PREFIX + bytes([0x82, command, value]) + bytes(zone_bytes) + TERMINATOR
    return wrap_payload(payload)


def build_query_frame() -> bytes:
    """Build the startup query used by Matrio Control."""

    return wrap_payload(PREFIX + bytes.fromhex("82 0a ff ff ff 89 26"))


def display_to_raw(command: str, value: int | bool) -> int:
    """Convert Home Assistant/display values to protocol bytes."""

    if command == "power":
        return POWER_ON if bool(value) else POWER_OFF
    if command == "mute":
        return MUTE_ON if bool(value) else MUTE_OFF
    if command == "volume":
        if not 0 <= int(value) <= MAX_VOLUME:
            raise ValueError("volume must be 0..38")
        return int(value) + 1
    if command in {"bass", "treble"}:
        if not MIN_TONE <= int(value) <= MAX_TONE:
            raise ValueError(f"{command} must be -12..12")
        return int(value) + 13
    if command == "balance":
        if not MIN_BALANCE <= int(value) <= MAX_BALANCE:
            raise ValueError("balance must be 0..20")
        return 1 + (int(value) * 3)
    if command == "source":
        if not 1 <= int(value) <= 8:
            raise ValueError("source must be 1..8")
        return int(value)
    raise ValueError(f"unknown command {command}")


def raw_to_volume(value: int) -> int:
    """Convert protocol volume to displayed volume."""

    return max(0, min(MAX_VOLUME, value - 1))


def raw_to_tone(value: int) -> int:
    """Convert protocol bass/treble to displayed tone offset."""

    return max(MIN_TONE, min(MAX_TONE, value - 13))


def raw_to_balance(value: int) -> int | None:
    """Convert protocol balance to displayed 0..20 balance."""

    if value >= 1 and (value - 1) % 3 == 0:
        display = (value - 1) // 3
        if MIN_BALANCE <= display <= MAX_BALANCE:
            return display
    return None


def source_name(sources: list[str], source: int) -> str:
    """Return a configured source name or a fallback label."""

    if 1 <= source <= len(sources):
        return sources[source - 1]
    return f"Source {source}"


def zone_name(zones: list[str], zone: int) -> str:
    """Return a configured zone name or a fallback label."""

    if 1 <= zone <= len(zones):
        return zones[zone - 1]
    return f"Zone {zone}"


def extract_payloads(data: bytes) -> list[bytes]:
    """Extract valid payloads from a TCP byte stream."""

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
    """Parse a config/name payload."""

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
    """Return the stripped 0x0c status block."""

    if not payload.startswith(PREFIX + bytes([0x82, 0x0C])):
        return None
    raw = payload[len(PREFIX) + 2 :]
    if raw.endswith(TERMINATOR):
        return raw[:-3]
    if raw.endswith(b"\xcc&"):
        return raw[:-2]
    return raw


def parse_state(data: bytes) -> DaxState:
    """Parse query response bytes into a DAX88 state."""

    config: DaxConfig | None = None
    status: bytes | None = None

    for payload in extract_payloads(data):
        config = config or parse_config(payload)
        status = status or parse_status_payload(payload)

    zones = parse_zone_statuses(status, config) if status else []
    return DaxState(
        device_name=config.device_name if config else None,
        config=config,
        zones=zones,
    )


def parse_zone_statuses(status: bytes, config: DaxConfig | None) -> list[ZoneStatus]:
    """Parse the first 56 status bytes into eight zone states."""

    if len(status) < 56:
        return []

    groups = [list(status[index : index + 8]) for index in range(0, 56, 8)]
    zone_names = config.zones if config else []
    sources = config.sources if config else []

    out: list[ZoneStatus] = []
    for index in range(8):
        zone = index + 1
        source = groups[0][index]
        power_raw = groups[5][index]
        mute_raw = groups[6][index]
        balance = raw_to_balance(groups[4][index])
        out.append(
            ZoneStatus(
                zone=zone,
                name=zone_name(zone_names, zone),
                source=source,
                source_name=source_name(sources, source),
                volume=raw_to_volume(groups[1][index]),
                treble=raw_to_tone(groups[2][index]),
                bass=raw_to_tone(groups[3][index]),
                balance=balance if balance is not None else CENTER_BALANCE,
                power_on=power_raw == POWER_ON,
                muted=mute_raw == MUTE_ON,
                power_raw=power_raw,
                mute_raw=mute_raw,
            )
        )
    return out


def command_id(command: str) -> int:
    """Return the protocol command id."""

    return COMMANDS[command]
