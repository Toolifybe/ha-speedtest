"""Speed measurement against speed.cloudflare.com (no extra packages, only aiohttp).

How it works:
- ping: 20 tiny requests; the time Cloudflare itself spent (Server-Timing) is subtracted.
  ping = median, jitter = average difference between consecutive pings.
- download / upload: a few parallel connections move filler data (zeros) that is
  counted and thrown away right away. Nothing is written to disk.

Two kinds of test, both measured over a fixed time with 6 connections:
- "light": 3 s download, 4 s upload. About a third of the data of a full test.
- "full": 10 s per direction, as much as the line can carry (like speedtest.net).

Why on time and not on a fixed amount of data: Cloudflare needs 0.1-0.4 s per request
before data flows, and one upload connection only gets a fraction of the line. Small
fixed amounts therefore read far too low on fast lines. Upload requests start small
(256 kB) and grow while they are quick; at the end of the time the test stops hard,
requests that hang at Cloudflare are dropped and do not count.
"""
from __future__ import annotations

import asyncio
import re
import statistics
import time
from collections.abc import Callable

import aiohttp

BASE = "https://speed.cloudflare.com"
HEADERS = {"User-Agent": "ha-speedtest (Home Assistant integration)", "Referer": BASE + "/"}

PROFILES = {
    "light": {"streams": 6, "down_seconds": 3.0, "up_seconds": 4.0, "warmup": 0.75},
    "full": {"streams": 6, "down_seconds": 10.0, "up_seconds": 10.0, "warmup": 1.0},
}
DOWN_CHUNK = 25_000_000          # bytes per download request (read as a stream, stopped at the end)
UP_START, UP_MIN, UP_MAX = 256_000, 128_000, 8_000_000   # upload request size adapts per connection
GRACE = 3.0                      # wait this long after the end for running uploads, then drop them
PINGS = 20
_DUR = re.compile(r"dur=([0-9.]+)")


class SpeedtestError(Exception):
    """The test could not be done (no internet, Cloudflare refused, ...)."""


def _server_ms(resp) -> float:
    """Time Cloudflare spent itself (largest of the Server-Timing durations)."""
    durs = [float(x) for x in _DUR.findall(resp.headers.get("Server-Timing", ""))]
    return max(durs, default=0.0)


class _Counter:
    """Counts bytes and keeps samples for the live speed and the warm-up cut."""

    def __init__(self, report: Callable[[float], None] | None):
        self.bytes = 0
        self.t0 = time.monotonic()
        self.samples: list[tuple[float, int]] = [(self.t0, 0)]
        self._report = report
        self._last_report = self.t0
        self.curve: list[list[float]] = []   # [seconds, Mbit/s] every half second, for the chart

    def add(self, n: int):
        self.bytes += n
        now = time.monotonic()
        if now - self.samples[-1][0] >= 0.2:
            self.samples.append((now, self.bytes))
        if now - self.t0 >= (len(self.curve) + 1) * 0.5:
            self.curve.append([round(now - self.t0, 1), round(self.live(1.0), 1)])
        if self._report and now - self._last_report >= 1.0:
            self._last_report = now
            self._report(self.live())

    def live(self, window: float = 2.0) -> float:
        """Mbit/s over the last few seconds."""
        now = time.monotonic()
        old = next(((t, b) for t, b in self.samples if now - t <= window), self.samples[0])
        dt = now - old[0]
        return (self.bytes - old[1]) * 8 / dt / 1e6 if dt > 0.05 else 0.0

    def result(self, warmup: float, end: float) -> float:
        """Mbit/s from the end of the warm-up until end."""
        start_t, start_b = self.t0, 0
        if warmup and end - self.t0 > warmup * 3:
            start_t, start_b = next(((t, b) for t, b in self.samples if t - self.t0 >= warmup), (self.t0, 0))
        dt = end - start_t
        return (self.bytes - start_b) * 8 / dt / 1e6 if dt > 0 else 0.0


