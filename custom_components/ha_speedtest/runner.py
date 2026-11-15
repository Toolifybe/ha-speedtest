"""Runs the tests, keeps the results and tells the entities and the card."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HISTORY_DAYS, SIGNAL_UPDATE
from .speedtest import SpeedtestError, run_test

_LOGGER = logging.getLogger(__name__)


class Runner:
    """One per config entry (there is only one)."""

    def __init__(self, hass: HomeAssistant, interval_h: int, kind: str):
        self.hass = hass
        self.interval_h = interval_h
        self.kind = kind
        self.store = Store(hass, 1, DOMAIN)
        self.history: list[dict] = []    # [{time, download, upload, ping, jitter, kind}], oldest first
        self.last: dict | None = None    # last result, with curve, isp, server
        self.phase = "idle"              # idle / ping / download / upload
        self.live: float | None = None   # Mbit/s right now, during the test
        self.live_curve: list = []       # [phase, seconds, Mbit/s] of the running test
        self.running_kind: str | None = None
        self.error = ""
        self._lock = asyncio.Lock()
        self._unsub = None
        self._task: asyncio.Task | None = None

    # ── lifetime ──────────────────────────────────────────────────────
    async def async_load(self):
        data = await self.store.async_load() or {}
        self.history = data.get("history", [])
        self.last = data.get("last")
        if self.interval_h:
            self._unsub = async_track_time_interval(
                self.hass, self._scheduled, timedelta(hours=self.interval_h), name="ha_speedtest")

    async def async_unload(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._task and not self._task.done():
            self._task.cancel()

    @callback
    def _scheduled(self, _now):
        if not self.running:
            self.start(self.kind)

    # ── running ───────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._lock.locked() or (self._task is not None and not self._task.done())

    @callback
    def start(self, kind: str) -> None:
        """Start a test in the background (button, schedule)."""
        if self.running:
            raise HomeAssistantError("A speed test is already running")

        async def background():
            try:
                await self._run(kind)
            except HomeAssistantError:
                pass  # already logged, and shown on the card
            except Exception as err:  # noqa: BLE001 - never fail silently in the background
                _LOGGER.exception("Speed test stopped unexpectedly")
                self.error = f"{type(err).__name__}: {err}"
                self._notify()

        self._task = self.hass.async_create_background_task(background(), "ha_speedtest test")

    async def run(self, kind: str) -> dict:
        """Run a test and wait for the result (action with response)."""
        if self.running:
            raise HomeAssistantError("A speed test is already running")
        return await self._run(kind)

    async def _run(self, kind: str) -> dict:
        async with self._lock:
            self.running_kind, self.error, self.live_curve = kind, "", []
            started = asyncio.get_running_loop().time()
            phase_start = [started]

            def progress(phase, mbit):
                now = asyncio.get_running_loop().time()
                if phase != self.phase:
                    phase_start[0] = now
                self.phase, self.live = phase, mbit
                if mbit is not None and phase in ("download", "upload"):
                    self.live_curve.append([phase, round(now - phase_start[0], 1), round(mbit, 1)])
                self._notify()

            try:
                result = await run_test(async_get_clientsession(self.hass), kind, progress)
            except SpeedtestError as err:
                self.error = str(err)
                _LOGGER.warning("Speed test failed: %s", err)
                raise HomeAssistantError(f"Speed test failed: {err}") from None
            finally:
                self.phase, self.live, self.running_kind = "idle", None, None
                self._notify()
            result["time"] = dt_util.utcnow().isoformat()
            self.last = result
            keep = ("time", "download", "upload", "ping", "jitter", "kind")
            self.history.append({k: result[k] for k in keep})
            cutoff = (dt_util.utcnow() - timedelta(days=HISTORY_DAYS)).isoformat()
            self.history = [h for h in self.history if h["time"] >= cutoff]
            await self.store.async_save({"history": self.history, "last": self.last})
            self.live_curve = []
            self._notify()
            _LOGGER.debug("Speed test done: %s down, %s up", result["download"], result["upload"])
            return result

    @callback
    def _notify(self):
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    # ── for the card ──────────────────────────────────────────────────
    def snapshot(self, days: int | None = None) -> dict:
        hist = self.history
        if days:
            cutoff = (dt_util.utcnow() - timedelta(days=days)).isoformat()
            hist = [h for h in hist if h["time"] >= cutoff]
        return {"history": hist, "last": self.last, "phase": self.phase, "live": self.live,
                "live_curve": self.live_curve, "running_kind": self.running_kind, "error": self.error,
                "interval": self.interval_h, "kind": self.kind}
