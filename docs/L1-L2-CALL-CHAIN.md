# L1 Agent 调用 L2 Agent 全链路说明

## 1. 能力感知

L1 通过三个信息源了解 L2：

| 来源 | 内容 | 作用 |
|------|------|------|
| `config/things.yaml` | 物的 id、type、location、protocol、endpoint | 元数据注册，决定走 agent_sse 还是 http_rest |
| `config/tools.yaml` | 每个 L2 的 OpenAI function-calling schema（name、description、parameters） | 告诉 LLM 这个工具能做什么、返回什么字段 |
| System Prompt | 自然语言说明书："L2 Agent 通过 SQL 工具几乎能回答所有停车场相关问题" | 高层行为指引 |

`l1_agent/config.py` 在 import 时执行 `validate_config()`：things.yaml ↔ tools.yaml 双向一致性校验，不一致则 `sys.exit(1)`。

## 2. 调用决策（LLM 自主）

`l1_agent/agent.py` 的 ReAct 循环中：

```python
response = await client.chat.completions.create(
    messages=messages,
    tools=TOOL_SCHEMAS,    # 所有工具（L1 自有 + L2 bridge）
    tool_choice="auto",    # LLM 自己决定调哪个
)
```

- LLM 根据 tools.yaml 中的 `description` 判断该调哪个 L2
- 同一轮可返回多个 `tool_calls`（如同时查 3 个停车场）
- 如果 LLM 同时返回 `tool_calls` 和 `content`，丢弃 content，只处理 tool_calls

## 3. 请求发起（bridge 分发）

`BRIDGE_TOOL_NAMES` 命中的工具走 `_execute_bridge_tool()` → 根据 `protocol` 分发：

- **agent_sse**（停车场）：POST `http://localhost:8011/api/chat`，body=`{"message": "...", "history": [...]}`，通过 httpx streaming 接收 SSE
- **http_rest**（食堂/医院）：GET `http://localhost:8010/api/...`，直接拿 JSON

## 4. 响应解析

### Agent SSE 路径

1. **SSE 事件流解析**（`bridge.py:109-169`）：逐行读 SSE 流，按 `event:`/`data:`/空行 协议解析。L2 的 `tool_call`、`chart` 事件被包装为 `source_*` 事件透传给前端
2. **结构化 JSON 提取**（`bridge.py:27-64`）：`_extract_json()` 算法 — 找所有顶级 `{...}` 对，逐个 `json.loads()`，取**最后一个**合法 dict（L2 System Prompt 要求 JSON 摘要放在末尾）
3. **返回结构**：
```python
{
    "source": "parking_lot_a",
    "tool_results": [...],      # L2 内部所有 tool_call 事件
    "charts": [...],            # L2 生成的图表
    "chart_types": ["pie"],     # 去重后的图表类型
    "summary": "...",           # L2 完整文本回复
    "structured": {             # 从 final_text 提取的 JSON
        "occupancy_rate": 0.65,
        "nev_ratio": 0.45,
        ...
    }
}
```

### HTTP REST 路径

直接 `resp.json()` → 包装为 `{source, structured: {value, capacity}, summary}`

## 5. 多轮循环

### L1 层（`agent.py:229-400`）

```
MAX_ITERATIONS=8 轮
每轮: LLM 决策 → 并行执行 tool_calls (asyncio.gather) → 结果追加到 messages → 回到 LLM
直到 LLM 返回纯文本（不再调工具）
```

- 同一轮的多个 tool_calls **并行执行**（asyncio.gather）
- render_chart 连续失败 2 次 → 熔断，强制转为纯文字分析

### L2 层（`instances/parking_a/agent.py:176-316`）

L1 调用 L2 时，L2 内部跑**完整的 ReAct 循环**（自己的 MAX_ITERATIONS 轮），每轮：LLM 决策 → 顺序执行工具 → 回到 LLM → 最终输出文本 + JSON 摘要

L2 的每一步（tool_call、chart）通过 SSE 实时推送给 L1，L1 解析后透传给前端。

## 完整时序示例

用户："三个停车场各剩多少车位，哪个最空？"

```
L1 Turn 0: LLM 决策 → 3 个 tool_calls
  ├─ query_parking_lot_a("当前空余车位") ──并行──▶ L2-A (内部 ReAct 1-3 轮)
  ├─ query_parking_lot_b("当前空余车位") ──并行──▶ L2-B (内部 ReAct 1-3 轮)
  └─ query_parking_lot_c("当前空余车位") ──并行──▶ L2-C (内部 ReAct 1-3 轮)

L1 Turn 1: LLM 收到 3 个 structured JSON → aggregate()
L1 Turn 2: LLM 看到聚合结果 → render_chart() + 最终文本
```

## 关键设计原则

1. **L2 的能力完全建模为 Function Calling 工具**：LLM 通过 tool description 理解 L2 能做什么
2. **L2 内部 ReAct 对 L1 透明**：L1 只是等 L2 跑完，拿到 final_text 中的 JSON
3. **并行 fan-out**：同一轮多个 L2 调用通过 asyncio.gather 并行执行
4. **SSE 事件透传**：L2 的工具调用、图表生成实时推送到前端
5. **结构化 JSON 契约**：L2 System Prompt 要求末尾附 JSON 摘要，L1 通过 `_extract_json()` 提取
