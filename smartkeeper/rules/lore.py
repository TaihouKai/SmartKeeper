"""资料库：从 SillyTavern World Info（世界书）的 JSON 导入，校验。

只认我们用得到的字段：标题（comment）、关键词（key）、次关键词和逻辑（keysecondary、selectiveLogic）、
大小写（caseSensitive）、顺序（order）、正文（content）、关闭（disable）。常驻（constant）不支持：
资料库只按关键词触发，常驻的设定该写进规则书。
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import JsonValue

from smartkeeper.contracts import LoreEntry, Problem

# World Info 的 selectiveLogic：0 AND ANY、1 NOT ALL、2 NOT ANY、3 AND ALL
_LOGIC = {0: "any", 1: "not_all", 2: "not_any", 3: "all"}


def _strs(v: object) -> tuple[str, ...]:
    if not isinstance(v, list):
        return ()
    return tuple(s.strip() for s in cast(list[Any], v) if isinstance(s, str) and s.strip())


def from_world_info(data: JsonValue) -> list[LoreEntry]:
    """世界书 JSON（{"entries": {uid: 条目}} 或条目列表）转成资料库条目，按原来的顺序。"""
    raw: object = data.get("entries", data) if isinstance(data, dict) else data
    items: list[Any] = (
        list(cast(dict[str, Any], raw).values())
        if isinstance(raw, dict)
        else list(cast(list[Any], raw))
        if isinstance(raw, list)
        else []
    )
    out: list[LoreEntry] = []
    for e in items:
        if not isinstance(e, dict):
            continue
        d = cast(dict[str, Any], e)
        content = str(d.get("content") or "").strip()
        keys = _strs(d.get("key"))
        if not content or not keys:
            continue
        logic = _LOGIC.get(int(d.get("selectiveLogic") or 0), "any")
        out.append(
            LoreEntry(
                title=str(d.get("comment") or keys[0]).strip(),
                keys=keys,
                content=content,
                secondary=_strs(d.get("keysecondary")),
                logic=cast(Any, logic),
                case_sensitive=bool(d.get("caseSensitive")),
                order=int(d.get("order") or 100),
                disabled=bool(d.get("disable")),
            )
        )
    return out


def check_lore(lore: tuple[LoreEntry, ...]) -> list[Problem]:
    """每条要有标题、关键词和正文；标题不重复（管理台和记录里按标题认条目）。"""
    out: list[Problem] = []
    seen: set[str] = set()
    for i, e in enumerate(lore):
        path = f"lore[{i}]"
        if not e.title.strip():
            out.append(Problem(code="lore.no_title", path=path))
        elif e.title in seen:
            out.append(Problem(code="lore.duplicate_title", path=path, params={"title": e.title}))
        seen.add(e.title)
        if not any(k.strip() for k in e.keys):
            out.append(Problem(code="lore.no_keys", path=path, params={"title": e.title}))
        if not e.content.strip():
            out.append(Problem(code="lore.no_content", path=path, params={"title": e.title}))
    return out
