# DoubleLayerAgent 技术概览

> 双层 AI Agent 仿真系统 — 验证双层编排、异构物统一调用、多源聚合、流式透传和双层图表生成五大技术点。

## 1. 架构全景

```
                         浏览器 (:5173)
                              │
                     POST /api/chat (SSE)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  L1 编排 Agent (:8001)                       │
│                                                              │
│  agent_loop()                     tools/                     │
│  ┌──────────────────┐    ┌──────────────────────────┐       │
│  │ Extended ReAct    │    │ find_nearby_things (geo) │       │
│  │ asyncio.gather()  │    │ aggregate (stats)        │       │
│  │ parallel tool exec│    │ render_chart (L1 chart)  │       │
│  └──────┬───────────┘    │ query_parking_lot_* (L2) │       │
│         │                │ query_cafeteria (L2)     │       │
│         │                │ query_hospital (L2)      │       │
│         │                └──────────────────────────┘       │
│         │                                                    │
│         │  bridge.py                                         │
│         │  ┌──────────────────────────────┐                  │
│         │  │ query_agent_thing()  → SSE   │                  │
│         │  │ query_rest_thing()   → HTTP  │                  │
│         │  │ _extract_json()              │                  │
│         │  └──────────────────────────────┘                  │
└─────────┼──────┼──────┼──────┼──────────┼───────────────────┘
          │ SSE  │ SSE  │ SSE  │ HTTP GET │ HTTP GET
          ▼      ▼      ▼      ▼          ▼
     ┌────────┐┌────────┐┌────────┐┌──────────────────┐
     │Parking ││Parking ││Parking ││ SimpleThings      │
     │Lot A   ││Lot B   ││Lot C   ││ (:8010)           │
     │:8011   ││:8012   ││:8013   ││ /api/cafeteria/   │
     │ReAct   ││ReAct   ││ReAct   ││ /api/hospital/    │
     │5 tools ││5 tools ││5 tools │└──────────────────┘
     │SQLite  ││SQLite  ││SQLite  │
     └────────┘└────────┘└────────┘
```

6 个进程，L2 物分为两类：Agent 类（SSE 通信，5 个 SQL 工具自主决策）和 REST 类（HTTP GET，无状态随机数据）。

## 2. 设计决策

### 2.1 为何手写 ReAct 而非用 LangChain

L1 仅有 8 个工具、L2 仅有 5 个工具，LangChain 的抽象层对 < 10 工具的 Agent 系统弊大于利。手写循环约 180 行，完全可控：消息格式、`asyncio.gather` 并行度、错误处理路径都直接可见。

### 2.2 为何 L2 Agent 通过 SSE 而非函数调用

三个 ParkingLotAgent 是**独立进程**，模拟真实微服务架构。它们有自己的 LLM API Key、数据库、ReAct 循环。L1 通过 HTTP POST 发送自然语言查询，L2 自行决定调用哪些工具、如何回答。这验证了"Agent 调用 Agent"的技术可行性——L1 不需要知道 L2 有哪些 SQL 工具。

### 2.3 为何简单物用 HTTP GET

食堂和医院是纯数据源（一个 int），不需要 Agent 的推理能力。HTTP GET 足以表达"查询当前人数"的语义，同时验证了 L1 统一调用异构协议的能力：底层是 SSE 还是 HTTP，LLM 感知不到。

### 2.4 为何用专用工具而非 LLM 直接做计算

空间距离计算（Haversine）和统计聚合（sum/avg/std）LLM 不可靠——会算错、会漏边界情况。专用 Python 工具精确且可预期。`aggregate` 工具支持嵌套路径（`structured.occupancy_rate`）、自动跳过 error 项、统计缺失计数，这些 LLM 自己做远比调用工具容易出错。

### 2.5 为何两层各自生成图表

L2 生成单体图表（如一个停车场的占用率饼图），嵌入对应 SourceCard，提供**微观细节**。L1 生成跨物对比图表（如三个停车场的新能源占比柱状图），全宽展示，提供**宏观视角**。两层图表互不冲突，信息密度最大化。

