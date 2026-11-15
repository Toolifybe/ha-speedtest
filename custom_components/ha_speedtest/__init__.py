"""Speedtest: internet speed (Cloudflare) with a simple card."""
from __future__ import annotations

import logging
import os

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (CARD_URL, CONF_INTERVAL, CONF_KIND, DEFAULT_INTERVAL, DEFAULT_KIND, DOMAIN,
                    KINDS, SIGNAL_UPDATE)
from .runner import Runner

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _runner(hass: HomeAssistant) -> Runner:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if e.state is ConfigEntryState.LOADED and getattr(e, "runtime_data", None)]
    if not entries:
        raise HomeAssistantError("Speedtest is not set up")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await _register_card(hass)
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_run)

    async def run_service(call: ServiceCall) -> ServiceResponse:
        runner = _runner(hass)
        kind = call.data.get(CONF_KIND, "full")
        if call.return_response:
            return await runner.run(kind)
        runner.start(kind)
        return None

    hass.services.async_register(DOMAIN, "run", run_service,
                                 schema=vol.Schema({vol.Optional(CONF_KIND): vol.In(KINDS)}),
                                 supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    opts = {**entry.data, **entry.options}
    runner = Runner(hass, int(opts.get(CONF_INTERVAL, DEFAULT_INTERVAL)), opts.get(CONF_KIND, DEFAULT_KIND))
    await runner.async_load()
    entry.runtime_data = runner
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await entry.runtime_data.async_unload()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _reload(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


# ─── Websocket for the card ──────────────────────────────────────────
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get", vol.Optional("days"): vol.All(int, vol.Range(1, 90))})
@callback
def ws_get(hass, connection, msg):
    try:
        connection.send_result(msg["id"], _runner(hass).snapshot(msg.get("days")))
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe", vol.Optional("days"): vol.All(int, vol.Range(1, 90))})
@callback
def ws_subscribe(hass, connection, msg):
    """Sends the snapshot now and again after every change (phase, live speed, new result)."""
    days = msg.get("days")

    @callback
    def send():
        try:
            connection.send_message(websocket_api.event_message(msg["id"], _runner(hass).snapshot(days)))
        except HomeAssistantError:
            pass

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATE, send)
    connection.send_result(msg["id"])
    send()


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/run", vol.Optional(CONF_KIND, default="full"): vol.In(KINDS)})
@callback
def ws_run(hass, connection, msg):
    try:
        _runner(hass).start(msg[CONF_KIND])
        connection.send_result(msg["id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "busy", str(err))


# ─── Card ────────────────────────────────────────────────────────────
async def _register_card(hass: HomeAssistant):
    """Serve the card and add it as a dashboard resource, with a version in the URL
    so browsers fetch the new file after an update."""
    from homeassistant.helpers.start import async_at_started

    path = os.path.join(os.path.dirname(__file__), "frontend", "ha-speedtest-card.js")
    try:
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, path, False)])
    except ImportError:
        hass.http.register_static_path(CARD_URL, path, False)
    stamp = int(await hass.async_add_executor_job(os.path.getmtime, path))
    url = f"{CARD_URL}?v={stamp}"

    async def add_resource(_hass):
        try:
            await _ensure_resource(hass, url)
        except Exception as err:  # never block the integration for this
            _LOGGER.warning("Could not add the dashboard resource (%s). "
                            "Add %s as a JavaScript module under Dashboards → Resources.", err, CARD_URL)

    async_at_started(hass, add_resource)


async def _ensure_resource(hass: HomeAssistant, url: str):
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        _LOGGER.info("Dashboards in YAML mode; add %s as a resource yourself", CARD_URL)
        return
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        current = str(item.get("url", ""))
        if current.split("?")[0] == CARD_URL:
            if current != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})
