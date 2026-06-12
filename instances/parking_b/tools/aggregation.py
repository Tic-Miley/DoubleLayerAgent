"""
工具: query_aggregation — 通用参数化聚合查询。

一个工具替代原有的 T1(get_current_vacancy)、T2(get_nev_ratio)、
T3(get_trend)、T4(get_floor_status)、T5(get_hourly_distribution)、
T7(get_summary_stats) 共六个工具。

通过 active_only + group_by + date_from/date_to + include_duration
参数组合覆盖所有一维聚合场景。

设计原则:
- 操作原语驱动: 每个参数对应数据库查询的一个正交维度
- 参数化扩展: 新分组维度只需加 group_by 枚举值
- 统一返回结构: 所有路径返回相同 JSON schema
- 内置派生指标: ratio, occupancy_rate, rolling_avg_7d 等由工具计算
"""

import datetime
from typing import Any, Optional

import pandas as pd

from db import get_db

# ── 常量映射 ────────────────────────────────────────────

VEHICLE_TYPE_LABELS = {
    "ICE": "燃油车",
    "BEV": "纯电动",
    "PHEV": "插电混动",
    "HEV": "油电混动",
}

DAY_OF_WEEK_LABELS = {
    "0": "周日", "1": "周一", "2": "周二", "3": "周三",
    "4": "周四", "5": "周五", "6": "周六",
}

# active_only=True 时允许的 group_by
ACTIVE_GROUP_BY = {None, "vehicle_type", "floor"}

# active_only=False 时允许的 group_by
HISTORY_GROUP_BY = {None, "vehicle_type", "floor", "date", "hour", "day_of_week", "month"}


# ── 主入口 ──────────────────────────────────────────────

def query_aggregation(
    active_only: bool = True,
    group_by: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_duration: bool = False,
) -> dict:
    """
    通用参数化聚合查询 —— 一个工具 = 旧 T1+T2+T3+T4+T5+T7。

    Args:
        active_only: True=仅在场车辆(当前快照), False=历史所有记录
        group_by: 分组维度
            - null: 全局聚合
            - "vehicle_type": 按能源类型
            - "floor": 按楼层
            - "date": 按日 (仅 active_only=False)
            - "hour": 按小时 (仅 active_only=False)
            - "day_of_week": 按星期几 (仅 active_only=False)
            - "month": 按月 (仅 active_only=False)
        date_from: 起始日期 YYYY-MM-DD (仅 active_only=False)
        date_to: 结束日期 YYYY-MM-DD (仅 active_only=False)
        include_duration: 是否附带平均停车时长 (仅 active_only=False)

    Returns:
        统一结构:
        {
            active_only, group_by, total_spots,
            occupied?, vacant?, occupancy_rate?,   # active_only=true 时
            total, groups[],
            avg_duration_minutes?,                  # include_duration=true 时
            date_range: {from, to} | null
        }
    """
    # ── 1. 参数校验 ──
    if active_only:
        if group_by not in ACTIVE_GROUP_BY:
            return {
                "error": (
                    f"active_only=true 时 group_by 仅支持 null、'vehicle_type'、'floor'，"
                    f"收到 '{group_by}'"
                )
            }
        # 忽略时间参数
        date_from = None
        date_to = None
        include_duration = False
    else:
        if group_by not in HISTORY_GROUP_BY:
            return {
                "error": (
                    f"group_by 不支持 '{group_by}'，"
                    f"可选: null, vehicle_type, floor, date, hour, day_of_week, month"
                )
            }
        # 默认日期范围: 最近 30 天
        today = datetime.date.today()
        if not date_from:
            date_from = (today - datetime.timedelta(days=30)).isoformat()
        if not date_to:
            date_to = today.isoformat()

    # ── 2. 获取全局配置 ──
    with get_db(read_only=True) as conn:
        config_row = conn.execute(
            "SELECT total_spots, floors, spots_per_floor "
            "FROM parking_lot_config WHERE id = 1"
        ).fetchone()
        total_spots = config_row["total_spots"] if config_row else 800

    # ── 3. 执行查询 ──
    with get_db(read_only=True) as conn:
        if active_only:
            result = _query_active(conn, group_by, total_spots)
        else:
            result = _query_history(
                conn, group_by, date_from, date_to, total_spots, include_duration
            )

    # ── 4. 统一返回结构 ──
    result["active_only"] = active_only
    result["group_by"] = group_by
    result["total_spots"] = total_spots
    result["date_range"] = (
        None if active_only else {"from": date_from, "to": date_to}
    )
    return result


