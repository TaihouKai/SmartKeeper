"""数值字段的可选值：choices 里每一项是 名字=数（E=1）、一个数（10）、或一个范围（1~5）。

    E=1, D=2, C=3, B=4, A=5, EX=10
    1~5, 10
    1~5, EX=10

角色卡上存的是数；带名字的显示名字。范围两端都算，取整数。
"""

from __future__ import annotations

import re

_RANGE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[~～\-–]\s*(-?\d+(?:\.\d+)?)$")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse(
    choices: tuple[str, ...],
) -> tuple[list[tuple[str | None, float]], list[tuple[float, float]]]:
    """(带名字或不带名字的单个值, 范围)。写错的那一项抛 ValueError(那一项)。"""
    values: list[tuple[str | None, float]] = []
    ranges: list[tuple[float, float]] = []
    for raw in choices:
        item = raw.strip()
        if "=" in item:
            label, _, num = item.partition("=")
            label, num = label.strip(), num.strip()
            if not label or not _NUM.match(num):
                raise ValueError(raw)
            values.append((label, float(num)))
        elif _NUM.match(item):
            values.append((None, float(item)))
        elif m := _RANGE.match(item):
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                raise ValueError(raw)
            ranges.append((lo, hi))
        else:
            raise ValueError(raw)
    return values, ranges


def allowed(choices: tuple[str, ...], value: float) -> bool:
    values, ranges = parse(choices)
    if any(abs(v - value) < 1e-9 for _, v in values):
        return True
    return float(value).is_integer() and any(lo <= value <= hi for lo, hi in ranges)


def label_of(choices: tuple[str, ...], value: float) -> str | None:
    """这个数对应的名字（E、EX……）；没有名字是 None。"""
    try:
        values, _ = parse(choices)
    except ValueError:
        return None
    return next((name for name, v in values if name and abs(v - value) < 1e-9), None)
