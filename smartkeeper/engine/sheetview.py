"""玩家看到的自己实体的角色卡，以及每个可见数值的变更历史。"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import JsonValue

from smartkeeper.contracts import (
    EntityTemplate,
    PatchOp,
    RulePack,
    Rules,
    SheetChange,
    SheetView,
    State,
    ValidationFailed,
    World,
)
from smartkeeper.engine.space import peers_of


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def visible_sheet(tpl: EntityTemplate, sheet: JsonValue) -> dict[str, JsonValue]:
    """去掉模板标为隐藏的字段和分组。"""
    out = copy.deepcopy(_obj(sheet))
    hidden = {f.name for f in tpl.fields if f.hidden}
    fields = _obj(out.get("fields"))
    out["fields"] = {k: v for k, v in fields.items() if k not in hidden}
    hidden_groups = {g.name for g in tpl.groups if g.hidden}
    groups = _obj(out.get("groups"))
    out["groups"] = {k: v for k, v in groups.items() if k not in hidden_groups}
    return out


def _numbers(
    rules: Rules,
    pack: RulePack,
    tpl: EntityTemplate,
    ent: dict[str, JsonValue],
    peers: dict[str, JsonValue | None],
) -> dict[str, JsonValue]:
    """一个实体全部可见的数值：字段和推导值。"""
    out: dict[str, JsonValue] = {}
    sheet = ent.get("sheet")
    for k, v in _obj(visible_sheet(tpl, sheet).get("fields")).items():
        out[f"fields.{k}"] = v
    hidden = {d.name for d in tpl.derived if d.hidden}
    try:
        for d in rules.derive(pack, tpl.name, sheet, peers):
            if d.name not in hidden:
                out[f"derived.{d.name}"] = d.value
    except ValidationFailed:
        pass
    statuses = _obj(sheet).get("statuses")
    if isinstance(statuses, list):
        out["statuses"] = [str(_obj(s).get("tag", "")) for s in statuses]
    return out


def build_sheet_views(
    *,
    world: World,
    rules: Rules,
    pack: RulePack,
    initial: State,
    patches: Sequence[tuple[int, str, list[PatchOp]]],
    feedback_seq: Mapping[int, int],
    player_id: str,
) -> list[SheetView]:
    state = initial
    history: dict[str, list[SheetChange]] = {}
    before: dict[str, dict[str, JsonValue]] = {}

    def snapshot(st: State) -> dict[str, dict[str, JsonValue]]:
        out: dict[str, dict[str, JsonValue]] = {}
        ents = _obj(st.get("entities"))
        ctl = _obj(st.get("controls")).get(player_id)
        for eid in [str(e) for e in ctl] if isinstance(ctl, list) else []:
            ent = _obj(ents.get(eid))
            tpl = pack.template(str(ent.get("template", "")))
            if tpl is not None:
                out[eid] = _numbers(rules, pack, tpl, ent, peers_of(st, eid))
        return out

    for round_no, cause, ops in patches:
        state = world.apply(state, ops)
        after = snapshot(state)
        kind: Literal["feedback", "admin", "engine", "opening"]
        if cause == "admin":
            kind, src = "admin", None
        elif round_no == 0:
            kind, src = "opening", None
        elif round_no in feedback_seq:
            kind, src = "feedback", feedback_seq[round_no]
        else:
            kind, src = "engine", None
        for eid, nums in after.items():
            old = before.get(eid)
            if old is None:
                continue  # 实体第一次出现不算变更
            for path in sorted(set(old) | set(nums)):
                if old.get(path) != nums.get(path):
                    history.setdefault(eid, []).append(
                        SheetChange(
                            path=path,
                            old=old.get(path),
                            new=nums.get(path),
                            round_no=round_no,
                            source_seq=src,
                            source_kind=kind,
                        )
                    )
        before = after

    views: list[SheetView] = []
    ents = _obj(state.get("entities"))
    ctl = _obj(state.get("controls")).get(player_id)
    for eid in [str(e) for e in ctl] if isinstance(ctl, list) else []:
        ent = _obj(ents.get(eid))
        tpl = pack.template(str(ent.get("template", "")))
        if tpl is None:
            continue
        hidden = {d.name for d in tpl.derived if d.hidden}
        peers = peers_of(state, eid)
        derived = tuple(
            d for d in rules.derive(pack, tpl.name, ent.get("sheet"), peers) if d.name not in hidden
        )
        views.append(
            SheetView(
                entity_id=eid,
                template=tpl.name,
                sheet=visible_sheet(tpl, rules.full_sheet(pack, tpl.name, ent.get("sheet"), peers)),
                derived=derived,
                history=tuple(history.get(eid, [])),
                label=tpl.display_name(_obj(ent.get("sheet"))),
            )
        )
    return views
