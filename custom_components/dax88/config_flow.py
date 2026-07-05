"""Config flow for the Dayton Audio DAX88 integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .client import Dax88Error
from .const import CONF_SUBNET, DEFAULT_PORT, DEFAULT_SCAN_TIMEOUT, DOMAIN
from .discovery import local_subnet_guess, scan_subnet, verify_host
from .protocol import DaxState


class Dax88ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a DAX88 config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._scan_results: dict[str, tuple[str, DaxState]] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Start with a manual-vs-scan menu."""

        return self.async_show_menu(
            step_id="user",
            menu_options=["manual", "scan"],
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure a DAX88 by host/IP."""

        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            try:
                state = await verify_host(host, port, timeout=2.0)
            except Dax88Error:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_create_entry(host, port, state)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Actively scan a subnet for verified DAX88 devices."""

        errors: dict[str, str] = {}
        subnet_default = local_subnet_guess() or "192.168.1.0/24"

        if user_input is not None:
            subnet = user_input[CONF_SUBNET].strip()
            try:
                found = await scan_subnet(subnet, DEFAULT_PORT, DEFAULT_SCAN_TIMEOUT)
            except ValueError:
                errors["base"] = "scan_too_large"
            except (Dax88Error, OSError):
                errors["base"] = "cannot_connect"
            else:
                if not found:
                    errors["base"] = "no_devices_found"
                elif len(found) == 1:
                    host, state = found[0]
                    return await self._async_create_entry(host, DEFAULT_PORT, state)
                else:
                    self._scan_results = {
                        host: (host, state)
                        for host, state in sorted(found, key=lambda item: item[0])
                    }
                    return await self.async_step_pick_device()

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SUBNET, default=subnet_default): str,
                }
            ),
            errors=errors,
        )

    async def async_step_pick_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick one device from active scan results."""

        if user_input is not None:
            host, state = self._scan_results[user_input[CONF_HOST]]
            return await self._async_create_entry(host, DEFAULT_PORT, state)

        options = [
            {"value": host, "label": f"{state.device_name or 'DAX88'} ({host})"}
            for host, (_host, state) in self._scan_results.items()
        ]
        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def _async_create_entry(self, host: str, port: int, state: DaxState) -> FlowResult:
        """Create a config entry from verified device metadata."""

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

        config = state.config
        return self.async_create_entry(
            title=state.device_name or f"DAX88 {host}",
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                "device_name": state.device_name,
                "zones": config.zones if config else [],
                "sources": config.sources if config else [],
            },
        )
