"""
停车场模拟数据生成器 — 独立脚本，无外部模块依赖（仅需 Python 标准库）。

用法:
    python regenerate_data.py --name "购物中心停车场" --total-spots 800 --floors 4 \
        --spots-per-floor "200,200,200,200" --nev-weights "55,25,12,8" \
        --db-path ../instances/parking_a/data/parking_a.db --days 120

由 regenerate_data.ps1 统一调用，一键重新生成三个实例的数据库。
"""

import argparse
import datetime
import heapq
import math
import os
import random
import sqlite3

# ══════════════════════════════════════════════════════════════
#  Schema（内联，不依赖外部 db.py）
# ══════════════════════════════════════════════════════════════

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS parking_lot_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT 'Demo停车场',
    total_spots INTEGER NOT NULL DEFAULT 800,
    floors INTEGER NOT NULL DEFAULT 4,
    spots_per_floor INTEGER NOT NULL DEFAULT 200,
    hourly_rate REAL NOT NULL DEFAULT 6.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vehicle_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL,
    vehicle_type TEXT NOT NULL CHECK(vehicle_type IN ('ICE', 'BEV', 'PHEV', 'HEV')),
    entry_time DATETIME NOT NULL,
    exit_time DATETIME,
    entry_floor INTEGER CHECK(entry_floor BETWEEN 1 AND 10),
    entry_spot INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entry_time ON vehicle_record(entry_time);
