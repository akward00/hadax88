"""Constants for the Dayton Audio DAX88 integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "dax88"

DEFAULT_PORT = 8899
DEFAULT_TIMEOUT = 2.0
DEFAULT_SCAN_TIMEOUT = 0.35
DEFAULT_SCAN_PREFIX = 24

CONF_SUBNET = "subnet"

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.NUMBER, Platform.BINARY_SENSOR]

MAGIC = bytes.fromhex("18 96 18 20")
PREFIX = b"MCU+PAS+"
TERMINATOR = bytes.fromhex("ff cc 26")

COMMAND_VOLUME = 0x01
COMMAND_TREBLE = 0x02
COMMAND_BASS = 0x03
COMMAND_BALANCE = 0x05
COMMAND_POWER = 0x08
COMMAND_SOURCE = 0x0D
COMMAND_MUTE = 0x0E

COMMANDS = {
    "volume": COMMAND_VOLUME,
    "treble": COMMAND_TREBLE,
    "bass": COMMAND_BASS,
    "balance": COMMAND_BALANCE,
    "power": COMMAND_POWER,
    "source": COMMAND_SOURCE,
    "mute": COMMAND_MUTE,
}

POWER_OFF = 0x01
POWER_ON = 0x02
MUTE_OFF = 0x01
MUTE_ON = 0x02

MAX_VOLUME = 38
MIN_TONE = -12
MAX_TONE = 12
MIN_BALANCE = 0
MAX_BALANCE = 20
CENTER_BALANCE = 10
