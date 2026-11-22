"""World 接口的实现：世界状态的折叠、校验与状态到期。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from pydantic import JsonValue

from smartkeeper.contracts import (
    PatchOp,
    Problem,
    RulePack,
    Rules,
    State,
    ValidationFailed,
)
from smartkeeper.world.patch import PatchError, apply_patch

TOP_LEVEL = (
    "game_minutes",
    "map",
    "controls",
    "entities",
    "map_changes",
    "clues",
    "flags",
    "kp_notes",
)


def _obj(v: JsonValue) -> dict[str, JsonValue] | None:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else None


def _num(v: JsonValue) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


class WorldService:
    def __init__(self, rules: Rules) -> None:
        self._rules = rules

    def initial_state(self, map_id: str | None) -> State:
        return {
            "game_minutes": 0,
            "map": map_id,
            "controls": {},
            "entities": {},
            "map_changes": [],
            "clues": {},
            "flags": {},
            "kp_notes": "",
        }

    def apply(self, state: State, ops: Sequence[PatchOp]) -> State:
        try:
            out = apply_patch(state, ops)
        except PatchError as e:
            raise ValidationFailed("patch.failed", [Problem(code=e.code, path=e.path)]) from e
        obj = _obj(out)
        if obj is None:
            raise ValidationFailed("patch.failed", [Problem(code="state.not_object")])
        return obj

    def validate(self, state: State, pack: RulePack) -> list[Problem]:
        problems: list[Problem] = []
        for key in state:
            if key not in TOP_LEVEL:
                problems.append(Problem(code="state.unknown_key", path=f"/{key}"))
        for key in TOP_LEVEL:
            if key not in state:
                problems.append(Problem(code="state.missing_key", path=f"/{key}"))
        if problems:
            return problems
        if not isinstance(state["game_minutes"], int) or isinstance(state["game_minutes"], bool):
            problems.append(Problem(code="state.type", path="/game_minutes"))
        if not isinstance(state["kp_notes"], str):
            problems.append(Problem(code="state.type", path="/kp_notes"))
        for key in ("clues", "flags"):
            if _obj(state[key]) is None:
                problems.append(Problem(code="state.type", path=f"/{key}"))
        if not isinstance(state["map_changes"], list):
            problems.append(Problem(code="state.type", path="/map_changes"))
        entities = _obj(state["entities"])
        if entities is None:
            return [*problems, Problem(code="state.type", path="/entities")]
        for eid, ent in sorted(entities.items()):
            problems += self._validate_entity(eid, ent, pack)
        controls = _obj(state["controls"])
        if controls is None:
            return [*problems, Problem(code="state.type", path="/controls")]
        owner: dict[str, str] = {}
        for pid, ents in sorted(controls.items()):
            if not isinstance(ents, list):
                problems.append(Problem(code="state.type", path=f"/controls/{pid}"))
                continue
            for e in ents:
                if not isinstance(e, str) or e not in entities:
                    problems.append(
                        Problem(
                            code="state.unknown_entity", path=f"/controls/{pid}", params={"id": e}
                        )
                    )
                elif e in owner:
                    problems.append(
                        Problem(
                            code="state.controlled_twice", path=f"/controls/{pid}", params={"id": e}
                        )
                    )
                else:
                    owner[e] = pid
        return problems

    def _validate_entity(self, eid: str, raw: JsonValue, pack: RulePack) -> list[Problem]:
        base = f"/entities/{eid}"
        ent = _obj(raw)
        if ent is None:
            return [Problem(code="state.type", path=base)]
        problems: list[Problem] = []
        for key in ent:
            if key not in ("template", "pos", "inside", "sheet"):
                problems.append(Problem(code="state.unknown_key", path=f"{base}/{key}"))
        template = ent.get("template")
        if not isinstance(template, str) or pack.template(template) is None:
            return [*problems, Problem(code="state.unknown_template", path=f"{base}/template")]
        pos = ent.get("pos")
        if pos is not None:
            p = _obj(pos)
            if p is None or set(p) != {"x", "y", "z"} or not all(_num(v) for v in p.values()):
                problems.append(Problem(code="state.bad_pos", path=f"{base}/pos"))
        inside = ent.get("inside")
        if inside is not None and not isinstance(inside, str):
            problems.append(Problem(code="state.type", path=f"{base}/inside"))
        for p in self._rules.validate_sheet(pack, template, ent.get("sheet")):
            path = "/" + p.path.replace(".", "/") if p.path else ""
            problems.append(p.model_copy(update={"path": f"{base}/sheet{path}"}))
        return problems

    def expire(self, state: State, now_minute: int) -> list[PatchOp]:
        ops: list[PatchOp] = []
        entities = _obj(state.get("entities")) or {}
        for eid, raw in sorted(entities.items()):
            sheet = _obj((_obj(raw) or {}).get("sheet"))
            statuses = (sheet or {}).get("statuses")
            if not isinstance(statuses, list):
                continue
            # 从后往前删，下标才不会错位
            for i in range(len(statuses) - 1, -1, -1):
                st = _obj(statuses[i]) or {}
                exp = st.get("expires_at")
                if _num(exp) and cast(float, exp) <= now_minute:
                    ops.append(PatchOp(op="remove", path=f"/entities/{eid}/sheet/statuses/{i}"))
        return ops

    def canonical(self, state: State) -> str:
        return json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
