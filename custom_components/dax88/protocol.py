"""DAX88 TCP frame building, parsing, and state reduction."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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

STATUS_MIN_LEN = 58
STATUS_SOURCE_OFFSET = 0
STATUS_VOLUME_OFFSET = 8
STATUS_TREBLE_OFFSET = 16
STATUS_BASS_OFFSET = 24
STATUS_BALANCE_OFFSET = 32
STATUS_POWER_OFFSET = 42
STATUS_MUTE_OFFSET = 50

COMMAND_NAMES = {value: key for key, value in COMMANDS.items()}


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
    source_raw: int
    volume_raw: int
    treble_raw: int
    bass_raw: int
    balance_raw: int
    power_raw: int
    mute_raw: int


@dataclass(slots=True)
class DaxState:
    """Parsed device state."""

    device_name: str | None
    config: DaxConfig | None
    zones: list[ZoneStatus]


@dataclass(slots=True)
class DaxEvent:
    """A push command/event frame from the DAX88 socket."""

    command: str
    command_raw: int
    value: int | bool
    value_raw: int
    zones: list[int]


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


def extract_first_frame(buffer: bytearray) -> bytes | None:
    """Pop one valid wrapped frame from a mutable stream buffer."""

    start = bytes(buffer).find(MAGIC)
    if start < 0:
        if len(buffer) > len(MAGIC):
            del buffer[: -len(MAGIC)]
        return None
    if start > 0:
        del buffer[:start]
    if len(buffer) < 20:
        return None

    payload_len = struct.unpack("<I", buffer[4:8])[0]
    total = 20 + payload_len
    if len(buffer) < total:
        return None

    frame = bytes(buffer[:total])
    del buffer[:total]
    return frame


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


def parse_event_payload(payload: bytes) -> DaxEvent | None:
    """Parse a command echo or unsolicited zone event payload."""

    if not payload.startswith(PREFIX + bytes([0x82])):
        return None
    body = payload[len(PREFIX) + 1 :]
    if len(body) < 10:
        return None

    command_raw = body[0]
    if command_raw not in COMMAND_NAMES:
        return None
    value_raw = body[1]
    mask = body[2:10]
    zones = [index + 1 for index, value in enumerate(mask) if value == 0x01]
    if not zones:
        return None

    command = COMMAND_NAMES[command_raw]
    return DaxEvent(
        command=command,
        command_raw=command_raw,
        value=raw_to_display(command, value_raw),
        value_raw=value_raw,
        zones=zones,
    )


def parse_state(data: bytes) -> DaxState:
    """Parse query response bytes into a DAX88 state."""

    state = DaxState(device_name=None, config=None, zones=[])
    for payload in extract_payloads(data):
        state = apply_payload(state, payload) or state
    return state


def parse_zone_statuses(status: bytes, config: DaxConfig | None) -> list[ZoneStatus]:
    """Parse assumed status fields into eight zone states."""

    if len(status) < STATUS_MIN_LEN:
        return []

    source_status = status[STATUS_SOURCE_OFFSET : STATUS_SOURCE_OFFSET + 8]
    volume_status = status[STATUS_VOLUME_OFFSET : STATUS_VOLUME_OFFSET + 8]
    treble_status = status[STATUS_TREBLE_OFFSET : STATUS_TREBLE_OFFSET + 8]
    bass_status = status[STATUS_BASS_OFFSET : STATUS_BASS_OFFSET + 8]
    balance_status = status[STATUS_BALANCE_OFFSET : STATUS_BALANCE_OFFSET + 8]
    power_status = status[STATUS_POWER_OFFSET : STATUS_POWER_OFFSET + 8]
    mute_status = status[STATUS_MUTE_OFFSET : STATUS_MUTE_OFFSET + 8]
    zone_names = config.zones if config else []
    sources = config.sources if config else []

    out: list[ZoneStatus] = []
    for index in range(8):
        zone = index + 1
        source_raw = source_status[index]
        volume_raw = volume_status[index]
        treble_raw = treble_status[index]
        bass_raw = bass_status[index]
        balance_raw = balance_status[index]
        power_raw = power_status[index]
        mute_raw = mute_status[index]
        balance = raw_to_balance(balance_raw)
        out.append(
            ZoneStatus(
                zone=zone,
                name=zone_name(zone_names, zone),
                source=source_raw,
                source_name=source_name(sources, source_raw),
                volume=raw_to_volume(volume_raw),
                treble=raw_to_tone(treble_raw),
                bass=raw_to_tone(bass_raw),
                balance=balance if balance is not None else CENTER_BALANCE,
                power_on=power_raw == POWER_ON,
                muted=mute_raw == MUTE_ON,
                source_raw=source_raw,
                volume_raw=volume_raw,
                treble_raw=treble_raw,
                bass_raw=bass_raw,
                balance_raw=balance_raw,
                power_raw=power_raw,
                mute_raw=mute_raw,
            )
        )
    return out


def apply_payload(state: DaxState | None, payload: bytes) -> DaxState | None:
    """Apply one unwrapped payload to a state snapshot."""

    current = state or DaxState(device_name=None, config=None, zones=[])

    config = parse_config(payload)
    if config is not None:
        return apply_config(current, config)

    status = parse_status_payload(payload)
    if status is not None:
        zones = parse_zone_statuses(status, current.config)
        if zones:
            return DaxState(
                device_name=current.device_name or (current.config.device_name if current.config else None),
                config=current.config,
                zones=zones,
            )
        return None

    event = parse_event_payload(payload)
    if event is not None:
        return apply_event(current, event)

    return None


def apply_config(state: DaxState, config: DaxConfig) -> DaxState:
    """Apply discovered names without discarding current zone values."""

    zones = [_with_config_names(zone, config) for zone in state.zones]
    return DaxState(device_name=config.device_name, config=config, zones=zones)


def apply_event(state: DaxState, event: DaxEvent) -> DaxState | None:
    """Apply an echoed command or push event to affected zones."""

    if not state.zones:
        return None

    updated: list[ZoneStatus] = []
    changed = False
    for status in state.zones:
        if status.zone not in event.zones:
            updated.append(status)
            continue
        updated.append(_apply_event_to_zone(status, event, state.config))
        changed = True

    if not changed:
        return None
    return DaxState(device_name=state.device_name, config=state.config, zones=updated)


def raw_to_display(command: str, value: int) -> int | bool:
    """Convert a raw event value into the display value for its command."""

    if command == "power":
        return value == POWER_ON
    if command == "mute":
        return value == MUTE_ON
    if command == "volume":
        return raw_to_volume(value)
    if command in {"bass", "treble"}:
        return raw_to_tone(value)
    if command == "balance":
        return raw_to_balance(value) or CENTER_BALANCE
    return value


def command_id(command: str) -> int:
    """Return the protocol command id."""

    return COMMANDS[command]


def _with_config_names(status: ZoneStatus, config: DaxConfig) -> ZoneStatus:
    return replace(
        status,
        name=zone_name(config.zones, status.zone),
        source_name=source_name(config.sources, status.source),
    )


def _apply_event_to_zone(status: ZoneStatus, event: DaxEvent, config: DaxConfig | None) -> ZoneStatus:
    kwargs: dict[str, int | bool | str | None] = {}
    if event.command == "power":
        kwargs["power_raw"] = event.value_raw
        kwargs["power_on"] = bool(event.value)
    elif event.command == "mute":
        kwargs["mute_raw"] = event.value_raw
        kwargs["muted"] = bool(event.value)
    elif event.command == "volume":
        kwargs["volume_raw"] = event.value_raw
        kwargs["volume"] = int(event.value)
    elif event.command == "treble":
        kwargs["treble_raw"] = event.value_raw
        kwargs["treble"] = int(event.value)
    elif event.command == "bass":
        kwargs["bass_raw"] = event.value_raw
        kwargs["bass"] = int(event.value)
    elif event.command == "balance":
        kwargs["balance_raw"] = event.value_raw
        kwargs["balance"] = int(event.value)
    elif event.command == "source":
        source = int(event.value)
        kwargs["source_raw"] = event.value_raw
        kwargs["source"] = source
        kwargs["source_name"] = source_name(config.sources if config else [], source)
    return replace(status, **kwargs)
