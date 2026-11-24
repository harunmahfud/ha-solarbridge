"""Constants for SolarBridge."""

from pathlib import Path

DOMAIN = "solarbridge"
PLATFORMS = ["sensor"]

CONF_PROFILE = "profile"
CONF_UNIT_ID = "unit_id"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_POLL_INTERVAL = 10
MIN_POLL_INTERVAL = 1
SLOW_POLL_INTERVAL = 60
FAILURE_THRESHOLD = 3
MAX_READ_REGISTERS = 125

PROFILE_DIR = Path(__file__).parent / "profiles" / "v1"
