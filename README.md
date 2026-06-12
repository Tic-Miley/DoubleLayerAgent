# DoubleLayerAgent

双层 AI Agent 仿真系统 —— Layer 1 编排 Agent 理解用户语义、并行调用 Layer 2 多个异构数据源（Agent 停车场 + REST 接口），在 L1 层做结构化聚合与对比可视化。

## 架构

```
用户 (浏览器 :5173)
  │ SSE
  ▼
Layer 1 编排 Agent (:8001)
  │  并行调用 (SSE / HTTP)
  ├──→ ParkingLotAgent A (:8011) — 购物中心停车场 (800 车位)
  ├──→ ParkingLotAgent B (:8012) — 科技园停车场 (500 车位)
  ├──→ ParkingLotAgent C (:8013) — 社区停车场 (1200 车位)
  ├──→ 中心食堂 (:8010 /api/cafeteria/count)
  └──→ 中心医院 (:8010 /api/hospital/count)
```

- **L1**：城市数据整合助手，自主选择 L2 数据源、并行查询、聚合结果、生成对比图表
- **L2 Agent 类**：完整 ReAct Agent，通过 SQL 工具回答停车场相关问题
- **L2 REST 类**：无状态 HTTP 接口，返回人数数据
- **前端**：React + ECharts，支持多源实时状态卡片、L2 内部过程透传、L1 对比图表

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- Windows PowerShell（启动脚本）

### 2. 安装依赖

```bash
pip install fastapi uvicorn httpx openai pydantic python-dotenv pyyaml pandas
cd frontend && npm install
```

### 3. 配置 API Key

编辑以下 `.env` 文件，将 `sk-xxx` 替换为你的 DeepSeek API Key：

```
l1_agent/.env
instances/parking_a/.env
instances/parking_b/.env
instances/parking_c/.env
```

### 4. 启动

```powershell
.\start_all.ps1
```

浏览器访问 **http://localhost:5173**。

### 5. 重新生成数据（可选）

仿真数据以生成当天的日期为基准。如果数据过期，运行：

```powershell
.\scripts\regenerate_data.ps1
```

> 运行前请先停止所有 ParkingLotAgent 实例，否则 SQLite 会锁文件。

## 示例查询

| 查询 | 预期效果 |
|------|----------|
| "附近停车场新能源车占比" | SourceCard 网格（3 停车场）+ L1 对比柱状图 |
| "食堂和医院各有多少人" | 两个 SourceCard + 可选对比图 |
| "方圆5公里有哪些停车场" | 空间筛选卡片 + 各停车场数据 |
| "三个停车场的占用率对比" | 并行查询 + 聚合 + 对比图表 |

## 项目结构

```
DoubleLayerAgent/
├── l1_agent/            # Layer 1 编排 Agent (FastAPI :8001)
├── instances/           # Layer 2 ParkingLotAgent ×3 (:8011-8013)
├── simple_things/       # Layer 2 简单物 (:8010)
├── frontend/            # React 前端 (Vite :5173)
├── config/              # things.yaml + tools.yaml
├── scripts/             # 数据重新生成脚本
├── start_all.ps1        # 一键启动脚本
└── docs/                # 技术规范
```

## 许可证

MIT
