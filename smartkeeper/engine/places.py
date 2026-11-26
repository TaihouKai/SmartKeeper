"""起了名字的地点：KP 或剧本给地图上的位置起名字，所有玩家共用、永久有效。

世界状态 /places/<id> = NamedPlace。来源只有三处，都要过引擎的校验：
- 剧本 scenario_kp.md 的 places（开场时登记）；
- 开场输出的 places；
- 每轮裁定的 places。
一个名字只能指一个地方：已经有这个名字、位置又不一样，或者同一批里同名不同地，都是错误（KP 带着错误重试）。
名字和地图上某个地物的名字相同，但指的不是那个地物，也是错误（玩家会以为是那个地物）。

KP 写给玩家的文字里用 {{place:名字}} 提到地点；引擎在文字变成事件时换成可以点的链接：
起过的名字换成 [名字](place:<id>)，地图上的地物名换成 [名字](feature:<地物 id>)，都不是就只留名字。

谁知道哪个名字不另外记：公开的谁都知道；不公开的，玩家能看到的事件里有指向它的链接，就是知道了。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import cast

from pydantic import JsonValue, ValidationError

from smartkeeper.contracts import NamedPlace

TOKEN = re.compile(r"\{\{place:([^{}]{1,60})\}\}")
LINKED = re.compile(r"\]\(place:([A-Za-z0-9_]{1,40})\)")

# 同一个名字再次声明时，离原来的位置这么近（米）就算同一个地方
SAME_SPOT_M = 5.0
SAME_SPOT_Z = 1.5


def clean(name: str) -> str:
    """名字去掉首尾空白、合并中间的空白；方括号换成全角（链接的写法里方括号有特殊意思）。"""
    return " ".join(name.split()).replace("[", "【").replace("]", "】")


def _key(name: str) -> str:
    return clean(name).casefold()


def of(state: Mapping[str, JsonValue]) -> dict[str, NamedPlace]:
    """世界状态里的全部地点。坏掉的条目跳过（世界状态校验会报）。"""
    raw = state.get("places")
    table = cast(dict[str, JsonValue], raw) if isinstance(raw, dict) else {}
    out: dict[str, NamedPlace] = {}
    for pid, v in table.items():
        try:
            out[pid] = NamedPlace.model_validate(v)
        except ValidationError:
            continue
    return out


def find(places: Mapping[str, NamedPlace], name: str) -> str | None:
    want = _key(name)
    return next((pid for pid, p in sorted(places.items()) if _key(p.name) == want), None)


def same_spot(a: NamedPlace, b: NamedPlace) -> bool:
    if a.feature is not None and a.feature == b.feature and abs(a.pos.z - b.pos.z) <= SAME_SPOT_Z:
        return True
    d = math.hypot(a.pos.x - b.pos.x, a.pos.y - b.pos.y)
    return d <= SAME_SPOT_M and abs(a.pos.z - b.pos.z) <= SAME_SPOT_Z


def new_id(places: Mapping[str, NamedPlace]) -> str:
    n = len(places) + 1
    while f"place_{n}" in places:
        n += 1
    return f"place_{n}"


def link(
    text: str, places: Mapping[str, NamedPlace], feature_named: Callable[[str], str | None]
) -> str:
    """把 {{place:名字}} 换成链接（见模块说明）。"""

    def one(m: re.Match[str]) -> str:
        name = clean(m.group(1))
        pid = find(places, name)
        if pid is not None:
            return f"[{name}](place:{pid})"
        fid = feature_named(name)
        if fid is not None:
            return f"[{name}](feature:{fid})"
        return name

    return TOKEN.sub(one, text)


def names_in(text: str) -> list[str]:
    return [clean(x) for x in TOKEN.findall(text)]


def linked_ids(text: str) -> set[str]:
    """文字里链接到的起了名字的地点。"""
    return set(LINKED.findall(text))
