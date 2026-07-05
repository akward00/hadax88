# DAX88 Debug GUI

Local browser control panel for debugging the Dayton Audio DAX88 TCP protocol without Home Assistant.

The browser UI talks to this Python server over HTTP. The Python server talks to the DAX88 over raw TCP port `8899`.

## Run

From this workspace:

```bash
python debug_gui/server.py
```

Then open:

```text
http://127.0.0.1:8898
```

If `python` is not on your PATH, use the Python bundled with Codex or any Python 3.10+ install.

## Use

1. Enter the DAX88 IP address and port `8899`, then select **Connect**.
2. Or enter a subnet such as `192.168.6.0/24` and select **Scan**.
3. Use the zone cards to test source, power, mute, volume, balance, bass, and treble.
4. Open **Debug data** to inspect parsed names, status bytes, and raw response hex.

This tool is intentionally dependency-free so it can be edited and run quickly while debugging the protocol.
