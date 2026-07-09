# Dayton Audio DAX88 Home Assistant integration

Custom Home Assistant integration for the Dayton Audio DAX88 matrix amplifier using the reverse-engineered Matrio TCP protocol on port `8899`.

This integration does not use RS-232 and does not use LinkPlay/UPnP for matrix control. It verifies the amplifier by sending the DAX88/Matrio query and parsing the returned config/status frames.

## Features

- Config flow setup from the Home Assistant UI.
- Manual host/IP entry.
- Optional active subnet scan for TCP `8899`.
- HACS-ready custom repository structure.
- Push-based runtime connection using one persistent TCP socket.
- One `media_player` entity per DAX88 zone.
- One connectivity `binary_sensor` for the persistent DAX88 socket.
- Home Assistant diagnostics download with parsed state and recent raw DAX88 payloads.
- Zone names and source names loaded from the amplifier.
- Power, mute, volume, source selection, bass, treble, and balance.
- Number entities for each zone:
  - Bass, `-12..12`
  - Treble, `-12..12`
  - Balance, `0..20`, center `10`

## Install

### HACS custom repository

1. In HACS, open **Integrations**.
2. Select the three-dot menu, then **Custom repositories**.
3. Add `https://github.com/akward00/hadax88` as an **Integration** repository.
4. Install **Dayton Audio DAX88**.
5. Restart Home Assistant.

### Manual install

Copy this directory:

```text
custom_components/dax88
```

into your Home Assistant config directory as:

```text
/config/custom_components/dax88
```

Restart Home Assistant.

## Configure

1. Go to **Settings > Devices & services**.
2. Select **Add integration**.
3. Search for **Dayton Audio DAX88**.
4. Choose either:
   - **Enter host manually** and provide the DAX88 IP address.
   - **Scan a subnet** and provide a subnet such as `192.168.6.0/24`.

The integration connects to TCP port `8899`, sends the Matrio query, and uses the response to discover the device name, zone names, source names, and current status.

## Status

Core controls have been tested on a Dayton Audio DAX88:

- Power
- Mute
- Volume
- Bass
- Treble
- Balance
- Zone/source name discovery
- Push updates from the persistent socket

The integration also exposes a connection binary sensor and Home Assistant diagnostics. PA announcement, DT/keypad status, and Matrio group management are not exposed yet.

## Runtime model

After setup, the integration keeps one TCP socket open to the DAX88. State updates are driven by frames received on that socket:

- Config/name frames refresh the device, zone, and source labels.
- Full status frames refresh all known zone values.
- Echoed command frames and unsolicited event frames patch affected zones immediately.
- If the socket drops, the client reconnects and sends the startup query again.

This matches the current debugging finding that the device appears to hold one active socket per remote IP, and that Matrio receives immediate state changes on the main socket.

## Protocol mappings

TCP status frame `0x82 0x0c` currently maps as follows, using data offsets after `MCU+PAS+ 82 0c` and before the trailer:

- `0..7`: source raw, zones 1..8
- `8..15`: volume raw, display `raw - 1`
- `16..23`: treble raw, display `raw - 13`
- `24..31`: bass raw, display `raw - 13`
- `32..39`: balance raw, display `(raw - 1) / 3` when valid
- `40..41`: unknown
- `42..49`: power raw, `0x01` off and `0x02` on
- `50..57`: mute raw, `0x01` unmuted and `0x02` muted
- `58..61`: unknown tail

Command/event frames use a command byte, value byte, and eight zone mask bytes. Mask byte `0x01` means the event applies to that zone; `0x02` means it does not.

## Known open protocol questions

The RS-232 manual exposes PA, DT, and keypad status values that have not yet been confidently identified in the TCP status block. PA is probably related to the announcement input. DT may be a do-not-disturb style feature, but that is still an assumption.
