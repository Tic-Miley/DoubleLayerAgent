# DoubleLayerAgent — 完整技术规范

> 版本 1.4 | 2026-06-12

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [Layer 2：物的设计](#3-layer-2物的设计)
4. [Layer 1：编排 Agent](#4-layer-1编排-agent)
5. [通信协议](#5-通信协议)
6. [配置体系](#6-配置体系)
7. [前端设计](#7-前端设计)
8. [数据流全景](#8-数据流全景)
9. [错误处理与降级](#9-错误处理与降级)
10. [LLM 配置](#10-llm-配置)
11. [部署方案](#11-部署方案)
12. [文件结构](#12-文件结构)
13. [决策记录](#13-决策记录)

---

## 1. 项目概述

### 1.1 目标

构建**两层 Agent 仿真系统**，验证以下技术可行性：

1. **双层 Agent 编排**：Layer 1 Agent 理解用户语义 → 选择 Layer 2 物 → 调用接口/Agent → 整合分析
2. **异构物统一调用**：简单 HTTP 数据接口 + Agent 类物通过统一 tool-calling 协议被 L1 调用
3. **多源数据聚合**：跨多个物收集数据，在 L1 层做结构化聚合和可视化
4. **双层图表生成**：L2 生成单体图表，L1 生成跨物对比图表
5. **流式透传**：L2 Agent 的内部过程透明展示在前端，但自然语言出口统一在 L1

### 1.2 非目标

- 不做生产级高可用/鉴权/限流
- 不做动态服务注册发现（使用静态配置）
- 不做真实地理编码（不使用地图 API）
- 不做会话持久化（对话仅内存保存）

### 1.3 仿真规模

| 层级 | 组件 | 数量 | 说明 |
|------|------|------|------|
| L1 | 编排 Agent + 前端 | 1 | 用户唯一入口 |
| L2 | ParkingLotAgent 实例 | 3 | 同代码、不同参数、不同数据 |
| L2 | 简单物服务 | 1 | 聚合食堂+医院（同一进程、不同路由） |
| — | 前端 Dev Server | 1 | Vite 开发服务器 |
| **总计** | **6 进程** | | |

> 用户可通过 L1 向 L2 停车场 Agent 提出任何其支持的查询——剩余车位、历史趋势、车辆详情等。L2 Agent 通过 SQL 工具几乎能回答所有停车场相关问题（参见 ParkingLotAgent goal.md）。

---

## 2. 系统架构

### 2.1 架构全景图

```
┌─────────────────────────────────────────────────────────┐
│                     User (Browser)                        │
│                  http://localhost:5173                    │
└─────────────────────┬───────────────────────────────────┘
                      │ SSE (POST /api/chat)
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Layer 1: Orchestrator Agent                  │
│              FastAPI :8001                                │
│  ┌──────────────────────────────────────────────────┐   │
│  │  agent_loop() — Extended ReAct                    │   │
│  │  • Parallel tool_calls via asyncio.gather         │   │
│  │  • SSESender: L1 events → frontend                │   │
│  │  • SSEReceiver: L2 events ← parking lots          │   │
│  │                                                    │   │
│  │  L1 Own Tools (code-defined):                     │   │
│  │  • find_nearby_things  — Haversine geo filter     │   │
│  │  • aggregate           — Structured multi-source  │   │
│  │  • render_chart        — Cross-thing charts       │   │
│  │                                                    │   │
│  │  L2 Bridge Tools (tools.yaml → dynamic):          │   │
│  │  • query_parking_lot_A — SSE → ParkingLotAgent    │   │
│  │  • query_parking_lot_B — SSE → ParkingLotAgent    │   │
│  │  • query_parking_lot_C — SSE → ParkingLotAgent    │   │
│  │  • query_cafeteria     — HTTP GET → SimpleThings  │   │
│  │  • query_hospital      — HTTP GET → SimpleThings  │   │
│  └──────────────────────────────────────────────────┘   │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │ SSE      │ SSE      │ SSE      │ HTTP GET
       ▼          ▼          ▼          ▼
┌──────────┐┌──────────┐┌──────────┐┌─────────────────────┐
│ParkingLot││ParkingLot││ParkingLot││ SimpleThings Service │
│Agent A   ││Agent B   ││Agent C   ││ :8010                │
│:8011     ││:8012     ││:8013     ││                      │
│ReAct +   ││ReAct +   ││ReAct +   ││ GET /api/cafeteria   │
│5 tools   ││5 tools   ││5 tools   ││ → {value: 342}       │
│SQLite A  ││SQLite B  ││SQLite C  ││ GET /api/hospital    │
└──────────┘└──────────┘└──────────┘│ → {value: 187}       │
                                    └─────────────────────┘
```

### 2.2 进程端口分配

| 进程 | 端口 | 技术栈 |
|------|------|--------|
| L1 Backend | 8001 | FastAPI + Python |
| L1 Frontend (Dev) | 5173 | Vite + React 18 + TypeScript |
| ParkingLotAgent A | 8011 | FastAPI + Python (ParkingLotAgent backend) |
| ParkingLotAgent B | 8012 | FastAPI + Python (ParkingLotAgent backend) |
| ParkingLotAgent C | 8013 | FastAPI + Python (ParkingLotAgent backend) |
| SimpleThings | 8010 | FastAPI + Python |

---

## 3. Layer 2：物的设计

### 3.1 ParkingLotAgent（3 实例）

#### 3.1.1 代码复用策略

三个实例运行**完全相同的代码**（继承自 `ParkingLotAgent/backend/`），仅通过 `.env` 差异化。

#### 3.1.2 实例差异化参数

| 参数 | 实例 A | 实例 B | 实例 C |
|------|--------|--------|--------|
| `PORT` | 8011 | 8012 | 8013 |
| `PARKING_NAME` | 购物中心停车场 | 科技园停车场 | 社区停车场                  |
| `TOTAL_SPOTS` | 800 | 500 | 1200 |
| `FLOORS` | 4 | 3 | 5 |
| `SPOTS_PER_FLOOR` | 200,200,200,200 | 167,167,166 | 240,240,240,240,240 |
| `DATABASE_PATH` | data/parking_a.db | data/parking_b.db | data/parking_c.db |
| `NEV_WEIGHTS`（表记为 ICE/BEV/PHEV/HEV） | 55,25,12,8 | 50,30,12,8 | 60,20,12,8 |

> **NEV_WEIGHTS 格式说明**：`.env`、CLI 参数和上表的值均为逗号分隔的 4 个整数，顺序固定为 `ICE,BEV,PHEV,HEV`（燃油/纯电/插混/混动），权重之和应为 100。上表表头括号内的类型标注仅供阅读参考，机器学习读取时忽略。
>
> **差异化程度**：极简。仅 `name` 和 `total_spots` 产生显著差异。相同的数据生成算法（泊松到达 + 指数停车时长），不同实例因容量不同自然产生不同的占用量和占用率数据。
>
> **SPOTS_PER_FLOOR 说明**：实例 A (800/4=200) 和实例 C (1200/5=240) 均分；实例 B (500/3) 无法整除，前两层各 167，第三层 166。
> `data_generator.py` 的参数语义：
> - `--floors <int>` — 楼层数（如 `4`、`3`、`5`）
> - `--spots-per-floor <str>` — 可选，逗号分隔的每层车位数（如 `"167,167,166"`）。若省略或值与 `--floors` 不匹配，则自动均分 `--total-spots` 到各层（余数逐层 +1）。
> 三个实例的命令行示例见 §11.3。

#### 3.1.3 L2 Agent 适配

ParkingLotAgent 的 System Prompt 从「面向终端用户」调整为「**面向机器/上层 Agent**」：

- **核心变更**：
  - 角色定位：从 "停车场数据分析助手" → "停车场数据服务，为上层 Agent 提供结构化数据"
  - 回复风格：必须在回复末尾附结构化的 JSON 摘要，附带简短自然语言摘要
  - 减少对话修饰语（如 "好的，我来帮您查一下"）
- **保留能力**：
  - 全部 5 个工具：`get_config`、`query_aggregation`、`get_vehicle`、`sql_query`、`render_chart`
  - ReAct 循环逻辑不变
  - render_chart 用于生成单体图表（自身占用率饼图、趋势折线图）
- **API 端点**：复用现有 `POST /api/chat`，不做任何 API 改动

**期望行为示例**：L2 收到自然语言查询后应返回结构化 JSON 摘要：
```
输入: "最近30天新能源车占比"
期望输出: 一段简短文字说明 + JSON 块
{"nev_ratio": 0.45, "total_vehicles_30d": 2340, "nev_count_30d": 1053,
 "occupancy_rate": 0.62, "total_spots": 800, "available_spots": 304}
```

#### 3.1.4 数据生成

复用 `data_generator.py`，支持命令行参数：

```bash
python data_generator.py \
  --name "购物中心停车场" \
  --total-spots 800 \
  --floors 4 \
  --spots-per-floor "200,200,200,200" \
  --nev-weights "55,25,12,8" \
  --db-path ../../instances/parking_a/data/parking_a.db \
  --days 120
```
> `--db-path` 的相对路径基准为执行脚本时的 CWD。以上命令假设 CWD 为 `ParkingLotAgent/backend/`。
三个实例各自运行一次数据生成，产生独立的 `.db` 文件。

### 3.2 简单物服务（食堂 + 医院）

#### 3.2.1 设计决策

- **一个 FastAPI 进程**托管两个简单物的路由
- 每个简单物返回 `{"value": <int>}` 表示当前人数
- 数据由随机数生成，无需数据库

#### 3.2.2 API 设计

```
GET /api/health
→ 200 {"status": "ok"}

GET /api/cafeteria/count
→ 200 {"value": 342, "capacity": 500, "timestamp": "2026-06-11T12:30:00"}

GET /api/hospital/count
→ 200 {"value": 187, "capacity": 300, "timestamp": "2026-06-11T12:30:00"}
```

> `capacity` 为固定值（食堂 500，医院 300）；`value` 为 `random.randint(0, capacity)` 每次请求随机生成。`timestamp` 为服务端当前时间。
>
> **已知限制**：`value` 每次请求随机生成，同一物在 L1 的两次连续查询中可能返回不同数值。这是仿真简化，生产环境应接入真实数据源。

#### 3.2.3 实现

单文件 `simple_things/main.py`（~40 行）：

```python
import os
import random
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

CAFETERIA_CAPACITY = int(os.getenv("CAFETERIA_CAPACITY", "500"))
HOSPITAL_CAPACITY   = int(os.getenv("HOSPITAL_CAPACITY", "300"))

app = FastAPI()

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/cafeteria/count")
async def cafeteria_count():
    return {
        "value": random.randint(0, CAFETERIA_CAPACITY),
        "capacity": CAFETERIA_CAPACITY,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/hospital/count")
async def hospital_count():
    return {
        "value": random.randint(0, HOSPITAL_CAPACITY),
        "capacity": HOSPITAL_CAPACITY,
        "timestamp": datetime.now().isoformat()
    }
```

---

## 4. Layer 1：编排 Agent

### 4.0 API 请求/响应模型

```python
# l1_agent/models.py — Pydantic 模型

class ChatRequest(BaseModel):
    message: str                          # 用户自然语言输入（必填）
    conversation_id: str | None = None    # 会话 ID（可选，L1 内存管理）
    history: list[dict] | None = None     # 对话历史（可选，LLM messages 格式）
                                           # 透传给 L2 Agent 以支持多轮上下文
    model: str | None = None              # 可选覆盖默认模型
    thinking_mode: str | None = None      # 可选覆盖 thinking mode

class HealthResponse(BaseModel):
    status: str                           # "ok"
```

> `history` 透传路径：L1 `ChatRequest.history` → bridge executor 在调用 L2 `/api/chat` 时传入 `request_body["history"]`。L2 的 `ChatRequest.history` 与之格式兼容（同为 LLM messages 列表）。

### 4.1 Agent 循环

**复用并扩展** ParkingLotAgent 的 `agent_loop()` 结构（详见决策 D1）。

#### 4.1.1 核心改动点

| 改动 | 说明 |
|------|------|
| **并行 tool_call 执行** | 同一轮 LLM 返回的多个 `tool_calls` 使用 `asyncio.gather` 并行执行 |
| **HTTP/SSE Tool Executor** | L2 物的 tool executor 发起 HTTP 请求（SSE 或 REST）而非本地函数调用 |
| **SSE 事件透传** | L2 的 `tool_call`/`chart` 事件被包装为 L1 事件透传给前端（详见 §5.3） |
| **L1 自有工具** | 新增 `find_nearby_things`、`aggregate`、`render_chart` 三个 Python 本地工具 |

#### 4.1.2 执行流程

```
用户消息 →
  LLM 工具决策（非流式, tool_choice=auto）
    →
  LLM 返回 N 个 tool_calls
    →
  asyncio.gather(执行 tool_1, tool_2, ..., tool_N)
    │
    ├── L2 Bridge Tool → HTTP/SSE 调用 L2 物
    │   ├── 发送 SSE: tool_call running (L1 包装)
    │   ├── 接收 L2 SSE 事件
    │   ├── 透传 L2 tool_call/chart 事件 (嵌套在 SourceCard)
    │   └── 发送 SSE: tool_call done/error (L1 包装)
    │
    ├── find_nearby_things → Haversine + things.yaml
    │
    ├── aggregate → Python 结构化计算
    │
    └── render_chart → ECharts option 校验
    →
  工具结果追加到 messages（每项为 OpenAI 标准 tool result 格式）：
    {"role": "tool", "tool_call_id": "<call_id>", "content": "<json_dump(return_value)>"}
  L2 bridge tool 返回的 dict 整体用 json.dumps() 序列化后填入 content 字段，
  确保 LLM 可读取结构化数据（含 structured 子对象）。
    →
  LLM 判断是否继续（最多 `MAX_ITERATIONS` 轮，默认 8，在 `.env` 中配置）
    →
  LLM 最终文本 → 流式 SSE text 事件
```

### 4.2 L1 自有工具

#### 4.2.1 `find_nearby_things`

```yaml
名称: find_nearby_things
定义位置: Python 代码（l1_agent/tools/geo.py）
参数:
  - lat: float (必填) — 中心点纬度
  - lng: float (必填) — 中心点经度
  - radius_km: float (必填) — 搜索半径（公里）
  - thing_type: string (可选) — 物类型过滤 (parking_lot|cafeteria|hospital)
返回:
  things: [{id, name, type, lat, lng, distance_km}]
  （endpoint 等内部协议信息不暴露给 LLM，由 bridge 层内部通过 things.yaml 查找）
逻辑:
  1. 从 things.yaml 加载所有物
  2. 用 Haversine 公式计算距离（地球半径 R=6371.0 km）
  3. 筛出 distance_km <= radius_km 的物
  4. 按 distance_km 升序排列
  5. 返回结果列表
```

> 用户位置 `(lat, lng)` 来自 `.env` 中的 `USER_DEFAULT_LAT` / `USER_DEFAULT_LNG`。LLM 负责在调用此工具时传入。

#### 4.2.2 `aggregate`

```yaml
名称: aggregate
定义位置: Python 代码（l1_agent/tools/aggregate.py）
参数:
  - data: array (必填) — 待聚合的数据列表，每项为 dict
  - operations: array (必填) — 聚合操作列表
    每项: {field: string, func: string, alias: string (可选)}
    支持的 func: sum|avg|min|max|count|median|std
    (std 在数据点为 1 个时返回 null；任何 func 在 data 为空数组时返回 null)
返回:
  results: {alias或生成的key: 计算结果}
  例: {"avg_occupancy_rate": 0.68, "total_vacant": 523}
逻辑:
  1. 遍历 operations
  2. 从 data 中提取 field 值列表
  3. 执行对应统计函数
  4. 返回结果 dict
边缘情况处理:
  - field 支持嵌套路径访问（如 "structured.value"、"data.occupancy_rate"），
    用点号分隔。实现中按点号切分后逐层 `dict.get(key)` 取值
  - 数据项中 field 不存在或值为 None → 跳过该项（不参与计算），
    并在结果中追加 {field}_skipped_count 表示跳过数量
  - 数据项包含 "error" 键（来自 L2 失败调用）→ 整体跳过，不计入统计
  - data 参数上限 500 条；超出时截断并返回 {field}_truncated: true
  - 所有有效值被跳过（全部为 None/缺失/error）→ 返回 {field}: null
```

#### 4.2.3 `render_chart` (L1 版)

```yaml
名称: render_chart
定义位置: Python 代码（l1_agent/tools/chart.py）
参数:
  - option: object (必填) — 完整 ECharts option
  - chart_title: string (可选) — 图表标题
返回:
  {status: "rendered", chart_id, chart_type, data_points, option}
  (chart_id 格式: {source_id}_{unix_timestamp_ms}_{random_6chars}，例如 parking_lot_a_1718123456789_a3Bx9K)
实现: 复用 ParkingLotAgent 的 `render_chart` 核心逻辑（ECharts option 校验 + 自动修复）。
区别: 新增 `chart_title` 参数。当提供 `chart_title` 时，自动注入到 `option.title.text`（若 option
  中已设置 title.text 则优先使用 option 中的值）。用于生成跨物对比图表（多停车场占用率柱状图等）。
```

### 4.3 System Prompt 设计要点

```
你是城市数据整合助手。你可以访问多个城市设施的数据服务。

## 能力
- 搜索附近设施（find_nearby_things）
- 查询各设施的数据（通过对应工具）
- 聚合多源数据（aggregate）
- 生成对比图表（render_chart）

## 工作流程
1. 理解用户问题，识别空间范围和数据需求
2. 如需空间筛选 → find_nearby_things
3. 对筛选结果并行查询各设施数据
4. 如需跨源统计 → aggregate
5. 综合回答 + 图表

## 数据源说明
L2 Agent 会以 JSON 格式返回结构化数据。你需要从返回结果中提取数值字段，
必要时使用 aggregate 工具做跨源统计。你可以向停车场查询任何数据——剩余车位、
历史趋势、车辆详情等。L2 Agent 通过 SQL 工具几乎能回答所有停车场相关问题。

## 当前用户位置
纬度: {user_lat}, 经度: {user_lng}
```

> 占位符 `{user_lat}` / `{user_lng}` 在 L1 启动时由 `config.py` 使用 Python `str.format()` 替换。取值优先级：`.env` 的 `USER_DEFAULT_LAT/USER_DEFAULT_LNG` > `things.yaml` 的 `user_default` > 硬编码回退值 `(39.9150, 116.4040)`。`config.py` 启动时打印最终使用的坐标值。

---

## 5. 通信协议

### 5.1 L1 ↔ L2 通信总览

| L2 物类型 | 协议 | 端点 | 请求格式 | 响应格式 |
|-----------|------|------|----------|----------|
| ParkingLotAgent | SSE | `POST /api/chat` | `{message, history?}` | SSE 事件流 |
| SimpleThings | HTTP REST | `GET /api/{thing}/count` | 无参数 | `{value, capacity, timestamp}` |

> `history` 为可选透传字段。L1 收到用户对话历史后，转发给 L2 Agent 以支持多轮上下文。简单物为无状态 GET，不接收 history。

### 5.2 L1 → L2 调用封装

每个 L2 物在 L1 中被封装为一个 **bridge tool**，其 executor 内部发起网络调用：

```python
# L2 Agent 类物的 executor 伪代码
# 注意：所有 send_l2_* 函数内部使用 asyncio.Lock 保护 SSE 写入，
# 确保并发 L2 响应时事件帧不交错。
# asyncio.Lock 粒度：per-SSE-connection（每个 L1 用户请求持有独立锁），非全局锁。

import json
import logging

logger = logging.getLogger(__name__)

async def query_parking_lot_A(message: str, history: list | None = None) -> dict:
    """通过 SSE 调用 ParkingLotAgent A

    Args:
        message: 转发给 L2 的自然语言查询
        history: 可选透传的对话历史（来自 L1 的 ChatRequest.history），
                 用于 L2 Agent 做多轮上下文理解。格式为 LLM messages 列表。
    """
    source_id = "parking_lot_A"   # 从 things.yaml 的 thing_id 映射
    async with httpx.AsyncClient() as client:
        # 构建请求体：message 必传，history 可选透传
        request_body = {"message": message}
        if history:
            request_body["history"] = history

        async with client.stream(
            "POST", "http://localhost:8011/api/chat",
            json=request_body,
            timeout=L2_TIMEOUT_SECONDS   # 从 .env 读取，默认 20.0
        ) as response:
            # 解析 SSE 流（正确处理多行 data: 事件）
            # SSE 规范：一个事件可由多条 data: 行组成，最终以空行分隔
            tool_results = []
            final_text = ""
            charts = []
            event_type = "message"       # 默认事件类型（SSE 规范）
            data_buffer: list[str] = []  # 累积同一事件的多行 data

            async for line in response.aiter_lines():
                if line == "":
                    # 空行 = 事件结束 → flush buffer
                    if data_buffer and event_type != "text":
                        data_str = "\n".join(data_buffer)
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            # L2 返回非法 JSON → 记录并跳过该事件，不中断流
                            logger.warning(f"L2 {source_id} SSE 解析失败，跳过事件 {event_type}: {data_str[:200]}")
                            event_type = "message"
                            data_buffer = []
                            continue
                        if event_type == "tool_call":
                            tool_results.append(data)
                            await send_l2_tool_event(source=source_id, event=data)
                        elif event_type == "chart":
                            charts.append(data)
                            await send_l2_chart_event(source=source_id, event=data)
                        elif event_type == "done":
                            final_text = data.get("final_text", "")
                        elif event_type == "error":
                            # L2 主动返回 error → 记录错误信息用于返回
                            l2_error = data.get("error", "L2 未知错误")
                            logger.error(f"L2 {source_id} 返回 error: {l2_error}")
                            if not final_text:
                                final_text = f"[L2 Error] {l2_error}"
                    event_type = "message"
                    data_buffer = []
                elif line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buffer.append(line[5:].strip())
                # 忽略 id: / retry: / 注释行 (:)

            # 从 L2 的最终文本中提取 JSON 结构
            # _extract_json 算法（明确步骤）：
            # 1. 在 final_text 中定位所有顶级 `{` 及其匹配的 `}`
            # 2. 对每个括号对，尝试 json.loads()；解析成功则记为候选 JSON
            # 3. 若存在多个候选 → 取**最后一个**（L2 System Prompt 要求摘要 JSON 在末尾）
            #    （注意：不取内层嵌套 JSON；{...{...}...} 中只取最外层合法对象）
            # 4. final_text 为空 → 返回 None
            # 5. 无合法 JSON → 返回 None，同时记录 warning 日志
            # 6. 下游 aggregate 工具在 structured 为 None 时跳过该数据项（不参与聚合）
            structured = _extract_json(final_text)
            return {
                "source": source_id,
                "tool_results": tool_results,
                "charts": charts,
                "summary": final_text,
                "structured": structured        # 提取的 JSON dict，供 aggregate 消费
            }

# 简单物 HTTP executor — 返回结构与 Agent executor 对齐，统一含 structured 字段
async def query_cafeteria() -> dict:
    """通过 HTTP GET 调用简单物"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://localhost:8010/api/cafeteria/count",
            timeout=5.0
        )
        data = resp.json()
        return {
            "source": "cafeteria_downtown",
            "structured": {          # 与 Agent executor 对齐，供 aggregate 直接消费
                "value": data["value"],
                "capacity": data["capacity"]
            },
            "summary": f"当前{data['value']}人 (容量{data['capacity']})",
            "timestamp": data["timestamp"]
        }
```

### 5.3 SSE 事件透传协议

#### 5.3.1 L1 新增 SSE 事件类型

| 事件类型 | 方向 | 数据结构 | 触发时机 |
|----------|------|----------|----------|
| `source_start` | L1→前端 | `{message_id, source_id, source_name, tool_name}` | L1 **发起 HTTP 请求前**立即发送，确保前端先收到 PENDING→RUNNING 状态转变再接收后续 source_tool_call/source_chart 事件 |
| `source_tool_call` | L1→前端 | `{message_id, source_id, tool_name, status, arguments?, result_preview?, error?}` | L2 内部的工具调用状态变化 |
| `source_chart` | L1→前端 | `{message_id, source_id, chart_id, chart_type, option}` | L2 生成图表 |
| `source_done` | L1→前端 | `{message_id, source_id, status, summary?}` | L2 查询完成 |
| `source_error` | L1→前端 | `{message_id, source_id, error}` | L2 查询失败/超时 |
>
> `message_id` 是 L1 Backend 在创建本轮 `AssistantMessage` 时生成并随所有 source_* 事件下发的标识，前端据此将事件路由到正确的消息对象（详见 §7.3）。

> L1 自身的 tool_call/text/chart/done 事件保持不变（与 ParkingLotAgent SSE 协议兼容）。
>
> **并发安全**：L1 内部所有 SSE 写入操作受 `asyncio.Lock` 保护，确保并发 L2 响应时事件帧不交错。

#### 5.3.2 透传规则

| L2 事件 | 是否透传 | 透传方式 |
|---------|----------|----------|
| `tool_call` (L2) | ✅ 透传 | 包装为 `source_tool_call`，标记 source_id |
| `chart` (L2) | ✅ 透传 | 包装为 `source_chart`，标记 source_id |
| `text` (L2 token) | ❌ 不透传 | L1 是唯一自然语言出口 |
| `done` (L2) | ✅ 透传 | 包装为 `source_done` |
| `error` (L2) | ✅ 透传 | 包装为 `source_error` |

---

## 6. 配置体系

### 6.1 文件结构

```
DoubleLayerAgent/
├── config/
│   ├── things.yaml          # L2 物实例元数据
│   └── tools.yaml           # L2 物 tool schemas（标准 OpenAI 格式）
├── l1_agent/
│   └── .env                 # L1 环境变量
├── instances/
│   ├── parking_a/.env       # 停车场 A 配置
│   ├── parking_b/.env       # 停车场 B 配置
│   └── parking_c/.env       # 停车场 C 配置
└── simple_things/
    └── .env                 # 简单物服务配置
```

### 6.2 `things.yaml` — 物实例元数据

```yaml
# things.yaml — Layer 2 物注册表
# 每个物包含：标识、位置、协议、端点

things:
  - id: parking_lot_a
    name: 购物中心停车场
    type: parking_lot
    location:
      lat: 39.9219
      lng: 116.4435
    description: 位于朝阳区的800车位地面停车场，服务周边商圈
    protocol: agent_sse
    endpoint: http://localhost:8011/api/chat

  - id: parking_lot_b
    name: 科技园停车场
    type: parking_lot
    location:
      lat: 39.9280
      lng: 116.4200
    description: 位于科技园的500车位地下停车场，主要服务园区企业
    protocol: agent_sse
    endpoint: http://localhost:8012/api/chat

  - id: parking_lot_c
    name: 社区停车场
    type: parking_lot
    location:
      lat: 39.9050
      lng: 116.4350
    description: 位于朝阳区的1200车位大型社区停车场
    protocol: agent_sse
    endpoint: http://localhost:8013/api/chat

  - id: cafeteria_downtown
    name: 中心食堂
    type: cafeteria
    location:
      lat: 39.9150
      lng: 116.4040
    description: 提供当前就餐人数
    protocol: http_rest
    endpoint: http://localhost:8010/api/cafeteria/count

  - id: hospital_downtown
    name: 中心医院
    type: hospital
    location:
      lat: 39.9180
      lng: 116.4100
    description: 提供当前门诊等候人数
    protocol: http_rest
    endpoint: http://localhost:8010/api/hospital/count

# 用户默认位置（演示预设）
# 注意：此处坐标与 cafeteria_downtown 完全相同 (39.9150, 116.4040)，
# 因此 find_nearby_things 会对食堂返回 distance_km=0。这是有意为之的演示设计。
user_default:
  lat: 39.9150
  lng: 116.4040
```

### 6.3 `tools.yaml` — L2 物 Tool Schemas

```yaml
# tools.yaml — L2 物的 OpenAI function-calling tool schemas
# L1 启动时加载并注册为 LLM 可用工具
# L1 自有工具在 Python 代码中定义，不在此文件

tools:
  # ── ParkingLotAgent 共用 Schema（三个实例复用） ──
  - thing_id: parking_lot_a
    schema:
      type: function
      function:
        name: query_parking_lot_a
        description: |
          查询购物中心停车场的数据。支持：当前空余车位、车辆类型分布、
          楼层占用、历史趋势、车辆详情等。
          传入自然语言查询语句。返回结果中的 structured 字段包含:
          occupancy_rate (float 0-1), nev_ratio (float 0-1),
          total_spots (int), available_spots (int),
          vehicle_types (object, key=类型 value=数量)。
        parameters:
          type: object
          properties:
            query:
              type: string
              description: 自然语言查询，如"现在还剩多少车位"、"最近30天新能源车占比"
          required: ["query"]
          additionalProperties: false

  - thing_id: parking_lot_b
    schema:
      type: function
      function:
        name: query_parking_lot_b
        description: |
          查询科技园停车场的数据。支持：当前空余车位、车辆类型分布、
          楼层占用、历史趋势、车辆详情等。
          传入自然语言查询语句。返回结果中的 structured 字段包含:
          occupancy_rate (float 0-1), nev_ratio (float 0-1),
          total_spots (int), available_spots (int),
          vehicle_types (object, key=类型 value=数量)。
        parameters:
          type: object
          properties:
            query:
              type: string
              description: 自然语言查询语句
          required: ["query"]
          additionalProperties: false

  - thing_id: parking_lot_c
    schema:
      type: function
      function:
        name: query_parking_lot_c
        description: |
          查询社区停车场的数据。支持：当前空余车位、车辆类型分布、
          楼层占用、历史趋势、车辆详情等。
          传入自然语言查询语句。返回结果中的 structured 字段包含:
          occupancy_rate (float 0-1), nev_ratio (float 0-1),
          total_spots (int), available_spots (int),
          vehicle_types (object, key=类型 value=数量)。
        parameters:
          type: object
          properties:
            query:
              type: string
              description: 自然语言查询语句
          required: ["query"]
          additionalProperties: false

  # ── 简单物 Schema ──
  - thing_id: cafeteria_downtown
    schema:
      type: function
      function:
        name: query_cafeteria
        description: 查询中心食堂当前就餐人数
        parameters:
          type: object
          properties: {}
          required: []
          additionalProperties: false

  - thing_id: hospital_downtown
    schema:
      type: function
      function:
        name: query_hospital
        description: 查询中心医院当前门诊等候人数
        parameters:
          type: object
          properties: {}
          required: []
          additionalProperties: false
```

### 6.4 环境变量

#### L1 Agent (`l1_agent/.env`)

```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
THINKING_MODE=enabled
L1_PORT=8001
USER_DEFAULT_LAT=39.9150
USER_DEFAULT_LNG=116.4040
THINGS_CONFIG=../config/things.yaml
TOOLS_CONFIG=../config/tools.yaml
MAX_ITERATIONS=8
L2_TIMEOUT_SECONDS=20
```

#### ParkingLotAgent 实例 (`instances/parking_a/.env`)

```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
THINKING_MODE=disabled
PORT=8011
PARKING_NAME=购物中心停车场
TOTAL_SPOTS=800
FLOORS=4
SPOTS_PER_FLOOR=200,200,200,200
DATABASE_PATH=data/parking_a.db
NEV_WEIGHTS=55,25,12,8
```

> **SPOTS_PER_FLOOR 格式**：逗号分隔的整数字符串，条目数=`FLOORS`。若所有楼层车位数相同可简写为单整数（如 `200` 等价于 `200,200,200,200`），`config.py` 解析时自动展开。
>
> 实例 B/C 仅 `PORT`、`PARKING_NAME`、`TOTAL_SPOTS`、`FLOORS`、`SPOTS_PER_FLOOR`、`DATABASE_PATH`、`NEV_WEIGHTS` 不同。

#### 简单物服务 (`simple_things/.env`)

```bash
PORT=8010
CAFETERIA_CAPACITY=500
HOSPITAL_CAPACITY=300
```

### 6.5 配置校验

L1 启动时对 `things.yaml` 和 `tools.yaml` 做基本校验：

- `tools.yaml` 中每个 `thing_id` 必须在 `things.yaml` 中存在
- `things.yaml` 中每个 `thing_id` 必须在 `tools.yaml` 中有对应的 tool schema（双向检查）
- `protocol` 字段必须为 `agent_sse` 或 `http_rest`
- 端口号不与 L1 自身冲突（检查 endpoint URL 的端口 ≠ `L1_PORT`）
- 所有 `endpoint` URL 的协议（http/https）和端口格式合法

校验失败时 L1 启动打印明确错误信息（指出冲突的 thing_id / 字段 / 预期值）并 `sys.exit(1)`。

---

## 7. 前端设计

### 7.0 视觉品质要求

ECharts 主题注册跟随页面主题（深色/浅色），SourceCard 使用 CSS transition（状态切换 0.3s ease），图表自适应 resize。

### 7.1 技术栈

| 层 | 技术 |
|----|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| 样式 | Tailwind CSS |
| 图表 | ECharts (via ChartWidget) |
| 通信 | Fetch API + ReadableStream SSE 解析 |

#### 7.1.1 跨域与代理配置

前端 (:5173) 与 L1 Backend (:8001) 存在跨域。**主路径为 Vite 开发代理**（无需浏览器端 CORS 处理）；CORS 中间件作为备用方案保留，方便不使用代理的场景（如直接访问 L1 端口调试）。

**主路径 — Vite 开发代理**（`frontend/vite.config.ts`）：
```typescript
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
})
```
> `useChat` 中的 SSE 请求地址为相对路径 `/api/chat`，由 Vite Dev Server 转发到 L1 Backend，无跨域问题。

**备选 — L1 Backend CORS 中间件**（`l1_agent/main.py`，仅在绕过 Vite 代理时生效）：
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 7.2 组件复用与新建

| 组件 | 来源 | 说明 |
|------|------|------|
| `ChartWidget` | 复用 | ECharts 渲染，主题适配，自适应 resize |
| `ToolCallCard` | 复用 | 工具状态卡片（running → done/error 动画） |
| `ChatInput` | 复用 | 输入框，Shift+Enter 换行，发送/停止 |
| `ThemeToggle` | 复用 | 深色/浅色切换 |
| `UserMessage` | 复用 | 用户消息气泡 |
| `EmptyState` | 复用 | 空白欢迎页 |
| `Header` | 改造 | 标题改为「城市数据助手」，保留主题切换 |
| `MessageList` | 改造 | 新增 SourceCard 渲染，智能滚动保持 |
| `AssistantMessage` | 改造 | 新增 SourceCard 网格区 + L1 图表区 |
| `ChatLayout` | 重写 | 新的根布局结构 |
| `useChat` | 重写 | 多源扇出状态机（见 §7.3） |
| **`SourceCard`** | **新建** | 单个 L2 物的查询状态卡片 |
| **`QueryProgress`** | **新建** | 多源并行查询整体进度条 |
| `QuickQuestions` | 改造 | 示例问题适配城市数据场景 |

> "复用"组件直接从 ParkingLotAgent 前端复制（开发准备阶段一次性操作）。ParkingLotAgent 前端仅作源码参考，项目完成后可删除。

### 7.3 `useChat` — 多源扇出状态机

核心改动：从单线 SSE 解析变为**多源并发状态管理**。

```typescript
// 消息增强类型
interface AssistantMessage {
  id: string;                  // 消息唯一 ID（前端生成，如 msg_1718123456789_a3b）
  // ... 原有字段
  sources: SourceState[];      // 本轮查询涉及的 L2 物状态
  l1ToolCalls: ToolCall[];     // L1 自有工具的调用记录
  l1Charts: ChartData[];       // L1 生成的聚合图表
}

interface SourceState {
  sourceId: string;            // 如 "parking_lot_a"
  sourceName: string;          // 如 "购物中心停车场"
  status: 'pending' | 'running' | 'done' | 'error';
  toolCalls: ToolCall[];       // L2 内部的工具调用（source_tool_call 事件）
  charts: ChartData[];         // L2 生成的图表（source_chart 事件）
  summary?: string;            // L2 完成后的摘要
  error?: string;              // 失败信息
}
```

**事件→消息绑定机制**：每个 `source_*` SSE 事件携带 `message_id` 字段（由 L1 Backend 在生成事件时填入当前 AssistantMessage 的 ID）。前端 `useChat` 通过 `message_id` 定位到正确的 `AssistantMessage`，再通过 `source_id` 定位其中的 `SourceState` 进行更新。此绑定在上一次 SSE 流结束后重置。

**状态流转**：
```
PENDING → (收到 source_start) → RUNNING
  → (收到 source_tool_call*) → 更新 toolCalls[]
  → (收到 source_chart*)     → 更新 charts[]
  → (收到 source_done)       → DONE
  → (收到 source_error)      → ERROR (带 error 信息)
```

> 前端收到 `source_*` 事件时，对 `SourceState` 做**浅合并更新**（shallow merge），
> 即仅更新事件携带的字段，保留已有字段。React 使用不可变更新模式。
>
> **未知事件类型处理**：前端 SSE 解析器遇到未识别的事件类型时应当静默忽略（`console.warn` 记录），
> 不抛出异常、不中断流。这确保与未来事件类型扩展兼容。

### 7.4 UI 布局

```
┌──────────────────────────────────────────────┐
│  Header: "城市数据助手"            [🌙/☀]    │
├──────────────────────────────────────────────┤
│                                              │
│  MessageList                                 │
│  ┌────────────────────────────────────────┐  │
│  │ [User]: 附近停车场的新能源车占比？      │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ [AI]:                                  │  │
│  │                                        │  │
│  │ ┌── QueryProgress ──────────────────┐  │  │
│  │ │ ██████████████████████████████████ │  │  │
│  │ │ 3/3 完成                          │  │  │
│  │ └───────────────────────────────────┘  │  │
│  │                                        │  │
│  │ ┌ SourceCard A ┐┌ SourceCard B ┐┌ SC C┐│  │
│  │ │✅购物中心 ││✅科技园  ││✅丰台 ││  │
│  │ │ 占用率: 65%  ││ 占用率: 78%  ││占:42%││  │
│  │ │ 新能源: 45%  ││ 新能源: 52%  ││新:38%││  │
│  │ │ [饼图: 小型] ││ [饼图: 小型] ││[小饼]││  │
│  │ └──────────────┘└──────────────┘└──────┘│  │
│  │                                        │  │
│  │ 综合来看，三个停车场的新能源车占比...   │  │
│  │                                        │  │
│  │ ┌──────────────────────────────────┐   │  │
│  │ │  [L1 对比柱状图: 全宽]           │   │  │
│  │ │  三停车场新能源占比对比           │   │  │
│  │ └──────────────────────────────────┘   │  │
│  └────────────────────────────────────────┘  │
│                                              │
├──────────────────────────────────────────────┤
│  QuickQuestions: [附近车位] [新能源占比] ...  │
│  ChatInput: [________________] [发送] [停止] │
└──────────────────────────────────────────────┘
```

### 7.5 图表布局规则

| 图表来源 | 展示位置 | 尺寸 | 说明 |
|----------|----------|------|------|
| L2 生成（饼图/折线图） | 对应 SourceCard 底部 | 小型（150×150） | 单体数据可视化 |
| L2 生成（多个图表） | SourceCard 可折叠 | — | 默认显示第一个，其余点开展示 |
| L1 生成（对比图/汇总图） | AI 消息气泡底部 | 全宽（100%） | 跨物聚合可视化 |

---

## 8. 数据流全景

### 8.1 典型查询完整流程（NEV 占比示例）

以"**方圆五公里内的停车场中，最近三十天的新能源车占比？**"为例：

```
1. 用户在 L1 前端输入问题
2. L1 前端 POST /api/chat → L1 Backend
3. L1 Agent Loop 第1轮:
   a. LLM 决策 → tool_calls: [find_nearby_things]
   b. 执行 find_nearby_things(lat=39.9150, lng=116.4040, radius_km=5, thing_type="parking_lot")
   c. 返回: [parking_lot_a (3.5km), parking_lot_b (2.0km), parking_lot_c (2.9km)]
4. L1 Agent Loop 第2轮:
   a. LLM 决策 → tool_calls: [
        query_parking_lot_a("最近30天新能源车占比"),
        query_parking_lot_b("最近30天新能源车占比"),
        query_parking_lot_c("最近30天新能源车占比")
      ]
   b. asyncio.gather 并行执行:
      ├── source_start: parking_lot_a (→前端)
      ├── source_start: parking_lot_b (→前端)
      ├── source_start: parking_lot_c (→前端)
      ├── (各 L2 Agent 内部 ReAct → query_aggregation → render_chart)
      ├── source_tool_call: parking_lot_a/query_aggregation done (→前端)
      ├── source_chart: parking_lot_a/pie (→前端)
      ├── source_done: parking_lot_a (→前端)
      ├── source_tool_call: parking_lot_b/query_aggregation done (→前端)
      ├── source_chart: parking_lot_b/pie (→前端)
      ├── source_done: parking_lot_b (→前端)
      ├── source_tool_call: parking_lot_c/query_aggregation done (→前端)
      ├── source_chart: parking_lot_c/pie (→前端)
      └── source_done: parking_lot_c (→前端)
   c. 三个 L2 结果返回给 LLM
5. L1 Agent Loop 第3轮:
   a. LLM 决策 → tool_calls: [
        aggregate(data=[A_result, B_result, C_result],
                  operations=[{field:"nev_ratio", func:"avg"}])
      ]
   b. 执行 aggregate → 返回 {avg_nev_ratio: 0.45}
6. L1 Agent Loop 第4轮:
   a. LLM 决策 → tool_calls: [render_chart]
   b. 执行 render_chart → 生成三停车场新能源占比对比柱状图
   c. 发送 SSE: chart (L1 聚合图)
7. L1 Agent Loop 第5轮:
   a. LLM 综合所有结果，决定最终回复 → 流式输出 text token
8. 流结束 → SSE: done
```

### 8.2 简单物查询流程（更简场景）

以"**食堂和医院现在各有多少人？**"为例：

```
1. 用户输入
2. L1 Agent Loop 第1轮:
   a. LLM 决策 → tool_calls: [query_cafeteria, query_hospital]
   b. asyncio.gather:
      ├── GET http://localhost:8010/api/cafeteria/count → {value: 342, capacity: 500}
      └── GET http://localhost:8010/api/hospital/count  → {value: 187, capacity: 300}
   c. source_start → source_done for both (无 L2 内部 tool_call，因为是纯 HTTP)
3. L1 Agent Loop 第2轮:
   a. LLM 决策 → tool_calls: [render_chart]（可选，如需双柱对比图）
   b. 执行 render_chart → 发送 SSE: chart
4. L1 Agent Loop 第3轮:
   a. LLM 直接回复: "中心食堂当前就餐342人(容量500)，中心医院门诊等候187人(容量300)。"
```

---

## 9. 错误处理与降级

### 9.1 L2 调用超时

- **超时时间**：由 `.env` 中 `L2_TIMEOUT_SECONDS` 配置（默认 20 秒）
- **超时行为**：该 L2 物标记为 `source_error`，错误信息 `"查询超时（超过 L2_TIMEOUT_SECONDS 秒）"`
- **对其他物**：不影响。其他并行调用继续执行
- **对 LLM**：超时物的 tool result 为 `{"error": "timeout", "message": "该数据源查询超时"}`，LLM 决定是否重试

### 9.2 L2 物不可用（连接拒绝）

- **行为**：立即标记为 `source_error`，错误信息 `"数据源不可用"`
- **LLM 策略**：使用可用数据继续，在回答中标注不可用的源

### 9.3 部分失败示例

```
用户: 三个停车场占用率如何？
L1 回复:

  朝阳购物中心停车场占用率 65%，科技园停车场占用率 78%。
  社区停车场暂时不可用。
  基于可用数据，两个停车场平均占用率 71.5%。

SourceCard 网格:
┌─────────────────┐┌─────────────────┐┌─────────────────┐
│ ✅ 朝阳购物中心  ││ ✅ 科技园    ││ ❌ 社区      │
│ 占用率 65%      ││ 占用率 78%      ││ 数据源不可用     │
└─────────────────┘└─────────────────┘└─────────────────┘
```

### 9.4 L2 返回错误

- L2 工具返回 `{"error": "..."}` 时
- L1 将该错误透传为 `source_tool_call(status="error")`
- SourceCard 中展示对应工具的错误状态
- L2 的 ReAct 循环会自行重试一次（L2 Agent 的 system prompt 中有错误恢复策略）

### 9.5 L1 自身错误

- L1 工具异常 → 同 ParkingLotAgent 的错误处理，通过 SSE `error` 事件通知前端
- L1 Agent Loop 超过 `MAX_ITERATIONS` 轮 → 返回"抱歉，我暂时无法完成这个查询"

---

## 10. LLM 配置

### 10.1 配置分离

两层 LLM 配置完全独立，各自在自身的 `.env` 中：

```
# L1: l1_agent/.env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro
THINKING_MODE=enabled

# L2: instances/parking_*/.env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-flash
THINKING_MODE=disabled
```

### 10.2 推荐配置

| 层级 | 模型 | thinking_mode | 理由 |
|------|------|---------------|------|
| L1 | `deepseek-v4-pro` | `enabled` | 需要深度推理处理复杂语义和多源编排 |
| L2 | `deepseek-v4-flash` | `disabled` | 单一领域查询 |

> 本仿真项目默认两层都用 DeepSeek V4，但配置体系支持各自独立切换模型。
>
> **模型名验证**：`deepseek-v4-pro` / `deepseek-v4-flash` 为编写 SPEC 时的有效模型名。实现时请通过 `deepseek-v4-api` skill 或 DeepSeek 官方文档确认当前最新的模型 ID，并相应更新 `.env` 文件。
>
> **THINKING_MODE 映射**：`.env` 中的 `THINKING_MODE=enabled|disabled` 字符串值在 `config.py` 中需映射为 DeepSeek API 的 `extra_body={"thinking": {"type": "enabled"}}` 或等效参数。具体映射方式取决于使用的 SDK（OpenAI 兼容模式 vs Anthropic 兼容模式），实现时参考 ParkingLotAgent/backend/agent.py 中的 API 调用方式。

---

## 11. 部署方案

### 11.1 启动脚本

提供 Windows PowerShell 启动脚本：

**`start_all.ps1`**：
```powershell
# 切换到脚本所在目录，确保相对路径正确
Set-Location $PSScriptRoot

# 启动所有服务
Write-Host "Starting DoubleLayerAgent..." -ForegroundColor Green

# SimpleThings
Start-Process -NoNewWindow python `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8010" `
    -WorkingDirectory simple_things
Write-Host "SimpleThings :8010" -ForegroundColor Gray

# ParkingLotAgent instances
foreach ($i in @("a","b","c")) {
    $port = if ($i -eq "a") {8011} elseif ($i -eq "b") {8012} else {8013}
    Start-Process -NoNewWindow python `
        -ArgumentList "-m", "uvicorn", "main:app", "--port", "$port" `
        -WorkingDirectory "instances/parking_$i"
    Write-Host "ParkingLotAgent $i :$port" -ForegroundColor Gray
    Start-Sleep -Seconds 1
}

# L1 Backend
Start-Process -NoNewWindow python `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8001" `
    -WorkingDirectory l1_agent
Write-Host "L1 Agent :8001" -ForegroundColor Yellow

# L1 Frontend
Start-Process -NoNewWindow npm `
    -ArgumentList "run", "dev" `
    -WorkingDirectory frontend
Write-Host "Frontend :5173" -ForegroundColor Cyan

Write-Host "`nAll services started. Press Ctrl+C to stop all." -ForegroundColor Green
```

### 11.2 启动顺序

1. SimpleThings :8010
2. ParkingLotAgent A :8011
3. ParkingLotAgent B :8012
4. ParkingLotAgent C :8013
5. L1 Backend :8001
6. L1 Frontend :5173

> L1 Backend 启动时会读取 `things.yaml` 和 `tools.yaml`，但不主动连接 L2 物（懒连接，仅在调用时连接）。因此启动顺序除了「L2 在 L1 收到请求前启动」外无硬性依赖。

### 11.3 首次运行

```powershell
# 0. 将 ParkingLotAgent 代码复制到三个实例目录（开发准备阶段一次性操作）
$backend = "ParkingLotAgent/backend"
foreach ($i in @("a","b","c")) {
    $dest = "instances/parking_$i"
    # 确保数据目录存在
    New-Item -ItemType Directory -Force -Path "$dest/data" | Out-Null
    Copy-Item "$backend/main.py", "$backend/agent.py", "$backend/config.py", `
        "$backend/db.py", "$backend/sse.py", "$backend/models.py" -Destination $dest
    Copy-Item -Recurse "$backend/tools" -Destination "$dest/tools"
}

# 1. 生成三个停车场的模拟数据
Set-Location ParkingLotAgent/backend
python data_generator.py --name "购物中心停车场" --total-spots 800 --floors 4 `
    --spots-per-floor "200,200,200,200" `
    --nev-weights "55,25,12,8" --db-path ../../instances/parking_a/data/parking_a.db --days 120
python data_generator.py --name "科技园停车场" --total-spots 500 --floors 3 `
    --spots-per-floor "167,167,166" `
    --nev-weights "50,30,12,8" --db-path ../../instances/parking_b/data/parking_b.db --days 120
python data_generator.py --name "社区停车场" --total-spots 1200 --floors 5 `
    --spots-per-floor "240,240,240,240,240" `
    --nev-weights "60,20,12,8" --db-path ../../instances/parking_c/data/parking_c.db --days 120

# 2. 安装依赖
Set-Location ../..
Set-Location l1_agent; pip install -r requirements.txt; Set-Location ..
Set-Location simple_things; pip install -r requirements.txt; Set-Location ..
Set-Location frontend; npm install; Set-Location ..

# 3. 配置 .env 文件（API Key 等）

# 4. 启动
.\start_all.ps1
```

---

## 12. 文件结构

```
DoubleLayerAgent/
├── docs/
│   ├── goal.md                     # 项目目标
│   └── SPEC.md                     # 本文件：完整技术规范
│
├── config/
│   ├── things.yaml                 # L2 物注册表（元数据+端点）
│   └── tools.yaml                  # L2 物 tool schemas（OpenAI 格式）
│
├── l1_agent/                       # Layer 1：编排 Agent
│   ├── main.py                     # FastAPI 入口：POST /api/chat (SSE)、GET /api/health
│   ├── agent.py                    # 扩展 ReAct Agent Loop（并行 tool_calls）
│   ├── config.py                   # 环境变量加载 + things.yaml/tools.yaml 加载 + 校验
│   ├── sse.py                      # SSE 事件发送器（扩展：source_* 事件）
│   ├── sse_receiver.py             # SSE 流解析器（接收 L2 事件）
│   ├── models.py                   # Pydantic 请求/响应模型
│   ├── bridge.py                   # L2 物桥接层：HTTP/SSE Tool Executor 工厂
│   ├── tools/
│   │   ├── __init__.py             # 工具注册：L1 自有 + L2 bridge 动态生成
│   │   ├── geo.py                  # find_nearby_things (Haversine)
│   │   ├── aggregate.py            # 结构化多源数据聚合
│   │   └── chart.py                # render_chart (L1 版)
│   ├── .env
│   └── requirements.txt
│
├── instances/                      # Layer 2：ParkingLotAgent 实例
│   ├── parking_a/
│   │   ├── main.py                 # 从 ParkingLotAgent/backend/ 复制（开发准备阶段一次性）
│   │   ├── agent.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── sse.py
│   │   ├── models.py
│   │   ├── tools/
│   │   ├── data/
│   │   │   └── parking_a.db
│   │   └── .env
│   ├── parking_b/                  # 同上结构
│   └── parking_c/                  # 同上结构
│
├── simple_things/                  # Layer 2：简单物服务
│   ├── main.py                     # FastAPI + /api/cafeteria/count + /api/hospital/count + /api/health
│   ├── .env                        # CAFETERIA_CAPACITY + HOSPITAL_CAPACITY（main.py 通过 load_dotenv 读取）
│   └── requirements.txt
│
├── frontend/                       # Layer 1 前端
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── index.css               # Tailwind 全局样式
│   │   ├── components/
│   │   │   ├── ChatLayout.tsx      # 重写：新根布局
│   │   │   ├── Header.tsx          # 改造：标题适配
│   │   │   ├── MessageList.tsx     # 改造：SourceCard 渲染
│   │   │   ├── UserMessage.tsx     # 复用
│   │   │   ├── AssistantMessage.tsx # 改造：SourceCard 网格 + L1 图表区
│   │   │   ├── SourceCard.tsx      # 新建：L2 物查询状态卡片
│   │   │   ├── QueryProgress.tsx   # 新建：多源并行进度条
│   │   │   ├── ToolCallCard.tsx    # 复用
│   │   │   ├── ChartWidget.tsx     # 复用
│   │   │   ├── ChatInput.tsx       # 复用
│   │   │   ├── QuickQuestions.tsx  # 改造：示例问题适配
│   │   │   ├── EmptyState.tsx      # 复用
│   │   │   └── ThemeToggle.tsx     # 复用
│   │   ├── hooks/
│   │   │   ├── useChat.ts          # 重写：多源扇出状态机
│   │   │   └── useTheme.tsx        # 复用
│   │   └── types/
│   │       └── chat.ts             # 扩展：SourceState 等类型
│   ├── index.html
│   ├── vite.config.ts              # 代理 /api → localhost:8001
│   ├── tailwind.config.js
│   └── package.json
│
├── ParkingLotAgent/                # 参考项目（仅作源码参考，不参与编译运行；项目完成后可删除）
│   ├── backend/
│   │   ├── main.py
│   │   ├── agent.py                # System prompt 适配为机器面向
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── sse.py
│   │   ├── models.py
│   │   ├── data_generator.py       # 参数化增强
│   │   └── tools/
│   ├── frontend/                   # 保留但本项目中不使用
│   ├── data/
│   └── docs/
│
├── start_all.ps1                   # Windows PowerShell 启动脚本
└── README.md
```

### 12.1 关键 Python 依赖

| 组件 | 依赖（requirements.txt 核心条目） |
|------|----------------------------------|
| l1_agent | `fastapi`, `uvicorn`, `httpx`, `openai`, `pydantic`, `python-dotenv`, `pyyaml` |
| instances/parking_* | 同 ParkingLotAgent/backend/requirements.txt：`fastapi`, `uvicorn`, `httpx`, `openai`, `pandas`, `pydantic`, `python-dotenv` |
| simple_things | `fastapi`, `uvicorn`, `python-dotenv` |

> `l1_agent` 额外需要 `pyyaml` 解析 `things.yaml` 和 `tools.yaml`。`httpx` 用于 L2 物的 HTTP/SSE 调用。parking 实例需要 `pandas` 用于 `query_aggregation` 的滚动平均计算。

---

## 13. 决策记录

### 13.1 架构

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| A1 | L1-L2 通信协议 | 混合模式（Agent→SSE，简单物→HTTP） | 兼顾灵活性和简单性，LLM 感知不到底层差异 |
| A2 | 物的注册与发现 | 静态配置文件 | 仿真验证不需要动态注册，YAML 简单透明 |
| A3 | L2 前端去留 | 完全拆除 | L1 是唯一用户入口，L2 仅保留后端/Agent 核心 |
| A4 | Tool Schema 生成 | 静态手写 (tools.yaml) | 与静态配置一致，手写可控 |
| A5 | L2 进程模型 | 独立进程 | 接近真实微服务架构，验证跨进程 Agent 调用 |
| A6 | 空间查询 | 专用 geo 工具 (Haversine) | LLM 算距离不可靠，专用工具精确可控 |

### 13.2 仿真规模

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| B1 | L2 物数量 | 5 个（3 Agent 停车场 + 2 简单物） | 覆盖双层 Agent、混合协议、多源聚合三大验证点 |
| B2 | 停车场差异化 | 极简（name + total_spots） | 容量差异已产生足够的占用率差异 |
| B3 | 简单物接口 | 纯 int | 验证混合协议的最小实现 |
| B4 | 停车场代码 | 同代码多实例 | 通过 .env 参数化 |

### 13.3 数据与聚合

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| C1 | 聚合策略 | 专用 aggregate 工具 | LLM 数值计算不可靠，Python 精确计算 |
| C2 | 聚合工具设计 | 结构化聚合 (field + func) | 可靠、可预测、易于 LLM 正确调用 |
| C3 | 图表生成 | 两层各自生成 | L2 单体图增强信息密度，L1 对比图统一视角 |
| C4 | L2 图表布局 | 嵌入 SourceCard 底部 | 层级分明，来源清晰 |
| C5 | L1 图表布局 | AI 消息气泡全宽 | 聚合结果突出展示 |

### 13.4 Agent 设计

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| D1 | L1 Agent Loop | 复用并扩展 ParkingLotAgent 的 ReAct | 核心改动为并行执行和 HTTP bridge，其余逻辑（LLM 调用、消息管理、SSE 发送）可直接复用 |
| D2 | 并行扇出 | LLM 原生并行 tool_calls | 通用、灵活，LLM 自主决定并行度 |
| D3 | L2 Agent 适配 | System prompt 改为机器面向 | 减少不必要的自然语言修饰，优先结构化数据 |
| D4 | L2 API 端点 | 复用 /api/chat | L2 代码零 API 改动 |
| D5 | L1 自有工具定义 | Python 代码中 | 与执行逻辑紧邻，tools.yaml 仅存 L2 bridge schema |

### 13.5 通信与流式

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| E1 | SSE 透传策略 | 双层混合透传 | L1 工具调用包装（层级清晰）+ SourceCard 嵌套 L2 过程（过程可见） |
| E2 | L2 文本 token | 不透传 | L1 是唯一自然语言出口 |
| E3 | L2 工具状态 | 透传（source_tool_call） | 用户能看到 L2 的查询过程 |
| E4 | L2 图表 | 透传（source_chart） | 在 SourceCard 内渲染 |

### 13.6 错误处理

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| F1 | L2 超时 | 20 秒 | Agent 类物需要足够时间完成 ReAct 循环 |
| F2 | 部分失败 | 返回部分结果 + 标注失败源 | 可用性优先于一致性 |
| F3 | 重试策略 | 失败后不自动重试，LLM 决定 | LLM 根据上下文判断是否值得重试 |

### 13.7 前端

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| G1 | 组件策略 | 复用核心组件，重写布局 | 保留成熟组件（Chart/ToolCard/Input），重构编排层 |
| G2 | 多源 UI | 内嵌卡片式 (SourceCard 网格) | 信息紧凑、上下文内聚 |
| G3 | 技术栈 | React 18 + TS + Tailwind + ECharts | 与 ParkingLotAgent 一致 |

### 13.8 LLM

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| H1 | 模型配置 | 两层可配置 | 灵活切换，开发和生产可用不同模型 |
| H2 | 默认模型 | DeepSeek V4（两层） | 与 ParkingLotAgent 一致，减少变量 |

### 13.9 部署

| # | 决策 | 选择 | 理由 |
|----|------|------|------|
| I1 | 部署方案 | 启动脚本 (PowerShell) | 仿真验证不需要容器化开销 |
| I2 | 端口分配 | L1:8001, L2:8010-8013, 前端:5173 | 不与 ParkingLotAgent 原始端口 8000 冲突 |

---

> **文档状态**：已确认  
> **下一步**：按此规范实现。

### 开发顺序建议

> 下表整合了开发步骤与现有代码改造点（"⚠️ 改造"标注项需修改 ParkingLotAgent 已有代码）。

1. **环境准备**（一次性）：
   - ⚠️ `data_generator.py` 参数化改造 — 当前硬编码，需增加 `argparse` CLI 参数（`--name`、`--total-spots`、`--floors`、`--spots-per-floor`、`--nev-weights`、`--db-path`、`--days`）
   - ⚠️ ParkingLotAgent `agent.py` System Prompt 适配 — 当前面向最终用户，需改为「面向机器/上层 Agent」角色 + JSON 摘要要求
   - ⚠️ `NEV_WEIGHTS` 配置外部化 — 当前硬编码 `55,25,12,8`，改为 `.env` 可配、CLI 可传
   - 将 ParkingLotAgent/backend 代码复制到三个 instances 目录
   - 生成三个停车场的独立 `.db` 数据文件
2. **配置体系**：`things.yaml` + `tools.yaml` + 各层 `.env`
3. **简单物**：`simple_things/main.py`（食堂 + 医院）
4. **L2 适配**：确认三个 ParkingLotAgent 实例可按新 System Prompt 正确响应
5. **L1 bridge**：`bridge.py` SSE 接收器 + HTTP 客户端
6. **L1 Agent Loop**：扩展 ReAct（并行 tool_calls + L2 bridge tools）
7. **前端 useChat 状态机**：多源扇出
8. **前端组件**：SourceCard + QueryProgress + 布局改造

> 端口说明：ParkingLotAgent 原占用 :8000，本项目 L1 使用 :8001（不冲突），ParkingLotAgent 实例使用 :8011-8013。