## 3. 通信协议

### 3.1 SSE 事件体系

前后端通过 SSE (Server-Sent Events) 实现实时推送，协议包含 10 种事件：

| 事件 | 来源 | 含义 |
|------|------|------|
| `tool_call` | L1 | L1 自有工具执行状态 |
| `text` | L1 | LLM 流式输出 token |
| `chart` | L1 | L1 生成的聚合图表 |
| `done` | L1 | 单次对话流结束 |
| `error` | L1 | L1 内部错误 |
| `source_start` | L1→前端 | 开始查询某个 L2 物 |
| `source_tool_call` | L1→前端 | L2 内部工具调用（透传） |
| `source_chart` | L1→前端 | L2 生成的图表（透传） |
| `source_done` | L1→前端 | L2 查询完成 |
| `source_error` | L1→前端 | L2 查询失败/超时 |

关键设计：`source_*` 事件始终携带 `message_id`，前端通过它将事件路由到正确的 `AssistantMessage.sources[]` 条目。这使得多个 L2 物并发查询时事件帧不会互相干扰。

### 3.2 L1 ↔ L2 通信

L1 不直接访问 L2 的工具或数据库。Protocol 完全是自然语言：

```
L1: POST /api/chat  {message: "最近30天新能源车占比"}
L2: SSE 流 → tool_call(开始查询) → text(token) → done(最终文本 + 末尾 JSON)
```

L2 的 System Prompt 要求回复末尾附带结构化 JSON 摘要。L1 的 `_extract_json()` 从 L2 最终文本中提取此 JSON，存入 `structured` 字段，供 `aggregate` 工具消费，无需 LLM 手动解析 L2 的回复。

## 4. 关键模块详解

### 4.1 L1 Agent Loop (`l1_agent/agent.py`)

核心改动相对 ParkingLotAgent 的 ReAct：

**并行 tool_calls 执行**：同一轮 LLM 返回 N 个 `tool_calls` 时，用 `asyncio.gather` 并行执行。这是实现 "同时查询三个停车场" 的机制。

```
LLM 决策 → tool_calls: [query_parking_lot_a, query_parking_lot_b, query_parking_lot_c]
              │                │                │
              └────────────────┼────────────────┘
                               │
                     asyncio.gather(exec_a, exec_b, exec_c)
                               │
                               ▼
              三个 SSE 事件流同时注入共享的 asyncio.Queue
```

**桥接工具识别**：通过 `BRIDGE_TOOL_NAMES` 集合识别 L2 工具，走 bridge 层。L1 自有工具（`find_nearby_things`、`aggregate`、`render_chart`）走本地执行路径。

**消息分离**：每轮 LLM 只允许返回 `text` 或 `tool_calls`，不可同时。若 LLM 同时返回两者，`content` 被丢弃，仅执行 `tool_calls`。

完整数据流：

```
用户消息
  ↓
LLM 非流式决策（tool_choice=auto）
  ↓
LLM 返回 tool_calls?
  ├── 是 → asyncio.gather(执行所有工具)
  │         ├── L2 bridge 工具 → HTTP POST/GET → SSE 解析 → 返回结构化 dict
  │         ├── find_nearby_things → Haversine 计算 → 返回物列表
  │         ├── aggregate → 统计计算 → 返回结果
  │         └── render_chart → ECharts 校验 → chart_id + option
  │       → 工具结果追加到 messages → 返回 LLM 下一轮决策
  └── 否 → LLM 流式生成最终回答
            → SSE: text (逐 token)
            → SSE: done
```

### 4.2 Bridge 层 (`l1_agent/bridge.py`)

两个核心函数，统一返回结构以支持 `aggregate`：

```python
# Agent 物（SSE）
query_agent_thing(thing, message, history, message_id, send_sse)
  → POST /api/chat
  → 逐行解析 SSE 流 (event: / data: / 空行)
  → 每个 L2 事件通过 send_sse.source_*() 透传给前端
  → 从 final_text 提取 JSON → structured 字段
  → return {source, structured, summary, tool_results, charts}

# REST 物（HTTP GET）
query_rest_thing(thing, message_id, send_sse)
  → GET /api/*/count
  → 包装为 {source, structured: {value, capacity}, summary}
```