async def _meta(session: aiohttp.ClientSession) -> dict:
    """Provider and the Cloudflare location that was used (no IP address is kept)."""
    try:
        async with session.get(BASE + "/meta", headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as r:
            d = await r.json(content_type=None)
        colo = d.get("colo") if isinstance(d.get("colo"), dict) else {}
        place = f"{colo.get('city', '')} ({colo.get('iata', '')})" if colo.get("iata") else ""
        return {"isp": str(d.get("asOrganization") or ""), "server": place}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return {"isp": "", "server": ""}


async def _ping(session: aiohttp.ClientSession) -> tuple[float, float]:
    times = []
    for i in range(PINGS):
        t = time.perf_counter()
        try:
            async with session.get(BASE + "/__down?bytes=0", headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                r.raise_for_status()
                await r.read()
                ms = (time.perf_counter() - t) * 1000 - _server_ms(r)
        except asyncio.TimeoutError:
            continue  # a lost ping is skipped
        if i:  # the first one also sets up the connection
            times.append(max(ms, 0.1))
    if len(times) < 5:
        raise asyncio.TimeoutError
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:]))
    return statistics.median(times), jitter


async def _direction(session, upload: bool, prof: dict, report) -> tuple[float, list, int]:
    """Returns (Mbit/s, curve, bytes moved)."""
    counter = _Counter(report)
    secs = prof["up_seconds" if upload else "down_seconds"]
    deadline = counter.t0 + secs
    errors: list[Exception] = []
    last_done = [counter.t0]
    sent = [0]

    async def down_once():
        async with session.get(f"{BASE}/__down?bytes={DOWN_CHUNK}", headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=secs + 15, sock_read=10)) as r:
            r.raise_for_status()
            async for chunk in r.content.iter_chunked(65536):
                if time.monotonic() >= deadline:
                    return  # leaving the block closes the connection
                counter.add(len(chunk))

    async def up_once(n):
        sent[0] += n
        async with session.post(BASE + "/__up", data=bytes(n), headers=HEADERS,
                                timeout=aiohttp.ClientTimeout(total=secs + 15)) as r:
            r.raise_for_status()
            await r.read()
        if time.monotonic() <= deadline + GRACE:
            counter.add(n)  # counted when Cloudflare confirms it
            last_done[0] = time.monotonic()

    async def worker():
        size = UP_START
        while time.monotonic() < deadline and len(errors) < 12:
            t = time.monotonic()
            try:
                await (up_once(size) if upload else down_once())
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                errors.append(err)  # one failed request (Cloudflare sometimes answers 502): go on
                continue
            if upload:
                took = time.monotonic() - t
                if took < 1.0:
                    size = min(size * 2, UP_MAX)
                elif took > 3.0:
                    size = max(size // 2, UP_MIN)

    tasks = [asyncio.ensure_future(worker()) for _ in range(prof["streams"])]
    done, pending = await asyncio.wait(tasks, timeout=secs + GRACE)
    for task in pending:      # requests hanging at Cloudflare: drop them
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if task.exception():
            raise task.exception()
    if not counter.bytes:
        raise errors[0] if errors else asyncio.TimeoutError()
    if upload:
        # up to the last confirmed request: time spent on dropped requests does not count
        dt = last_done[0] - counter.t0
        speed = counter.bytes * 8 / dt / 1e6 if dt > 0 else 0.0
        return speed, counter.curve, sent[0]
    return counter.result(prof["warmup"], min(time.monotonic(), deadline)), counter.curve, counter.bytes


async def run_test(session: aiohttp.ClientSession, kind: str = "light",
                   progress: Callable[[str, float | None], None] | None = None) -> dict:
    """Run a full measurement. progress(phase, live_mbit) is called along the way.

    Returns {"download", "upload" (Mbit/s), "ping", "jitter" (ms), "kind", "isp", "server",
    "bytes_mb" (data used, rough), "curve" (speed every half second, per direction)}.
    """
    prof = PROFILES.get(kind, PROFILES["light"])

    def step(phase):
        if progress:
            progress(phase, None)
        return (lambda v: progress(phase, v)) if progress else None

    try:
        step("ping")
        meta = await _meta(session)
        ping, jitter = await _ping(session)
        down, down_curve, down_bytes = await _direction(session, False, prof, step("download"))
        up, up_curve, up_bytes = await _direction(session, True, prof, step("upload"))
    except aiohttp.ClientResponseError as err:
        raise SpeedtestError(f"Cloudflare answered {err.status}") from None
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise SpeedtestError(f"no connection with speed.cloudflare.com ({type(err).__name__})") from None
    used = down_bytes + up_bytes
    return {"download": round(down, 1), "upload": round(up, 1), "ping": round(ping, 1),
            "jitter": round(jitter, 1), "kind": kind, **meta, "bytes_mb": round(used / 1e6),
            "curve": {"download": down_curve, "upload": up_curve}}
