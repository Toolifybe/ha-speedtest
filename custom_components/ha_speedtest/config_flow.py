"""Set up and change Speedtest from the UI."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import CONF_INTERVAL, CONF_KIND, DEFAULT_INTERVAL, DEFAULT_KIND, DOMAIN, INTERVALS, KINDS


def _schema(cur: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_INTERVAL, default=cur.get(CONF_INTERVAL, DEFAULT_INTERVAL)): SelectSelector(
            SelectSelectorConfig(options=INTERVALS, translation_key="interval", mode=SelectSelectorMode.DROPDOWN)),
        vol.Required(CONF_KIND, default=cur.get(CONF_KIND, DEFAULT_KIND)): SelectSelector(
            SelectSelectorConfig(options=KINDS, translation_key="kind", mode=SelectSelectorMode.LIST)),
    })


class SpeedtestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Speedtest", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SpeedtestOptionsFlow()


class SpeedtestOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(cur))