**`_extract_json` 算法**：扫描文本中所有顶级 `{...}` 对（用深度计数器匹配括号），逐一 `json.loads()`，取最后一个合法 dict。L2 的 System Prompt 要求 JSON 放在末尾，取最后一个利用了这一点。

**并发安全**：`SSESender._send()` 内部使用 `asyncio.Lock`，确保并发 L2 响应时事件帧不会在 Queue 中交错。

### 4.3 L1 自有工具

#### `find_nearby_things` (`tools/geo.py`)

- 从 `things.yaml` 加载所有物的经纬度
- 使用 Haversine 公式（地球半径 6371 km）计算球面距离
- 按 `radius_km` 筛选，按距离升序排列
- 返回 `{things: [{id, name, type, lat, lng, distance_km}]}`
- 不向 LLM 暴露 `endpoint` 等内部协议信息

#### `aggregate` (`tools/aggregate.py`)

- 从 L2 返回的 `structured` 字典中提取字段进行跨源统计
- 支持嵌套路径访问：`"structured.occupancy_rate"` → 逐层 `dict.get(key)`
- 自动跳过含 `error` 键的数据项（来自 L2 失败调用）
- 自动跳过 `None` 值，记录 `skipped_count`
- 数据上限 500 条，超出截断并标记 `truncated: true`
- 支持 7 种聚合函数：`sum | avg | min | max | count | median | std`

#### `render_chart` (`tools/chart.py`)

- 复用 ParkingLotAgent 的 ECharts option 校验 + 自动修复逻辑
- 新增 `chart_title` 参数：若 option 中无 `title.text` 则自动注入
- chart_id 格式：`l1_{timestamp_ms}_{random_6chars}`，前端据此去重渲染

### 4.4 L2 ParkingLotAgent (`instances/parking_*/`)

三个实例运行完全相同的代码，仅通过 `.env` 差异化：

| 参数 | A | B | C |
|------|---|---|---|
| PORT | 8011 | 8012 | 8013 |
| PARKING_NAME | 购物中心 | 科技园 | 社区 |
| TOTAL_SPOTS | 800 | 500 | 1200 |
| FLOORS | 4 | 3 | 5 |
| SPOTS_PER_FLOOR | 200×4 | 167,167,166 | 240×5 |
| NEV_WEIGHTS | 55/25/12/8 | 50/30/12/8 | 60/20/12/8 |

每个实例配备 5 个工具：`get_config`、`query_aggregation`（核心，覆盖 90% 查询，替代旧 6 个独立工具）、`get_vehicle`、`sql_query`（只读 SQL 兜底）、`render_chart`。

数据由 `scripts/regenerate_data.py` 一次性生成：泊松到达 + 指数停车时长 × 120 天，容量感知时间线模拟保证任意时刻在场数 ≤ 总车位数。

### 4.5 前端 (`frontend/`)

**多源扇出状态机** (`hooks/useChat.ts`)：

```
SourceState: PENDING → (source_start) → RUNNING
                → (source_tool_call*)   → 累积 toolCalls[]
                → (source_chart*)       → 累积 charts[]
                → (source_done)         → DONE
                → (source_error)        → ERROR
```

所有 `source_*` 事件携带 `message_id`，通过它定位到正确的 `AssistantMessage`，再通过 `source_id` 定位 `SourceState` 进行浅合并更新。

**新增组件**：
- `SourceCard` — 单个 L2 物的状态卡片，含状态图标（等待/运行/完成/错误）、L2 摘要、L2 工具调用列表、L2 小型图表
- `QueryProgress` — 多源并行查询整体进度条

**复用组件**（从 ParkingLotAgent 复制）：`ChartWidget`（新增 `compact` 模式用于小尺寸 L2 图表）、`ToolCallCard`、`ChatInput`、`ThemeToggle`、`UserMessage`、`EmptyState`

