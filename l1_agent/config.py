"""L1 Agent configuration — .env + things.yaml + tools.yaml loading & validation."""

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── LLM config ───────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
THINKING_MODE = os.environ.get("THINKING_MODE", "enabled")

# ── Server config ────────────────────────────────────────
L1_PORT = int(os.environ.get("L1_PORT", "8001"))

# ── User location (with fallback chain) ──────────────────
USER_DEFAULT_LAT = float(os.environ.get("USER_DEFAULT_LAT", "39.9150"))
USER_DEFAULT_LNG = float(os.environ.get("USER_DEFAULT_LNG", "116.4040"))

# ── Agent config ─────────────────────────────────────────
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "8"))
L2_TIMEOUT_SECONDS = float(os.environ.get("L2_TIMEOUT_SECONDS", "20.0"))

# ── Loading config files ─────────────────────────────────
THINGS_CONFIG = os.environ.get("THINGS_CONFIG", "../config/things.yaml")
TOOLS_CONFIG = os.environ.get("TOOLS_CONFIG", "../config/tools.yaml")


def _resolve_path(path: str) -> Path:
    """Resolve a path relative to BASE_DIR."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()


def load_things() -> list[dict]:
    """Load things.yaml, return list of thing dicts."""
    path = _resolve_path(THINGS_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("things", [])


def load_user_default_location() -> tuple[float, float]:
    """
    Load user default location. Priority:
    1. .env USER_DEFAULT_LAT / USER_DEFAULT_LNG
    2. things.yaml user_default section
    3. Hardcoded fallback (39.9150, 116.4040)
    """
    lat = USER_DEFAULT_LAT
    lng = USER_DEFAULT_LNG

    # Check if things.yaml has a user_default and .env didn't override explicitly
    path = _resolve_path(THINGS_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    yaml_default = data.get("user_default", {})
    if yaml_default:
        # Only use yaml values if .env values are still defaults
        if os.environ.get("USER_DEFAULT_LAT") is None:
            lat = float(yaml_default.get("lat", lat))
        if os.environ.get("USER_DEFAULT_LNG") is None:
            lng = float(yaml_default.get("lng", lng))

    print(f"[L1 Config] User default location: ({lat}, {lng})")
    return lat, lng


def load_tool_schemas() -> list[dict]:
    """Load tools.yaml, return list of tool schema dicts."""
    path = _resolve_path(TOOLS_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("tools", [])


def validate_config(things: list[dict], tool_schemas: list[dict]) -> None:
    """Validate things.yaml ↔ tools.yaml consistency. Exits on failure."""
    thing_ids = {t["id"] for t in things}
    tool_thing_ids = {ts["thing_id"] for ts in tool_schemas}

    # Check: every tool's thing_id exists in things
    for tid in tool_thing_ids:
        if tid not in thing_ids:
            print(f"[CONFIG ERROR] tools.yaml 中 thing_id '{tid}' 在 things.yaml 中不存在")
            sys.exit(1)

    # Check: every thing has a tool schema
    for tid in thing_ids:
        if tid not in tool_thing_ids:
            print(f"[CONFIG ERROR] things.yaml 中 thing_id '{tid}' 在 tools.yaml 中缺少 tool schema")
            sys.exit(1)

    # Check: protocol values
    for t in things:
        if t.get("protocol") not in ("agent_sse", "http_rest"):
            print(f"[CONFIG ERROR] thing '{t['id']}' 的 protocol 无效: {t.get('protocol')}")
            sys.exit(1)

    # Check: endpoint ports don't conflict with L1
    l1_port = L1_PORT
    for t in things:
        endpoint = t.get("endpoint", "")
        if f":{l1_port}" in endpoint or f":{l1_port}/" in endpoint:
            print(f"[CONFIG ERROR] thing '{t['id']}' 的 endpoint 端口与 L1 冲突: {endpoint}")
            sys.exit(1)

    print(f"[L1 Config] Validated: {len(things)} things, {len(tool_schemas)} tool schemas")


# ── Build lookup maps ────────────────────────────────────
THINGS = load_things()
TOOL_SCHEMAS_RAW = load_tool_schemas()

# thing_id → thing dict
THING_MAP: dict[str, dict] = {t["id"]: t for t in THINGS}

# thing_id → tool schema dict
TOOL_SCHEMA_MAP: dict[str, dict] = {}
for ts in TOOL_SCHEMAS_RAW:
    schema = ts["schema"]
    TOOL_SCHEMA_MAP[ts["thing_id"]] = schema

# Collect thing type → list of thing_ids for filtering
THINGS_BY_TYPE: dict[str, list[str]] = {}
for t in THINGS:
    THINGS_BY_TYPE.setdefault(t["type"], []).append(t["id"])

# Reverse map: tool_name → thing_id (O(1) lookup for bridge tool dispatch)
TOOL_NAME_TO_THING_ID: dict[str, str] = {}
for tid, schema in TOOL_SCHEMA_MAP.items():
    TOOL_NAME_TO_THING_ID[schema["function"]["name"]] = tid

# Validate on import
validate_config(THINGS, TOOL_SCHEMAS_RAW)
