"""Sensors: download, upload, ping, jitter, last test, status."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity, SensorEntityDescription,
                                             SensorStateClass)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATE, VERSION


@dataclass(frozen=True, kw_only=True)
class SpeedSensorDescription(SensorEntityDescription):
    field: str


SENSORS = (
    SpeedSensorDescription(key="download", field="download", translation_key="download", icon="mdi:download",
                           native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
                           device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
                           suggested_display_precision=0),
    SpeedSensorDescription(key="upload", field="upload", translation_key="upload", icon="mdi:upload",
                           native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
                           device_class=SensorDeviceClass.DATA_RATE, state_class=SensorStateClass.MEASUREMENT,
                           suggested_display_precision=0),
    SpeedSensorDescription(key="ping", field="ping", translation_key="ping", icon="mdi:timer-outline",
                           native_unit_of_measurement=UnitOfTime.MILLISECONDS,
                           device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT,
                           suggested_display_precision=0),
    SpeedSensorDescription(key="jitter", field="jitter", translation_key="jitter", icon="mdi:pulse",
                           native_unit_of_measurement=UnitOfTime.MILLISECONDS,
                           device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT,
                           suggested_display_precision=1),
    SpeedSensorDescription(key="last_test", field="time", translation_key="last_test", icon="mdi:clock-check-outline",
                           device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC),
)


def device_info(entry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Speedtest", manufacturer="Cloudflare",
                      model="speed.cloudflare.com", sw_version=VERSION, entry_type=DeviceEntryType.SERVICE)


async def async_setup_entry(hass, entry, async_add_entities):
    runner = entry.runtime_data
    async_add_entities([ResultSensor(entry, runner, d) for d in SENSORS] + [StatusSensor(entry, runner)])


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, runner, key):
        self.runner = runner
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()


class ResultSensor(_Base):
    entity_description: SpeedSensorDescription

    def __init__(self, entry, runner, description):
        super().__init__(entry, runner, description.key)
        self.entity_description = description
        self._shown = None

    @callback
    def _update(self):
        # only write when the result changed, not on every live update
        if (self.runner.last or {}).get("time") != self._shown:
            self.async_write_ha_state()

    @property
    def native_value(self):
        last = self.runner.last
        if not last:
            return None
        self._shown = last.get("time")
        value = last.get(self.entity_description.field)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            return dt_util.parse_datetime(value) if value else None
        return value

    @property
    def extra_state_attributes(self):
        last = self.runner.last
        if self.entity_description.key == "download" and last:
            return {"kind": last.get("kind"), "isp": last.get("isp"), "server": last.get("server"),
                    "data_used_mb": last.get("bytes_mb")}
        return None


class StatusSensor(_Base):
    """idle / ping / download / upload; the live speed is only an attribute and is not recorded."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "ping", "download", "upload"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"live_mbit"})

    def __init__(self, entry, runner):
        super().__init__(entry, runner, "status")

    @property
    def native_value(self):
        return self.runner.phase

    @property
    def extra_state_attributes(self):
        return {"live_mbit": round(self.runner.live, 1) if self.runner.live is not None else None,
                "kind": self.runner.running_kind, "error": self.runner.error or None,
                "interval_hours": self.runner.interval_h, "automatic_kind": self.runner.kind}
