"""Buttons: start a full or a light test."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .sensor import device_info


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RunButton(entry, "full"), RunButton(entry, "light")])


class RunButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, kind):
        self.entry, self.kind = entry, kind
        self._attr_unique_id = f"{entry.entry_id}_run_{kind}"
        self._attr_translation_key = f"run_{kind}"
        self._attr_icon = "mdi:speedometer" if kind == "full" else "mdi:speedometer-slow"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        self.entry.runtime_data.start(self.kind)