# ── 当前快照查询 ─────────────────────────────────────────

def _query_active(conn, group_by: Optional[str], total_spots: int) -> dict:
    """active_only=true: 仅查询在场车辆 (exit_time IS NULL)。"""

    if group_by is None:
        # ── 全局: 等价于旧 T1 get_current_vacancy ──
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM vehicle_record WHERE exit_time IS NULL"
        ).fetchone()
        occupied = row["cnt"]
        return {
            "occupied": occupied,
            "vacant": total_spots - occupied,
            "occupancy_rate": _rate(occupied, total_spots),
            "total": occupied,
            "groups": [],
        }

    elif group_by == "vehicle_type":
        # ── 按车辆类型: 等价于旧 T2 get_nev_ratio ──
        rows = conn.execute(
            "SELECT vehicle_type, COUNT(*) AS cnt "
            "FROM vehicle_record WHERE exit_time IS NULL "
            "GROUP BY vehicle_type ORDER BY cnt DESC"
        ).fetchall()

        total = sum(r["cnt"] for r in rows)
        groups = [
            {
                "key": r["vehicle_type"],
                "label": VEHICLE_TYPE_LABELS.get(r["vehicle_type"], r["vehicle_type"]),
                "count": r["cnt"],
                "ratio": _rate(r["cnt"], total),
            }
            for r in rows
        ]
        return {
            "occupied": total,
            "vacant": total_spots - total,
            "occupancy_rate": _rate(total, total_spots),
            "total": total,
            "groups": groups,
        }

    elif group_by == "floor":
        # ── 按楼层: 等价于旧 T4 get_floor_status ──
        config_row = conn.execute(
            "SELECT floors, spots_per_floor FROM parking_lot_config WHERE id = 1"
        ).fetchone()
        total_floors = config_row["floors"] if config_row else 4
        spots_per_floor = config_row["spots_per_floor"] if config_row else 200

        groups = []
        occupied_total = 0
        for f in range(1, total_floors + 1):
            cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM vehicle_record "
                "WHERE exit_time IS NULL AND entry_floor = ?",
                (f,),
            ).fetchone()["cnt"]
            occupied_total += cnt
            groups.append({
                "key": str(f),
                "label": f"{f}楼",
                "count": cnt,
                "ratio": _rate(cnt, total_spots),
                "floor_total": spots_per_floor,
                "floor_vacant": spots_per_floor - cnt,
                "floor_occupancy_rate": _rate(cnt, spots_per_floor),
            })

        return {
            "occupied": occupied_total,
            "vacant": total_spots - occupied_total,
            "occupancy_rate": _rate(occupied_total, total_spots),
            "total": occupied_total,
            "groups": groups,
        }


# ── 历史记录查询 ─────────────────────────────────────────

