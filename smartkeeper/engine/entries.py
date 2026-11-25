"""角色卡上能用的东西：条目本身，和条目下面的用途（写成“条目名/用途名”）。

用途当作一个“虚拟条目”交给后面的代码：列是条目的列，技能设置是条目的设置被用途覆盖之后的，
脚本是用途自己的，名字是“条目名/用途名”（冷却、事件里都用这个名字）。修正属于条目本身，不属于用途。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple, cast

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import USE_SEP, GroupEntry


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def _list(v: JsonValue) -> list[JsonValue]:
    return cast(list[JsonValue], v) if isinstance(v, list) else []


# 用途当作条目时另外带着的信息（不是条目的格式）
USE_KEYS = ("is_use", "use_name", "toggle", "default_on")


def as_entry(row: dict[str, JsonValue]) -> GroupEntry:
    """角色卡上的一行（可能是用途）读成条目。"""
    return GroupEntry.model_validate({k: v for k, v in row.items() if k not in USE_KEYS})


def use_row(entry: dict[str, JsonValue], use: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """物品的一个用途当作一个条目：参数是物品上加的加上用途上加的；开关类用途带着它的开关信息。"""
    name = f"{entry.get('name', '')}{USE_SEP}{use.get('name', '')}"
    return {
        **entry,
        "name": name,
        "id": "",
        "description": str(use.get("description", "")),
        "config": f.merge_config(str(entry.get("config") or ""), str(use.get("config") or "")),
        "script": str(use.get("script") or ""),
        "effects": [],
        "uses": [],
        "params": [*_list(entry.get("params")), *_list(use.get("params"))],
        "is_use": True,
        "use_name": str(use.get("name", "")),
        "toggle": bool(use.get("toggle")),
        "default_on": bool(use.get("default_on")),
    }


class Found(NamedTuple):
    group: str
    row: dict[str, JsonValue]
    owner: str  # 条目本身的名字（用途属于的那个条目）


def usable(sheet: dict[str, JsonValue]) -> Iterator[Found]:
    """每个条目，再跟着它的每个用途。"""
    for gname, entries in _obj(sheet.get("groups")).items():
        for e in _list(entries):
            row = _obj(e)
            owner = str(row.get("name", ""))
            yield Found(str(gname), row, owner)
            for u in _list(row.get("uses")):
                yield Found(str(gname), use_row(row, _obj(u)), owner)


def find(sheet: dict[str, JsonValue], ref: str) -> Found | None:
    """按名字或 ID 找条目；“条目名/用途名”（条目也可以写 ID）找用途。"""
    for hit in usable(sheet):
        if ref == hit.row.get("name") or (hit.row.get("id") and ref == hit.row.get("id")):
            return hit
    head, sep, use = ref.rpartition(USE_SEP)
    if not sep:
        return None
    for gname, entries in _obj(sheet.get("groups")).items():
        for e in _list(entries):
            row = _obj(e)
            if head in (row.get("name"), row.get("id")) and head:
                for u in _list(row.get("uses")):
                    if _obj(u).get("name") == use:
                        return Found(str(gname), use_row(row, _obj(u)), str(row.get("name", "")))
    return None
