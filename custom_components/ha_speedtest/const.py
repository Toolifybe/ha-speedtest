"""Constants for Speedtest."""
DOMAIN = "ha_speedtest"
VERSION = "1.2.0"

CONF_INTERVAL = "interval"      # hours between automatic tests, "0" = only on request
CONF_KIND = "kind"              # kind of the automatic test: "light" or "full"
INTERVALS = ["0", "1", "3", "6", "12", "24"]
KINDS = ["light", "full"]
DEFAULT_INTERVAL = "3"
DEFAULT_KIND = "light"

HISTORY_DAYS = 90               # results kept for the chart
SIGNAL_UPDATE = f"{DOMAIN}_update"
CARD_URL = f"/{DOMAIN}/ha-speedtest-card.js"