def _query_history(
    conn, group_by: Optional[str], date_from: str, date_to: str,
    total_spots: int, include_duration: bool,
) -> dict:
    """active_only=false: 查询历史记录，按 group_by 维度聚合。"""

    date_end = f"{date_to} 23:59:59"

    if group_by is None:
        # ── 全局聚合 ──
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ?",
            (date_from, date_end),
        ).fetchone()
        total = row["cnt"]
        result: dict = {"total": total, "groups": []}
        _attach_duration(conn, result, None, date_from, date_end, include_duration)
        return result

    elif group_by == "vehicle_type":
        rows = conn.execute(
            "SELECT vehicle_type, COUNT(*) AS cnt "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY vehicle_type ORDER BY cnt DESC",
            (date_from, date_end),
        ).fetchall()

        total = sum(r["cnt"] for r in rows)
        groups = [
            {
                "key": r["vehicle_type"],
                "label": VEHICLE_TYPE_LABELS.get(r["vehicle_type"], r["vehicle_type"]),
                "count": r["cnt"],
                "ratio": _rate(r["cnt"], total),
            }
            for r in rows
        ]
        result = {"total": total, "groups": groups}
        if include_duration:
            _attach_per_group_duration(
                conn, groups, "vehicle_type", "vehicle_type", date_from, date_end
            )
        return result

    elif group_by == "floor":
        config_row = conn.execute(
            "SELECT floors FROM parking_lot_config WHERE id = 1"
        ).fetchone()
        total_floors = config_row["floors"] if config_row else 4

        rows = conn.execute(
            "SELECT entry_floor, COUNT(*) AS cnt "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY entry_floor ORDER BY entry_floor",
            (date_from, date_end),
        ).fetchall()

        floor_map = {r["entry_floor"]: r["cnt"] for r in rows}
        total = sum(floor_map.values())
        groups = [
            {
                "key": str(f),
                "label": f"{f}楼",
                "count": floor_map.get(f, 0),
                "ratio": _rate(floor_map.get(f, 0), total),
            }
            for f in range(1, total_floors + 1)
        ]
        return {"total": total, "groups": groups}

    elif group_by == "date":
        # ── 按日: 等价于旧 T3 get_trend ──
        rows = conn.execute(
            "SELECT DATE(entry_time) AS date, "
            "COUNT(*) AS entry_count, "
            "SUM(CASE WHEN exit_time IS NOT NULL THEN 1 ELSE 0 END) AS exit_count "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY DATE(entry_time) ORDER BY date",
            (date_from, date_end),
        ).fetchall()

        groups = []
        for r in rows:
            entry_cnt = r["entry_count"]
            peak = min(int(entry_cnt * 0.75), total_spots)
            groups.append({
                "date": r["date"],
                "entry_count": entry_cnt,
                "exit_count": r["exit_count"],
                "net_change": entry_cnt - r["exit_count"],
                "peak_occupancy_estimate": peak,
                "occupancy_rate": _rate(peak, total_spots),
            })

        # 7 日移动平均
        if len(groups) >= 2:
            df = pd.DataFrame(groups)
            df["rolling_avg_7d"] = (
                df["peak_occupancy_estimate"]
                .rolling(7, min_periods=1).mean().round(1)
            )
            groups = df.to_dict(orient="records")

        total = sum(g["entry_count"] for g in groups)
        result = {"total": total, "groups": groups}
        if include_duration:
            _attach_per_group_duration(
                conn, groups, "date", "DATE(entry_time)", date_from, date_end
            )
        return result

    elif group_by == "hour":
        # ── 按小时: 等价于旧 T5 get_hourly_distribution ──
        entry_rows = conn.execute(
            "SELECT CAST(strftime('%H', entry_time) AS INTEGER) AS hour, "
            "COUNT(*) AS entry_count "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY hour ORDER BY hour",
            (date_from, date_end),
        ).fetchall()

        exit_rows = conn.execute(
            "SELECT CAST(strftime('%H', exit_time) AS INTEGER) AS hour, "
            "COUNT(*) AS exit_count "
            "FROM vehicle_record "
            "WHERE exit_time IS NOT NULL "
            "AND exit_time >= ? AND exit_time <= ? "
            "GROUP BY hour ORDER BY hour",
            (date_from, date_end),
        ).fetchall()

        entry_map = {r["hour"]: r["entry_count"] for r in entry_rows}
        exit_map = {r["hour"]: r["exit_count"] for r in exit_rows}

        groups = []
        for h in range(24):
            ec = entry_map.get(h, 0)
            xc = exit_map.get(h, 0)
            groups.append({
                "hour": h,
                "entry_count": ec,
                "exit_count": xc,
                "net_change": ec - xc,
            })

        total = sum(g["entry_count"] for g in groups)
        return {"total": total, "groups": groups}

    elif group_by == "day_of_week":
        rows = conn.execute(
            "SELECT strftime('%w', entry_time) AS dow, "
            "COUNT(*) AS cnt "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY dow ORDER BY dow",
            (date_from, date_end),
        ).fetchall()

        total = sum(r["cnt"] for r in rows)
        existing = {r["dow"]: r["cnt"] for r in rows}
        groups = []
        for d in [str(i) for i in range(7)]:
            cnt = existing.get(d, 0)
            groups.append({
                "key": d,
                "label": DAY_OF_WEEK_LABELS[d],
                "count": cnt,
                "ratio": _rate(cnt, total),
            })

        result = {"total": total, "groups": groups}
        if include_duration:
            _attach_per_group_duration(
                conn, groups, "key",
                "strftime('%w', entry_time)", date_from, date_end
            )
        return result

    elif group_by == "month":
        rows = conn.execute(
            "SELECT strftime('%Y-%m', entry_time) AS month, "
            "COUNT(*) AS cnt "
            "FROM vehicle_record "
            "WHERE entry_time >= ? AND entry_time <= ? "
            "GROUP BY month ORDER BY month",
            (date_from, date_end),
        ).fetchall()

        total = sum(r["cnt"] for r in rows)
        groups = [
            {
                "key": r["month"],
                "label": r["month"],
                "count": r["cnt"],
                "ratio": _rate(r["cnt"], total),
            }
            for r in rows
        ]

        result = {"total": total, "groups": groups}
        if include_duration:
            _attach_per_group_duration(
                conn, groups, "key",
                "strftime('%Y-%m', entry_time)", date_from, date_end
            )
        return result


