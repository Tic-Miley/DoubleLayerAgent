"""
aggregate — 结构化多源数据聚合工具。

对 L2 物返回的结构化数据执行统计聚合（sum/avg/min/max/count/median/std）。
"""

import math
from typing import Any


# 数据上限
MAX_DATA_ITEMS = 500

# 支持的聚合函数
SUPPORTED_FUNCS = {"sum", "avg", "min", "max", "count", "median", "std"}


def _get_nested_value(item: dict, field: str) -> Any:
    """
    按点号分隔的嵌套路径逐层 dict.get(key) 取值。
    例: "structured.value" → item.get("structured", {}).get("value")
    """
    parts = field.split(".")
    current = item
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _safe_numbers(values: list) -> list[float]:
    """Filter to numeric values only, excluding None."""
    result = []
    for v in values:
        if v is None:
            continue
        try:
            result.append(float(v))
        except (ValueError, TypeError):
            pass
    return result


def aggregate(data: list[dict], operations: list[dict]) -> dict:
    """
    对多源数据执行聚合操作。

    Args:
        data: 待聚合的数据列表，每项为 dict
        operations: 聚合操作列表
            [{field: str, func: str, alias: str (optional)}]
            func: sum|avg|min|max|count|median|std

    Returns:
        {results: {alias或生成的key: 计算结果}}
    """
    # Truncate if over limit
    truncated = False
    if len(data) > MAX_DATA_ITEMS:
        data = data[:MAX_DATA_ITEMS]
        truncated = True

    # Filter out error items
    valid_data = [d for d in data if isinstance(d, dict) and "error" not in d]

    results: dict[str, Any] = {}

    for op in operations:
        field = op["field"]
        func = op["func"]
        alias = op.get("alias", "")
        key = alias if alias else f"{func}_{field}"

        # Extract values
        values = []
        skipped = 0
        for item in valid_data:
            val = _get_nested_value(item, field)
            if val is None:
                skipped += 1
            else:
                values.append(val)

        # Report truncation
        if truncated:
            results[f"{key}_truncated"] = True

        # Report skipped count
        if skipped > 0:
            results[f"{key}_skipped_count"] = skipped

        # All values skipped → null
        if not values:
            results[key] = None
            continue

        # Execute function
        try:
            if func == "sum":
                results[key] = round(sum(_safe_numbers(values)), 4)
            elif func == "avg":
                nums = _safe_numbers(values)
                results[key] = round(sum(nums) / len(nums), 4) if nums else None
            elif func == "min":
                nums = _safe_numbers(values)
                results[key] = min(nums) if nums else None
            elif func == "max":
                nums = _safe_numbers(values)
                results[key] = max(nums) if nums else None
            elif func == "count":
                results[key] = len(values)
            elif func == "median":
                nums = sorted(_safe_numbers(values))
                if not nums:
                    results[key] = None
                else:
                    n = len(nums)
                    if n % 2 == 1:
                        results[key] = nums[n // 2]
                    else:
                        results[key] = round((nums[n // 2 - 1] + nums[n // 2]) / 2, 4)
            elif func == "std":
                nums = _safe_numbers(values)
                if len(nums) < 2:
                    results[key] = None  # std requires >= 2 data points
                else:
                    mean = sum(nums) / len(nums)
                    variance = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)
                    results[key] = round(math.sqrt(variance), 4)
            else:
                results[key] = f"unsupported func: {func}"
        except Exception as e:
            results[key] = {"error": str(e)}

    return {"results": results}
