"""情报：玩家得知的关于别人的事。

全部记成 intel_gained 事件（只给那个玩家看），“我知道的”从日志里合并出来，所以同一份日志总得出同样的结果。
来源有三种：规则包的“看见就知道”（每轮开始时引擎按感知算）、认出了别人用的什么（技能的动静）、KP 的判定。
玩家自己改不了：情报只由引擎和裁定写。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Literal

from pydantic import JsonValue

from smartkeeper.contracts import (
    Event,
    Faces,
    IntelFact,
    NewEvent,
    ValidationFailed,
    Visibility,
)
from smartkeeper.engine.space import Space, peers_of

TOKEN = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")

type Known = dict[tuple[str, str], list[IntelFact]]
type Source = Literal["rule", "use", "kp"]


def _key(fact: IntelFact) -> tuple[str, str] | None:
    """同一个字段、同一个条目只留最新的；线索没有键，全留。"""
    if fact.kind == "field" and fact.field is not None:
        return ("field", fact.field.name)
    if fact.kind == "entry":
        return ("entry", fact.entry)
    return None


def _same(a: IntelFact, b: IntelFact) -> bool:
    keep = {"kind", "field", "entry", "columns", "text"}
    return a.model_dump(include=keep) == b.model_dump(include=keep)


def known(events: Iterable[Event]) -> Known:
    """(玩家, 实体) -> 合并后的情报，按得知的先后排。"""
    merged: dict[tuple[str, str], dict[tuple[str, str], IntelFact]] = {}
    for ev in events:
        if ev.type != "intel_gained":
            continue
        pair = (str(ev.payload.get("player")), str(ev.payload.get("about")))
        facts = ev.payload.get("facts")
        bucket = merged.setdefault(pair, {})
        for i, raw in enumerate(facts if isinstance(facts, list) else []):
            fact = IntelFact.model_validate(raw)
            k = _key(fact) or ("note", f"{ev.seq}:{i}")
            bucket.pop(k, None)  # 新值排到后面
            bucket[k] = fact
    return {pair: list(b.values()) for pair, b in merged.items()}


def fresh(have: Sequence[IntelFact], facts: Iterable[IntelFact]) -> list[IntelFact]:
    """facts 里玩家还不知道的（值没变的字段和条目不再说一遍）。"""
    by_key = {k: f for f in have if (k := _key(f)) is not None}
    out: list[IntelFact] = []
    for f in facts:
        k = _key(f)
        if k is not None:
            old = by_key.get(k)
            if old is not None and _same(old, f):
                continue
            by_key[k] = f
        out.append(f)
    return out


def event(
    player: str, about: str, facts: Sequence[IntelFact], round_no: int, seconds: int, actor: str
) -> NewEvent:
    return NewEvent(
        type="intel_gained",
        actor=actor,
        visibility=Visibility.to(player),
        payload={
            "player": player,
            "about": about,
            "facts": [f.model_dump(mode="json") for f in facts],
            "round": round_no,
            "game_seconds": seconds,
        },
    )


def facts_about(
    space: Space,
    entity: str,
    fields: Sequence[str],
    groups: Sequence[str],
    source: Source,
    seconds: int,
) -> list[IntelFact]:
    """实体卡上这些字段此刻的值、这些分组里的条目，作为情报。"""
    ent = space.entities.get(entity)
    if not isinstance(ent, dict):
        return []
    tpl = str(ent.get("template", ""))
    sheet = ent.get("sheet")
    peers = peers_of(space.state, entity)
    out: list[IntelFact] = []
    try:
        values = (
            space.rules.describe(space.pack, tpl, sheet, tuple(fields), peers) if fields else ()
        )
        for v in values:
            out.append(IntelFact(kind="field", field=v, source=source, game_seconds=seconds))
        for g in groups:
            for name, cols in space.rules.describe_entries(space.pack, tpl, sheet, g, peers):
                out.append(
                    IntelFact(
                        kind="entry",
                        entry=name,
                        columns=cols,
                        source=source,
                        game_seconds=seconds,
                    )
                )
    except ValidationFailed:
        return out
    return out


def note(text: str, seconds: int) -> IntelFact:
    return IntelFact(kind="note", text=text, source="kp", game_seconds=seconds)


def entry_fact(name: str, seconds: int) -> IntelFact:
    return IntelFact(kind="entry", entry=name, source="use", game_seconds=seconds)


def sight(space: Space, faces: Faces, seconds: int, dead: Callable[[str], bool]) -> Known:
    """规则包的“看见就知道”：每个玩家的每个活着的实体，对它此刻感知到的每个别人的实体，套一遍规则。"""
    pack = space.pack
    out: Known = {}
    if not pack.insights:
        return out
    for pid, ents in sorted(space.controls.items()):
        mine = set(ents)
        for e in ents:
            if dead(e):
                continue
            ent = space.entities.get(e)
            if not isinstance(ent, dict):
                continue
            e_tpl = str(ent.get("template", ""))
            for other in sorted(space.perceived_by(e)):
                if other in mine:
                    continue
                o_ent = space.entities.get(other)
                if not isinstance(o_ent, dict):
                    continue
                o_tpl = str(o_ent.get("template", ""))
                for rule in pack.insights:
                    if rule.observers and e_tpl not in rule.observers:
                        continue
                    if rule.subjects and o_tpl not in rule.subjects:
                        continue
                    if rule.when.strip():
                        try:
                            ok = space.rules.roll(
                                pack,
                                rule.when,
                                faces,
                                e_tpl,
                                ent.get("sheet"),
                                None,
                                peers_of(space.state, e),
                                (o_tpl, space.full_sheet(other), peers_of(space.state, other)),
                            ).total
                        except ValidationFailed:
                            continue
                        if ok == 0:
                            continue
                    out.setdefault((pid, other), []).extend(
                        facts_about(space, other, rule.fields, rule.groups, "rule", seconds)
                    )
    return out


def fill(text: str, labels: dict[str, str], unknown: str) -> str:
    """把 {{实体 id}} 换成这个玩家对它的叫法；不认识的换成 unknown。"""
    return TOKEN.sub(lambda m: labels.get(m.group(1), unknown), text)


def dump(facts: Sequence[IntelFact]) -> list[JsonValue]:
    return [f.model_dump(mode="json") for f in facts]