# ── 辅助函数 ─────────────────────────────────────────────

def _rate(numerator: int, denominator: int) -> float:
    """安全除法，返回保留 4 位小数的比率。"""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _attach_duration(
    conn, result: dict, _group_col, date_from: str, date_end: str,
    include_duration: bool,
) -> None:
    """为全局聚合结果附加 avg_duration_minutes。"""
    if not include_duration:
        return
    row = conn.execute(
        "SELECT AVG((julianday(exit_time) - julianday(entry_time)) * 24 * 60) "
        "AS avg_minutes "
        "FROM vehicle_record "
        "WHERE exit_time IS NOT NULL "
        "AND entry_time >= ? AND entry_time <= ?",
        (date_from, date_end),
    ).fetchone()
    result["avg_duration_minutes"] = (
        round(row["avg_minutes"], 1) if row and row["avg_minutes"] else 0.0
    )


def _attach_per_group_duration(
    conn, groups: list, key_field: str, group_expr: str,
    date_from: str, date_end: str,
) -> None:
    """为每个 group 附加 avg_duration_minutes。"""
    dur_rows = conn.execute(
        f"SELECT {group_expr} AS grp, "
        "AVG((julianday(exit_time) - julianday(entry_time)) * 24 * 60) "
        "AS avg_minutes "
        "FROM vehicle_record "
        "WHERE exit_time IS NOT NULL "
        "AND entry_time >= ? AND entry_time <= ? "
        f"GROUP BY {group_expr}",
        (date_from, date_end),
    ).fetchall()

    dur_map = {
        str(r["grp"]): round(r["avg_minutes"], 1)
        for r in dur_rows if r["avg_minutes"] is not None
    }
    for g in groups:
        g["avg_duration_minutes"] = dur_map.get(str(g[key_field]))
