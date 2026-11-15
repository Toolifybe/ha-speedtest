# ⚡ HA Speedtest for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)

Measure your internet speed with Cloudflare and see it at a glance: a live gauge, four tiles and a chart of the last days.

---

## ✨ Features

- 🚀 **Cloudflare speed test** — download, upload, ping and jitter via speed.cloudflare.com, no extra packages or programs
- 🎯 **Live gauge** — follows the test as it runs (ping → download → upload)
- 📈 **Chart** — the speed curve of the last test, or every result of the last days (hover for details)
- 🪶 **Light or full test** — light uses ±35 MB and is enough to see whether everything is normal; full fills the line for 10 s each way to find the real top speed
- ⏱️ **Automatic tests** — every 1, 3, 6, 12 or 24 hours, or only on request
- 🔘 **Run test button** — on the card, and as button entities for automations
- 📊 **Sensors** — Download, Upload (Mbit/s), Ping, Jitter (ms), Last test and Status, with long-term statistics
- 🧩 **Action** `ha_speedtest.run` — optionally waits and returns the result (`response_variable`)
- 🎨 **Home Assistant look** — follows your theme, light and dark
- 🗂️ **History kept for 90 days** — independent of the recorder
- ⚙️ **Visual editor** — title, days in the chart, gauge maximum, start view

---

## 📦 Installation via HACS

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Toolifybe/ha-speedtest` as **Integration**
2. Search for **HA Speedtest** and download it
3. Restart Home Assistant
4. **Settings → Devices & services → Add integration → HA Speedtest**
5. Choose how often to test automatically and which kind of test

The card is added as a dashboard resource automatically. Add it to a dashboard:

```yaml
type: custom:ha-speedtest-card
```

---

## ⚙️ Card options

| Option  | Default     | Description                                            |
|---------|-------------|--------------------------------------------------------|
| `title` | `Speedtest` | Title at the top                                       |
| `days`  | `7`         | Days shown in the chart (1–90)                         |
| `max`   | automatic   | Maximum of the gauge in Mbit/s                         |
| `view`  | `gauge`     | `gauge` or `chart` when the card opens                 |

## 🔧 Integration options

| Option              | Choices                                       |
|---------------------|-----------------------------------------------|
| Automatic test      | Only on request, every 1 / 3 / 6 / 12 hours, once a day |
| Kind of automatic test | Light (±35 MB) or Full (10 s each way)     |

The button on the card always runs a **full** test.

---

## 🧩 Entities and action

| Entity | |
|---|---|
| `sensor.speedtest_download` / `_upload` | Mbit/s; attributes `kind`, `isp`, `server`, `data_used_mb` |
| `sensor.speedtest_ping` / `_jitter` | ms |
| `sensor.speedtest_last_test` | time of the last result |
| `sensor.speedtest_status` | idle, ping, download, upload (live speed as attribute) |
| `button.speedtest_run_test` / `_light_test` | start a full / light test |

(Entity ids follow your Home Assistant language, e.g. `button.speedtest_nu_testen` in Dutch.)

```yaml
action: ha_speedtest.run
data:
  kind: light        # or full (default)
response_variable: result   # optional: wait for the result
```

---

## ❓ Why does a speed test use so much data?

A ping only measures reaction time. To measure speed, the line has to be filled for a moment: the test downloads and uploads filler data (zeros) that is counted and thrown away right away — nothing is stored. At 500 Mbit/s, 10 seconds is about 600 MB. That is why automatic tests are **light** by default.

The test runs from the machine Home Assistant runs on. On a slow machine, very fast lines (close to 1 Gbit/s) can read a bit low.

---

## 📁 Structure

```
custom_components/ha_speedtest/
├── __init__.py          setup, websocket for the card, action, dashboard resource
├── config_flow.py       setup and options from the UI
├── runner.py            runs tests, schedule, history (.storage/ha_speedtest)
├── speedtest.py         the Cloudflare measurement
├── sensor.py / button.py
├── services.yaml, strings.json, translations/ (en, nl)
└── frontend/ha-speedtest-card.js
```

---

## 📝 Changelog

### v1.0.0
- First version: Cloudflare speed test (light and full), sensors, buttons, action with response, automatic schedule, 90 days history, card with live gauge, tiles and chart (last test / last days), visual editor, English and Dutch.
