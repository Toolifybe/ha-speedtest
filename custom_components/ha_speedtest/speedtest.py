"""Speed measurement against speed.cloudflare.com (no extra packages, only aiohttp).

How it works:
- ping: 20 tiny requests; the time Cloudflare itself spent (Server-Timing) is subtracted.
  ping = median, jitter = average difference between consecutive pings.
- download / upload: a few parallel connections move filler data (zeros) that is
  counted and thrown away right away. Nothing is written to disk.

Two kinds of test:
- "light": a fixed, small amount of data (25 MB down, 10 MB up). Cheap, good to see
  whether the line behaves as usual. On very fast lines it reads somewhat low, because
  the test is over before the connections reach full speed.
- "full": 10 seconds per direction, as much as the line can carry (like speedtest.net).
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
    "light": {"streams": 4, "down_total": 25_000_000, "up_total": 10_000_000, "seconds": None, "warmup": 0.0},
    # light: the first 25 % of the data is the connections starting up and is not counted
    "full": {"streams": 6, "down_total": None, "up_total": None, "seconds": 10.0, "warmup": 1.0},
}
DOWN_CHUNK = 25_000_000          # bytes per download request (read as a stream, can stop early)
UP_START, UP_MAX = 1_000_000, 8_000_000   # upload requests grow while they are fast
SAFETY = 30.0                    # never run a direction longer than this
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

    def result(self, warmup: float) -> float:
        end = time.monotonic()
        start_t, start_b = self.t0, 0
        if not warmup and len(self.samples) > 4:   # amount-based test: skip the start-up quarter
            start_t, start_b = next(((t, b) for t, b in self.samples if b >= self.bytes * 0.25), (self.t0, 0))
        elif warmup and end - self.t0 > warmup * 3:
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


async def _direction(session, upload: bool, prof: dict, report) -> tuple[float, list]:
    counter = _Counter(report)
    total = prof["up_total" if upload else "down_total"]
    deadline = counter.t0 + (prof["seconds"] or SAFETY)
    left = [total]

    def take(want: int) -> int:
        if total is None:
            return want
        n = min(want, left[0])
        left[0] -= n
        return n

    errors: list[Exception] = []

    async def down_once(n):
        async with session.get(f"{BASE}/__down?bytes={n}", headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=SAFETY + 10, sock_read=15)) as r:
            r.raise_for_status()
            async for chunk in r.content.iter_chunked(65536):
                counter.add(len(chunk))
                if time.monotonic() >= deadline:
                    return  # leaving the block closes the connection

    async def up_once(n):
        async with session.post(BASE + "/__up", data=bytes(n), headers=HEADERS,
                                timeout=aiohttp.ClientTimeout(total=SAFETY + 10)) as r:
            r.raise_for_status()
            await r.read()
        counter.add(n)  # counted when Cloudflare confirms it

    async def worker():
        size = UP_START if upload else DOWN_CHUNK
        if total is not None and not upload:
            size = max(total // prof["streams"], 1)
        while time.monotonic() < deadline and len(errors) < 6:
            n = take(size)
            if n <= 0:
                return
            t = time.monotonic()
            try:
                await (up_once if upload else down_once)(n)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                errors.append(err)  # one failed request (Cloudflare sometimes answers 502): go on
                continue
            if upload and time.monotonic() - t < 1.0:
                size = min(size * 2, UP_MAX)

    await asyncio.gather(*(worker() for _ in range(prof["streams"])))
    if not counter.bytes and errors:
        raise errors[0]
    return counter.result(prof["warmup"]), counter.curve


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
        down, down_curve = await _direction(session, False, prof, step("download"))
        up, up_curve = await _direction(session, True, prof, step("upload"))
    except aiohttp.ClientResponseError as err:
        raise SpeedtestError(f"Cloudflare answered {err.status}") from None
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise SpeedtestError(f"no connection with speed.cloudflare.com ({type(err).__name__})") from None
    secs = prof["seconds"]
    used = (prof["down_total"] or down * secs / 8 * 1e6) + (prof["up_total"] or up * secs / 8 * 1e6)
    return {"download": round(down, 1), "upload": round(up, 1), "ping": round(ping, 1),
            "jitter": round(jitter, 1), "kind": kind, **meta, "bytes_mb": round(used / 1e6),
            "curve": {"download": down_curve, "upload": up_curve}}
