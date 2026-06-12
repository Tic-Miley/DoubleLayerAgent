import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Load .env from CWD first (for instances), fall back to BASE_DIR/.env
load_dotenv(".env", override=False)
load_dotenv(BASE_DIR / ".env", override=True)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "parking_lot.db"))

# Ensure data directory exists
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

# Thinking mode: "enabled" (default, higher reasoning) or "disabled" (faster response)
THINKING_MODE = os.environ.get("THINKING_MODE", "enabled")

# Parking lot config (from .env, for instances)
PARKING_NAME = os.environ.get("PARKING_NAME", "Demo停车场")
TOTAL_SPOTS = int(os.environ.get("TOTAL_SPOTS", "800"))
FLOORS = int(os.environ.get("FLOORS", "4"))
NEV_WEIGHTS = os.environ.get("NEV_WEIGHTS", "55,25,12,8")
PORT = int(os.environ.get("PORT", "8000"))


def _parse_spots_per_floor(raw: str, floors: int, total_spots: int) -> list[int]:
    """Parse SPOTS_PER_FLOOR: comma-separated or single integer shorthand."""
    parts = [int(x.strip()) for x in raw.split(",")]
    if len(parts) == 1:
        base = parts[0]
        spots = [base] * floors
        diff = total_spots - sum(spots)
        for i in range(diff):
            spots[i] += 1
        return spots
    return parts


SPOTS_PER_FLOOR = _parse_spots_per_floor(
    os.environ.get("SPOTS_PER_FLOOR", "200"),
    FLOORS,
    TOTAL_SPOTS,
)

# Agent config
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "8"))
SQL_TIMEOUT_SECONDS = 5
SQL_MAX_ROWS = 1000
TOKEN_WARNING_THRESHOLD = 80_000
