# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

DoubleLayerAgent is a **two-tier Agent simulation system** (6 processes) that validates: layered Agent orchestration, heterogeneous thing calling (HTTP REST + SSE Agent), multi-source data aggregation, and dual-layer chart generation.

- **L1 Orchestrator Agent** (`l1_agent/`, port 8001) — understands user queries, selects L2 things, aggregates results, generates comparison charts
- **L2 ParkingLotAgent ×3** (`instances/parking_{a,b,c}/`, ports 8011-8013) — same code, different `.env`/`.db` per instance. Full ReAct Agent with SQL tools
- **L2 SimpleThings** (`simple_things/`, port 8010) — stateless HTTP GET endpoints for cafeteria + hospital headcounts
- **Frontend** (`frontend/`, port 5173) — React 18 + TypeScript + ECharts + Tailwind, multi-source SSE fan-out

`ParkingLotAgent/` is a reference project — it is **not part of the running system** and can be deleted after development. Data regeneration is handled by `scripts/regenerate_data.py` + `scripts/regenerate_data.ps1`.

## Start / build / verify

```bash
# Install all dependencies (one-time)
cd l1_agent && pip install -r requirements.txt
cd ../simple_things && pip install -r requirements.txt
cd ../frontend && npm install

# (Re)generate L2 data
.\scripts\regenerate_data.ps1

# Start everything
.\start_all.ps1    # starts 6 processes; open http://localhost:5173

# Quick verify
curl http://localhost:8010/api/health    # SimpleThings
curl http://localhost:8011/api/health    # ParkingLotAgent A
curl http://localhost:8001/api/health    # L1
cd frontend && npx tsc --noEmit          # type-check
```

Each service can also be started individually for debugging:
```bash
cd l1_agent && uvicorn main:app --port 8001
```

## Architecture (non-obvious from file listing)

### Two-tier ReAct with parallel fan-out

L1's `agent_loop` (`l1_agent/agent.py`) extends ParkingLotAgent's ReAct loop. The critical difference: when the LLM returns N `tool_calls` in one turn, L1 executes them **in parallel via `asyncio.gather`**. This is how "query all 3 parking lots at once" works.

L2 tools (`query_parking_lot_*`, `query_cafeteria`, `query_hospital`) are **not** called through `TOOL_EXECUTORS` — the agent loop checks `tool_name in BRIDGE_TOOL_NAMES` and dispatches to `bridge.py` functions instead. `TOOL_EXECUTORS` only serves L1 own tools (`find_nearby_things`, `aggregate`, `render_chart`).

### Bridge layer (`l1_agent/bridge.py`)

Two code paths, same return shape:
- **Agent things** (SSE): `query_agent_thing()` → POST to L2 `/api/chat`, parses SSE stream line-by-line (`event:`/`data:`/blank-line framing), emits `source_*` events to frontend, extracts JSON from L2's final text via `_extract_json()`
- **REST things** (HTTP): `query_rest_thing()` → GET request, wraps response into `{source, structured, summary}`

Both return `structured` (a dict or None) for consumption by the L1 `aggregate` tool.

### SSE event routing: `message_id` binding

L1 generates a `message_id` per user request. Every `source_*` SSE event carries this ID. The frontend uses it to route L2 sub-events to the correct `AssistantMessage.sources[]` entry — critical for concurrent multi-source queries.

### Config validation at import time

`l1_agent/config.py` validates `things.yaml` ↔ `tools.yaml` bidirectional consistency on import. Every `thing_id` in one must exist in the other. Mismatch → `sys.exit(1)` with a specific error message. This runs at L1 startup, before any requests are served.

### `_extract_json` algorithm (bridge.py)

L2's System Prompt requires a JSON block at the end of responses. `_extract_json()` finds all top-level `{...}` pairs (tracking brace depth), tries `json.loads()` on each, returns the **last** valid dict. If L2 returns no parseable JSON, `structured` is `None` and the `aggregate` tool skips that data item.

### ParkingLotAgent adaptations for L2 role

Three changes were made to ParkingLotAgent/backend before copying to instances:
1. **System Prompt** (`agent.py`): changed from user-facing assistant → machine-facing data service; requires JSON summary in every response
2. **`config.py`**: added `PARKING_NAME`, `TOTAL_SPOTS`, `FLOORS`, `SPOTS_PER_FLOOR`, `NEV_WEIGHTS`, `PORT` from `.env`; `SPOTS_PER_FLOOR` supports single-integer shorthand (e.g., `"200"` → `[200,200,200,200]`)
3. **`db.py`**: `DATABASE_PATH` accessed via `config.DATABASE_PATH` (not module-level import) so `data_generator.py` can override it; `seed_config()` accepts parameters
4. **`data_generator.py`**: full `argparse` CLI (`--name`, `--total-spots`, `--floors`, `--spots-per-floor`, `--nev-weights`, `--db-path`, `--days`)

## Critical pitfalls

- **ReAct constraint**: each LLM turn returns either `tool_calls` OR `content`, never both. If LLM returns both, L1's agent loop drops `content` and only processes `tool_calls`
- **`aggregate` nested paths**: use `dict.get(key)` chaining (not `getattr`). Field `"structured.value"` → `item.get("structured", {}).get("value")`
- **`SPOTS_PER_FLOOR` format**: comma-separated string in `.env` (e.g., `"167,167,166"`). `config.py`'s `_parse_spots_per_floor()` handles the single-integer shorthand
- **`NEV_WEIGHTS` format**: comma-separated 4 integers summing to ~100 (`"ICE,BEV,PHEV,HEV"`). `data_generator.py` divides by the sum to get probabilities
- **PowerShell `Start-Process`**: `-ArgumentList` must be comma-separated array (`"-m", "uvicorn", ...`). `npm` must be invoked via `cmd /c "npm run dev"` because `npm` is a `.cmd` script, not a Win32 executable
- **`DATABASE_PATH` in db.py**: accessed as `config.DATABASE_PATH` at call time, not imported at module level — necessary so `data_generator.py` can set it before `init_db()`/`seed_config()` run
- **No auth, no persistence, no Docker** — these are explicit non-goals (SPEC §1.2)