## 5. 数据流示例

以查询"方圆 5 公里停车场的新能源车占比"为例，完整 5 轮 ReAct：

```
轮次 1: LLM → tool_calls: [find_nearby_things(lat, lng, radius_km=5, type="parking_lot")]
         结果: [parking_lot_a(3.5km), parking_lot_b(2.0km), parking_lot_c(2.9km)]

轮次 2: LLM → tool_calls: [query_pl_a("最近30天新能源车占比"),
                             query_pl_b("最近30天新能源车占比"),
                             query_pl_c("最近30天新能源车占比")]
         asyncio.gather 并行执行:
           ├── SSE → L2 A: source_start → source_tool_call → source_chart → source_done
           ├── SSE → L2 B: source_start → source_tool_call → source_chart → source_done
           └── SSE → L2 C: source_start → source_tool_call → source_chart → source_done
         结果: [{source:A, structured:{nev_ratio:0.45, ...}},
                {source:B, structured:{nev_ratio:0.52, ...}},
                {source:C, structured:{nev_ratio:0.38, ...}}]

轮次 3: LLM → tool_calls: [aggregate(data=[A,B,C], ops=[{field:"structured.nev_ratio", func:"avg"}])]
         结果: {avg_structured.nev_ratio: 0.45}

轮次 4: LLM → tool_calls: [render_chart(option={bar chart of three nev ratios})]
         → SSE: chart (L1 对比柱状图)

轮次 5: LLM → 流式 text: "附近三个停车场的新能源车平均占比 45%..."
         → SSE: done
```

## 6. 错误处理

| 场景 | L1 行为 | 前端表现 |
|------|---------|----------|
| L2 超时（> 20s） | 该 source 标记 error，其余继续 | 对应 SourceCard 显示 "查询超时" |
| L2 连接拒绝 | 立即标记 source_error | 对应 SourceCard 显示 "数据源不可用" |
| L2 返回错误事件 | 透传 source_error | SourceCard 显示 L2 错误信息 |
| L1 工具异常 | SSE error 事件 | 全局错误提示 |
| 部分源失败 | LLM 用可用数据继续，文本中标注不可用源 | 错误卡片 + 正常卡片并存 |
| 超过 8 轮迭代 | 返回 "暂时无法完成" | 正常结束 |

## 7. 配置体系

配置在三个层面：

1. **`.env`**（进程级）：API Key、端口、停车场参数。L1 和各 L2 实例独立配置，两层可使用不同模型
2. **`things.yaml`**（物注册表）：每个 L2 物的 id、名称、经纬度、协议类型、endpoint URL
3. **`tools.yaml`**（桥接工具 schema）：每个 L2 物在 L1 中暴露为 OpenAI function-calling 格式的 tool schema

L1 启动时校验 `things.yaml` ↔ `tools.yaml` 双向一致性（每个 thing_id 在对方中必须存在），失败则 `sys.exit(1)` 并打印具体冲突。

## 8. 技术栈

| 层 | 技术 | 选型理由 |
|----|------|----------|
| L1 后端 | FastAPI + Python | 与 L2 一致，减少技术栈碎片 |
| L2 后端 | FastAPI + Python | 继承 ParkingLotAgent |
| LLM 调用 | OpenAI SDK → DeepSeek V4 | DeepSeek 兼容 OpenAI 协议 |
| L1↔L2 通信 | httpx (SSE 流 + HTTP) | 异步流式 HTTP 客户端 |
| 计算 | Haversine (球面距离) + NumPy 风格统计 | LLM 不可靠，专用工具精确 |
| 前端 | React 18 + TypeScript + Vite | 单页应用，HMR 开发体验 |
| 样式 | Tailwind CSS | AI 友好的 utility class |
| 图表 | ECharts | LLM 可直接生成 option JSON，无需中间 DSL |
| 数据库 | SQLite (WAL 模式) | 零配置，单文件，仿真无须独立 DB 服务 |
| 配置 | YAML + python-dotenv | YAML 用于结构化物注册，.env 用于密钥和简单参数 |
