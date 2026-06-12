"""
find_nearby_things — Haversine 地理空间筛选工具。

从 things.yaml 加载所有物的经纬度，计算与查询中心的距离，
返回 radius_km 范围内的物列表。
"""

import math

# Earth radius in km
R_EARTH = 6371.0


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Haversine formula — calculate great-circle distance between two points.
    Returns distance in kilometers.
    """
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R_EARTH * c


def find_nearby_things(
    lat: float,
    lng: float,
    radius_km: float,
    thing_type: str | None = None,
) -> dict:
    """
    查找中心点周围的物。

    Args:
        lat: 中心点纬度
        lng: 中心点经度
        radius_km: 搜索半径（公里）
        thing_type: 可选物类型过滤 (parking_lot|cafeteria|hospital)

    Returns:
        {things: [{id, name, type, lat, lng, distance_km}]}
    """
    from config import THINGS

    results = []
    for thing in THINGS:
        # Type filter
        if thing_type and thing.get("type") != thing_type:
            continue

        thing_lat = thing["location"]["lat"]
        thing_lng = thing["location"]["lng"]
        distance = haversine(lat, lng, thing_lat, thing_lng)

        if distance <= radius_km:
            results.append({
                "id": thing["id"],
                "name": thing["name"],
                "type": thing["type"],
                "lat": thing_lat,
                "lng": thing_lng,
                "distance_km": round(distance, 2),
            })

    # Sort by distance ascending
    results.sort(key=lambda x: x["distance_km"])

    return {"things": results}
