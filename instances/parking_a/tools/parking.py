"""
停车场业务工具 v2 — get_config + get_vehicle。

v2 变更 (2026-06-10):
- 新增 get_config: 获取停车场全局配置
- get_vehicle_detail 重命名为 get_vehicle，增加 history_count 和 found 标志
- 移除 T1(get_current_vacancy), T2(get_nev_ratio), T3(get_trend),
  T4(get_floor_status), T5(get_hourly_distribution), T7(get_summary_stats)
  → 全部由 query_aggregation (tools/aggregation.py) 替代
"""

import datetime
from typing import Any, Optional

from db import get_db


# ── Tool: get_config ────────────────────────────────────

def get_config() -> dict:
    """
    获取停车场全局配置。

    Returns:
        {
            name, total_spots, floors, spots_per_floor, hourly_rate
        }
    """
    with get_db(read_only=True) as conn:
        row = conn.execute(
            "SELECT name, total_spots, floors, spots_per_floor, hourly_rate "
            "FROM parking_lot_config WHERE id = 1"
        ).fetchone()

    if row:
        return {
            "name": row["name"],
            "total_spots": row["total_spots"],
            "floors": row["floors"],
            "spots_per_floor": row["spots_per_floor"],
            "hourly_rate": row["hourly_rate"],
        }
    return {
        "name": "Demo停车场",
        "total_spots": 800,
        "floors": 4,
        "spots_per_floor": 200,
        "hourly_rate": 6.0,
    }


# ── Tool: get_vehicle ───────────────────────────────────

VEHICLE_TYPE_NAMES = {
    "ICE": "燃油车",
    "BEV": "纯电动",
    "PHEV": "插电混动",
    "HEV": "油电混动",
}


def get_vehicle(plate: str) -> dict:
    """
    按车牌号精确查询车辆的进出记录和当前状态。

    先查在场记录 (exit_time IS NULL)，无结果则查最近已离开记录。
    附加该车牌的历史总记录数 (history_count)。

    Args:
        plate: 车牌号 (必填)

    Returns:
        {
            found, plate, vehicle_type, vehicle_type_name,
            status ("parked"|"left"),
            entry_time, exit_time, duration_minutes,
            floor, spot, history_count
        }
    """
    with get_db(read_only=True) as conn:
        # 先查在场
        row = conn.execute(
            "SELECT plate, vehicle_type, entry_time, exit_time, entry_floor, entry_spot "
            "FROM vehicle_record WHERE plate = ? AND exit_time IS NULL "
            "ORDER BY entry_time DESC LIMIT 1",
            (plate,),
        ).fetchone()

        if not row:
            # 查最近的已离开记录
            row = conn.execute(
                "SELECT plate, vehicle_type, entry_time, exit_time, entry_floor, entry_spot "
                "FROM vehicle_record WHERE plate = ? "
                "ORDER BY entry_time DESC LIMIT 1",
                (plate,),
            ).fetchone()

        if not row:
            return {
                "found": False,
                "plate": plate,
                "error": f"未找到车牌 {plate} 的任何记录",
            }

        # 历史总记录数
        history_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM vehicle_record WHERE plate = ?",
            (plate,),
        ).fetchone()["cnt"]

    status = "parked" if row["exit_time"] is None else "left"

    duration_minutes = None
    if row["entry_time"] and row["exit_time"]:
        try:
            entry = datetime.datetime.strptime(row["entry_time"], "%Y-%m-%d %H:%M:%S")
            exit_t = datetime.datetime.strptime(row["exit_time"], "%Y-%m-%d %H:%M:%S")
            duration_minutes = round((exit_t - entry).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass
    elif row["entry_time"] and status == "parked":
        try:
            entry = datetime.datetime.strptime(row["entry_time"], "%Y-%m-%d %H:%M:%S")
            duration_minutes = round((datetime.datetime.now() - entry).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass

    return {
        "found": True,
        "plate": row["plate"],
        "vehicle_type": row["vehicle_type"],
        "vehicle_type_name": VEHICLE_TYPE_NAMES.get(row["vehicle_type"], row["vehicle_type"]),
        "status": status,
        "entry_time": row["entry_time"],
        "exit_time": row["exit_time"],
        "duration_minutes": duration_minutes,
        "floor": row["entry_floor"],
        "spot": row["entry_spot"],
        "history_count": history_count,
    }
