"""KP 的裁定文字里用名字或外貌提到了某个实体，却没写成 {{实体ID}}。

那样的话引擎不知道玩家见到了谁：不给他建代号，反馈里的人不能点，玩家行动里也 @ 不到他。
这里按字面找：名字（或名字里两个字以上的一段）出现在文字里，或者和外貌描述有两处以上
连续四个字（英文是四个词）相同。只是提醒：找错了 KP 改个说法就行。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_TOKEN = re.compile(r"\{\{([^{}]{1,80})\}\}")
# 英文和数字按词，其余文字（中文、日文）按字
_UNIT = re.compile(r"[a-z0-9']+|[^\W\d_a-z]")
_NAME_SPLIT = re.compile(r"[\s·・,，、/()（）\[\]【】「」\"'“”]+")
_GRAM = 4
_MIN_SHARED = 2


@dataclass(frozen=True, slots=True)
class Looks:
    """一个实体能被认出来的写法：名字（可以有几个）和外貌描述。"""

    names: tuple[str, ...] = ()
    appearance: str = ""


def _grams(text: str) -> set[tuple[str, ...]]:
    units = _UNIT.findall(text.lower())
    return {tuple(units[i : i + _GRAM]) for i in range(len(units) - _GRAM + 1)}


def _name_parts(names: Iterable[str]) -> list[str]:
    parts: set[str] = set()
    for n in names:
        n = n.strip()
        if len(n) >= 2:
            parts.add(n)
        parts |= {p for p in _NAME_SPLIT.split(n) if len(p) >= 2}
    return sorted(parts, key=len, reverse=True)


def _has_name(text: str, part: str) -> bool:
    if part.isascii():  # 英文名按整词找，不区分大小写
        return (
            re.search(rf"(?<![A-Za-z0-9]){re.escape(part)}(?![A-Za-z0-9])", text, re.I) is not None
        )
    return part in text


def untokened(text: str, looks: Mapping[str, Looks]) -> list[tuple[str, str]]:
    """文字里没写记号、但按名字或外貌认得出来的实体：(实体 id, 认出来的依据)。文字里已经写了记号的实体不算。"""
    tokens = set(_TOKEN.findall(text))
    plain = _TOKEN.sub(" ", text)
    grams = _grams(plain)
    out: list[tuple[str, str]] = []
    for eid, lk in sorted(looks.items()):
        if eid in tokens:
            continue
        hit = next((p for p in _name_parts(lk.names) if _has_name(plain, p)), None)
        if hit is None and lk.appearance:
            shared = grams & _grams(lk.appearance)
            if len(shared) >= _MIN_SHARED:
                hit = lk.appearance
        if hit is not None:
            out.append((eid, hit))
    return out
