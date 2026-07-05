# Dayton Audio DAX88 Home Assistant integration

Custom Home Assistant integration for the Dayton Audio DAX88 matrix amplifier using the reverse-engineered Matrio TCP protocol on port `8899`.

This integration does not use RS-232 and does not use LinkPlay/UPnP for matrix control. It verifies the amplifier by sending the DAX88/Matrio query and parsing the returned config/status frames.

## Features

- Config flow setup from the Home Assistant UI.
- Manual host/IP entry.
- Optional active subnet scan for TCP `8899`.
- One `media_player` entity per DAX88 zone.
- Zone names and source names loaded from the amplifier.
- Power, mute, volume, source selection, and periodic status polling.
- Number entities for each zone:
  - Bass, `-12..12`
  - Treble, `-12..12`
  - Balance, `0..20`, center `10`

## Install

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

## Protocol mappings

- Power: off `0x01`, on `0x02`
- Mute: unmuted `0x01`, muted `0x02`
- Volume: Home Assistant `0.0..1.0` maps to DAX88 display `0..38`, then raw `display + 1`
- Bass and treble: display `-12..12`, raw `display + 13`
- Balance: display `0..20`, raw `1 + display * 3`
- Source: raw source number, `1..8`

## Notes

The integration polls status every 12 seconds using a Home Assistant `DataUpdateCoordinator`. After a command is sent, it immediately requests a refresh so the UI follows the amplifier state closely.
