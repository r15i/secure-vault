"""Single source of truth for host-side configuration.

Every host tool (test client, benchmark harness, analysis scripts) reads its
configuration from here. Nothing else hardcodes a device address.

Resolution order, first match wins:
  1. explicit argument  (--ip on the command line)
  2. ESP32_IP environment variable
  3. DEFAULT_DEVICE_IP below

The firmware's own configuration lives in src/config.h (git-ignored); the two
sides are independent because the device gets its address via DHCP.
"""

import os
from pathlib import Path

# Device address as of the last recorded session. The device uses DHCP, so this
# is a convenience default, not a guarantee — it reports its actual address over
# serial at boot and via GET /api/status.
DEFAULT_DEVICE_IP = "127.0.0.1:5000"

DEFAULT_SERIAL_PORT = "/dev/ttyACM1"
SERIAL_BAUD = 115200

# Repository paths, resolved relative to this file so any checkout location works.
PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR.parent / "results"

# Default run sizes. Overridable per invocation.
DEFAULT_ITERATIONS = 150
DEFAULT_DELAY_S = 0.01


def device_ip(override: str | None = None) -> str:
    """Resolve the device address."""
    return override or os.environ.get("ESP32_IP") or DEFAULT_DEVICE_IP


def base_url(override: str | None = None) -> str:
    """Base URL of the device API, without a trailing slash."""
    return f"http://{device_ip(override)}"


def serial_port(override: str | None = None) -> str:
    return override or os.environ.get("ESP32_PORT") or DEFAULT_SERIAL_PORT


def add_common_args(parser) -> None:
    """Attach the shared configuration flags to an argparse parser."""
    parser.add_argument(
        "--ip",
        default=None,
        help=f"device address (default: $ESP32_IP or {DEFAULT_DEVICE_IP})",
    )
