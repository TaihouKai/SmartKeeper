"""行动声明里的 @ 指代。界面插入的格式是 `@[显示文字](ref)`：

- ref 是该玩家的代号引用（handle 表里的 ref），指人和物；
- `feature:<地物 id>` 指地图上的地物。

引擎在 KP 看到之前把它们换成实体 ID 或地物 id；KP 不负责猜指代。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MENTION = re.compile(r"@\[([^\]\n]{1,80})\]\(([A-Za-z0-9_:\-]{1,80})\)")


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
    def feature_id(self) -> str:
        return self.ref.removeprefix("feature:")


def find_mentions(text: str) -> list[Mention]:
    return [Mention(m.group(1), m.group(2), m.start(), m.end()) for m in MENTION.finditer(text)]


def replace_mentions(text: str, labels: dict[str, str]) -> str:
    """把 `@[x](ref)` 换成 `@<labels[ref]>`；labels 里没有的 ref 保留原文字。"""

    def sub(m: re.Match[str]) -> str:
        return "@" + labels.get(m.group(2), m.group(1))

    return MENTION.sub(sub, text)