CREATE INDEX IF NOT EXISTS idx_exit_time ON vehicle_record(exit_time);
CREATE INDEX IF NOT EXISTS idx_vehicle_type ON vehicle_record(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_plate ON vehicle_record(plate);
CREATE INDEX IF NOT EXISTS idx_active ON vehicle_record(entry_time) WHERE exit_time IS NULL;
"""


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def seed_config(db_path: str, name: str, total_spots: int, floors: int,
                spots_per_floor: int, hourly_rate: float = 6.0) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO parking_lot_config "
            "(id, name, total_spots, floors, spots_per_floor, hourly_rate) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (name, total_spots, floors, spots_per_floor, hourly_rate),
        )
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
#  解析工具
# ══════════════════════════════════════════════════════════════

def _parse_nev_weights(weights_str: str) -> list[float]:
    parts = [float(x.strip()) for x in weights_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"NEV_WEIGHTS 须为 4 个值 (ICE,BEV,PHEV,HEV)，收到 {len(parts)} 个")
    total = sum(parts)
    if total == 0:
        raise ValueError("NEV_WEIGHTS 总和不能为 0")
    return [p / total for p in parts]


def _parse_spots_per_floor(spots_str: str, floors: int, total_spots: int) -> list[int]:
    parts = [int(x.strip()) for x in spots_str.split(",")]
    if len(parts) == 1:
        base = parts[0]
        spots = [base] * floors
        diff = total_spots - sum(spots)
        for i in range(diff):
            spots[i] += 1
        return spots
    if len(parts) != floors:
        raise ValueError(f"SPOTS_PER_FLOOR 条目数 ({len(parts)}) 与 FLOORS ({floors}) 不匹配")
    return parts


# ══════════════════════════════════════════════════════════════
#  数据生成核心
# ══════════════════════════════════════════════════════════════

R_EARTH = 6371.0
DEFAULT_DAYS = 120

MORNING_PEAK  = (7,  9,  1.6)
LUNCH_PERIOD  = (11, 14, 1.2)
EVENING_PEAK  = (17, 19, 1.8)
NIGHT_LULL    = (21, 24, 0.3)
NIGHT_LULL2   = (0,  6,  0.1)

DURATION_MEAN_BUSINESS = 3.0
DURATION_MEAN_WEEKEND  = 4.5


def _poisson(lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30:
        L = math.exp(-lam)
        k, p = 0, 1.0
        while p > L:
            k += 1
            p *= random.random()
        return k - 1
    return max(0, int(random.gauss(lam, math.sqrt(lam)) + 0.5))


def _hour_multiplier(hour: int, is_weekend: bool) -> float:
    base = 1.0
    if is_weekend:
        base *= 0.70
    if MORNING_PEAK[0] <= hour < MORNING_PEAK[1]:
        return base * MORNING_PEAK[2]
    elif LUNCH_PERIOD[0] <= hour < LUNCH_PERIOD[1]:
        return base * LUNCH_PERIOD[2]
    elif EVENING_PEAK[0] <= hour < EVENING_PEAK[1]:
        return base * EVENING_PEAK[2]
    elif NIGHT_LULL[0] <= hour < NIGHT_LULL[1]:
        return base * NIGHT_LULL[2]
    elif 0 <= hour < NIGHT_LULL2[1]:
        return base * NIGHT_LULL2[2]
    return base * 0.8


def generate(db_path: str, name: str, total_spots: int, floors: int,
             spots_per_floor: list[int], nev_weights: list[float],
             history_days: int = DEFAULT_DAYS) -> int:
    """生成历史停车数据，返回总记录数。"""

    vehicle_types = ["ICE", "BEV", "PHEV", "HEV"]
    provinces = ["京", "沪", "粤", "苏", "浙", "鲁", "川", "鄂"]

    init_db(db_path)
    seed_config(db_path, name, total_spots, floors,
                sum(spots_per_floor) // floors, 6.0)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("DELETE FROM vehicle_record")

    today = datetime.date.today()
    now = datetime.datetime.now()
    start_date = today - datetime.timedelta(days=history_days)
    total_records = 0

    heap = []
    parked_forever = 0

    for day_offset in range(history_days):
        current_date = start_date + datetime.timedelta(days=day_offset)
        is_weekend = current_date.weekday() >= 5
        daily_mean = random.randint(1200, 1800) * (0.7 if is_weekend else 1.0)
        records = []

        for hour in range(24):
            hour_start = datetime.datetime.combine(current_date, datetime.time(hour, 0, 0))

            while heap and heap[0] <= hour_start:
                heapq.heappop(heap)

            hour_mean = daily_mean * _hour_multiplier(hour, is_weekend) / 24.0
            arrivals = min(_poisson(hour_mean), 200)

            for _ in range(arrivals):
                if len(heap) + parked_forever >= total_spots:
                    break

                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                entry_dt = hour_start + datetime.timedelta(minutes=minute, seconds=second)

                mean_dur = DURATION_MEAN_WEEKEND if is_weekend else DURATION_MEAN_BUSINESS
                duration = min(random.expovariate(1.0 / mean_dur), 24.0)
                exit_dt = entry_dt + datetime.timedelta(hours=duration)

                vtype = random.choices(vehicle_types, weights=nev_weights, k=1)[0]
                plate = f"{random.choice(provinces)}{chr(65 + random.randint(0,25))}{total_records + len(records):05d}"
                floor = random.randint(1, floors)
                spot = random.randint(1, spots_per_floor[floor - 1])

                if exit_dt > now:
                    exit_str = None
                    parked_forever += 1
                else:
                    exit_str = exit_dt.isoformat(sep=" ")
                    heapq.heappush(heap, exit_dt)

                records.append((plate, vtype, entry_dt.isoformat(sep=" "), exit_str, floor, spot))

        conn.executemany(
            "INSERT INTO vehicle_record (plate, vehicle_type, entry_time, exit_time, entry_floor, entry_spot) "
            "VALUES (?, ?, ?, ?, ?, ?)", records)
        total_records += len(records)

        if (day_offset + 1) % 20 == 0:
            print(f"  进度: {day_offset + 1}/{history_days} 天, 累计 {total_records} 条")

    conn.commit()

    parked = conn.execute("SELECT COUNT(*) FROM vehicle_record WHERE exit_time IS NULL").fetchone()[0]
    dr = conn.execute("SELECT MIN(entry_time), MAX(entry_time) FROM vehicle_record").fetchone()
    conn.close()

    print(f"  {name} → {total_records} 条记录, 在场 {parked} 辆, "
          f"日期 {dr[0][:10]} ~ {dr[1][:10]}  [容量 {total_spots}]")
    return total_records


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="停车场模拟数据生成器")
    parser.add_argument("--name", required=True)
    parser.add_argument("--total-spots", type=int, required=True)
    parser.add_argument("--floors", type=int, required=True)
    parser.add_argument("--spots-per-floor", type=str, default=None)
    parser.add_argument("--nev-weights", type=str, default="55,25,12,8")
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    nev_weights = _parse_nev_weights(args.nev_weights)
    spots_str = args.spots_per_floor
    if spots_str is None:
        base = args.total_spots // args.floors
        spots_str = ",".join([str(base)] * args.floors)
    spots_per_floor = _parse_spots_per_floor(spots_str, args.floors, args.total_spots)

    generate(args.db_path, args.name, args.total_spots, args.floors,
             spots_per_floor, nev_weights, args.days)


if __name__ == "__main__":
    main()
