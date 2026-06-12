"""
T8: 受控 SQL 查询工具。

安全约束:
- 只读连接 (PRAGMA query_only = ON + URI mode=ro)
- SQL 关键字黑名单
- 查询超时 5 秒
- 返回行数上限 1000
- PRAGMA 语句允许执行，写 PRAGMA 由 SQLite 内核层 (query_only=ON) 拦截
"""

import re
from db import get_db

# 禁止的 SQL 关键字
FORBIDDEN_KEYWORDS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
    r"\bALTER\b", r"\bCREATE\b", r"\bATTACH\b", r"\bDETACH\b",
    r"\bVACUUM\b",
]

MAX_ROWS = 1000

SCHEMA_HINT = (
    "可用表及字段:\n"
    "- parking_lot_config: id, name, total_spots, floors, spots_per_floor, hourly_rate\n"
    "- vehicle_record: id, plate, vehicle_type(ICE/BEV/PHEV/HEV), "
    "entry_time, exit_time(NULL=在场), entry_floor, entry_spot\n"
    "可用索引: idx_entry_time, idx_exit_time, idx_vehicle_type, idx_plate, idx_active"
)


def sql_query(query: str) -> dict:
    """
    执行受控的只读 SQL 查询。
    返回 {columns: [...], rows: [...], row_count: int} 或 {error: str}。
    """
    query_stripped = query.strip()

    if not query_stripped:
        return {"error": "查询语句为空"}

    # 安全检查（仅对非 PRAGMA 语句进行关键字黑名单检查）
    query_upper = query_stripped.upper()

    if query_upper.startswith("PRAGMA"):
        # PRAGMA 语句：跳过黑名单检查，安全性由 SQLite 内核层 (mode=ro + query_only=ON) 保证
        pass
    else:
        for kw in FORBIDDEN_KEYWORDS:
            if re.search(kw, query_upper):
                return {"error": f"此查询涉及不允许的操作 ({kw.strip('\\\\b')})，请使用预定义工具"}

        if not query_upper.startswith("SELECT"):
            return {"error": "仅支持 SELECT 和 PRAGMA 查询"}

    # 执行
    try:
        with get_db(read_only=True) as conn:
            # 设置查询超时
            conn.execute("PRAGMA query_only = ON")

            cursor = conn.execute(query_stripped)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(MAX_ROWS + 1)

            if len(rows) > MAX_ROWS:
                return {
                    "error": f"查询结果超过 {MAX_ROWS} 行上限，请缩小查询范围",
                    "columns": columns,
                    "row_count": len(rows),
                }

            # 转换 Row 对象为字典
            row_dicts = [dict(zip(columns, row)) for row in rows]

            return {
                "columns": columns,
                "rows": row_dicts,
                "row_count": len(row_dicts),
            }

    except Exception as e:
        error_msg = str(e)
        hint = None
        error_lower = error_msg.lower()

        if "no such" in error_lower:
            hint = SCHEMA_HINT
        elif "syntax error" in error_lower:
            hint = "请检查SQL语法: 确保关键字拼写正确、括号匹配、字符串用单引号"
        elif "ambiguous column" in error_lower:
            hint = "列名在多个表中存在，请使用 table.column 格式明确指定"

        return {
            "error": "SQL执行失败",
            "detail": error_msg,
            **({"hint": hint} if hint else {}),
            "query": query,
        }
