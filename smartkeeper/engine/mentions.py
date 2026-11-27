"""行动声明里的 @ 指代。界面插入的格式是 `@[显示文字](ref)`：

- ref 是该玩家的代号引用（handle 表里的 ref），指人和物；
- `feature:<地物 id>` 指地图上的地物；
- `point:x,y,z` 是在地图上点选的坐标（米）。

引擎在 KP 看到之前把它们换成实体 ID 或地物 id；KP 不负责猜指代。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from smartkeeper.contracts import Point

MENTION = re.compile(r"@\[([^\]\n]{1,80})\]\(([A-Za-z0-9_:.,\-]{1,80})\)")


@dataclass(frozen=True, slots=True)
class Mention:
    text: str
    ref: str
    start: int
    end: int

    @property
    def is_feature(self) -> bool:
        return self.ref.startswith("feature:")

    @property
    def is_point(self) -> bool:
        return self.ref.startswith("point:")

    @property
    def point(self) -> Point | None:
        try:
            parts = [float(x) for x in self.ref.removeprefix("point:").split(",")]
        except ValueError:
            return None
        if len(parts) == 2:
            parts.append(0.0)
        if len(parts) != 3:
            return None
        return Point(x=parts[0], y=parts[1], z=parts[2])

    @property
    def feature_id(self) -> str:
        return self.ref.removeprefix("feature:")


def find_mentions(text: str) -> list[Mention]:
    return [Mention(m.group(1), m.group(2), m.start(), m.end()) for m in MENTION.finditer(text)]


def link_labels(text: str, refs: dict[str, str]) -> str:
    """给玩家的消息里写的 `@代号` 换成 `@[代号](ref)`（refs：代号 -> ref，长的代号优先），
    界面上就能点，玩家改了代号也跟着显示新的。已经是链接的不动。"""
    labels = sorted((x for x in refs if x), key=len, reverse=True)
    if "@" not in text or not labels:
        return text
    pat = re.compile("@(" + "|".join(re.escape(x) for x in labels) + ")")
    return pat.sub(lambda m: f"@[{m.group(1)}]({refs[m.group(1)]})", text)


def replace_mentions(text: str, labels: dict[str, str]) -> str:
    """把 `@[x](ref)` 换成 `@<labels[ref]>`；labels 里没有的 ref 保留原文字。"""

    def sub(m: re.Match[str]) -> str:
        return "@" + labels.get(m.group(2), m.group(1))

    return MENTION.sub(sub, text)
