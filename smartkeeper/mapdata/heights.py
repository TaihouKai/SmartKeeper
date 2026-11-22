"""建筑高度补全。规则固定：有高度用高度；否则层数乘 3 米；两者都没有就按建筑类型取默认值。"""

from __future__ import annotations

import re
from collections.abc import Mapping

FLOOR_HEIGHT = 3.0

# 按 OSM building=* 的取值给默认高度（米）。可以在导入时用配置文件覆盖。
DEFAULT_HEIGHTS: dict[str, float] = {
    "default": 9.0,
    "yes": 9.0,
    "house": 6.0,
    "detached": 6.0,
    "residential": 12.0,
    "apartments": 15.0,
    "commercial": 12.0,
    "retail": 6.0,
    "office": 20.0,
    "industrial": 8.0,
    "warehouse": 8.0,
    "garage": 3.0,
    "shed": 3.0,
    "school": 12.0,
    "hospital": 20.0,
    "church": 15.0,
    "temple": 9.0,
    "shrine": 6.0,
    "train_station": 12.0,
    "hotel": 30.0,
    "roof": 4.0,
}

_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(m|meters?|metres?)?\s*$", re.IGNORECASE)
_FEET = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ft|feet|')\s*$", re.IGNORECASE)


def parse_length(value: str | None) -> float | None:
    """解析 OSM 的长度标签，例如 "12"、"12.5 m"、"40 ft"。解析不了返回 None。"""
    if value is None:
        return None
    m = _NUM.match(value)
    if m:
        return float(m.group(1))
    m = _FEET.match(value)
    if m:
        return float(m.group(1)) * 0.3048
    return None


def parse_levels(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        n = float(value.strip())
    except ValueError:
        return None
    return n if n >= 0 else None


def building_height(
    tags: Mapping[str, str], defaults: Mapping[str, float] = DEFAULT_HEIGHTS
) -> float:
    h = parse_length(tags.get("height"))
    if h is not None and h > 0:
        return h
    levels = parse_levels(tags.get("building:levels"))
    if levels is not None and levels > 0:
        return levels * FLOOR_HEIGHT
    kind = tags.get("building", "default")
    return float(defaults.get(kind, defaults.get("default", DEFAULT_HEIGHTS["default"])))


def building_min_height(tags: Mapping[str, str]) -> float:
    h = parse_length(tags.get("min_height"))
    if h is not None and h >= 0:
        return h
    levels = parse_levels(tags.get("building:min_level"))
    if levels is not None:
        return levels * FLOOR_HEIGHT
    return 0.0


def floor_z(floor: int) -> float:
    """第 n 层的离地高度：z = (n − 1) × 3 米；地下层用负数楼层号（-1 层 → -3 米）。"""
    if floor >= 1:
        return (floor - 1) * FLOOR_HEIGHT
    return floor * FLOOR_HEIGHT
