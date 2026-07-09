# DAX88 Home Assistant custom integration

Home Assistant custom integration for the Dayton Audio DAX88 matrix amplifier using the reverse-engineered Matrio TCP protocol on port `8899`.

The integration lives in:

```text
custom_components/dax88
```

It is structured for manual custom-component installs and HACS custom repository installs.

Current release status: core DAX88 zone controls are tested, including power, mute, volume, bass, treble, balance, zone/source names, push updates, connectivity status, and diagnostics.

## HACS install

1. In HACS, open **Integrations**.
2. Select the three-dot menu, then **Custom repositories**.
3. Add this repository URL:

```text
https://github.com/akward00/hadax88
```

4. Set the category to **Integration**.
5. Install **Dayton Audio DAX88**.
6. Restart Home Assistant.
7. Add **Dayton Audio DAX88** from **Settings > Devices & services**.

## Manual install

Copy this directory:

```text
custom_components/dax88
```

into Home Assistant as:

```text
/config/custom_components/dax88
```

Then restart Home Assistant and add **Dayton Audio DAX88** from **Settings > Devices & services**.

See [custom_components/dax88/README.md](custom_components/dax88/README.md) for configuration notes, entity details, and protocol mappings.
