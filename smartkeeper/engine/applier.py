"""把算好的脚本步骤（伤害、加减、设置、限时修正）和消耗、冷却落到世界状态上，顺手记下 patch。

技能的使用和死亡时的脚本都走这里。所有改动都经由 World.apply，数值按字段的上下限截断。
"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    COOLDOWN_TAG,
    HP_FIELD,
    SHIELD_FIELD,
    Effect,
    Grant,
    PatchOp,
    Problem,
    RulePack,
    Rules,
    State,
    Status,
    World,
)
from smartkeeper.engine.space import peers_of


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


class StepApplier:
    def __init__(
        self, world: World, rules: Rules, faces: f.Faces, pack: RulePack, end: int
    ) -> None:
        self.world = world
        self.rules = rules
        self.faces = faces
        self.pack = pack
        self.end = end  # 本轮结束的游戏内秒：限时效果从这里起算
        self.ops: list[PatchOp] = []
        self.problems: list[Problem] = []
        self.hurt_by: dict[str, str] = {}  # 受伤的实体 -> 最后一次伤到它的实体

    def _fields(self, state: State, eid: str) -> dict[str, JsonValue]:
        return _obj(_obj(_obj(_obj(state.get("entities")).get(eid)).get("sheet")).get("fields"))

    def _bound(self, state: State, eid: str, name: str) -> tuple[float | None, float | None]:
        ent = _obj(_obj(state.get("entities")).get(eid))
        template = str(ent.get("template", ""))
        tpl = self.pack.template(template)
        fd = next((x for x in tpl.fields if x.name == name), None) if tpl else None
        if fd is None:
            return None, None
        peers = peers_of(state, eid)

        def ev(text: str | None) -> float | None:
            if text is None:
                return None
            return self.rules.roll(
                self.pack, text, self.faces, template, ent.get("sheet"), None, peers
            ).total

        return ev(fd.min), ev(fd.max)

    def put(self, state: State, eid: str, name: str, value: float) -> State:
        lo, hi = self._bound(state, eid, name)
        if lo is not None:
            value = max(value, lo)
        if hi is not None:
            value = min(value, hi)
        value = round(value, 2)
        v: JsonValue = int(value) if value.is_integer() else value
        op = PatchOp(op="replace", path=f"/entities/{eid}/sheet/fields/{name}", value=v)
        self.ops.append(op)
        return self.world.apply(state, [op])

    def num(self, state: State, eid: str, name: str) -> float | None:
        v = self._fields(state, eid).get(name)
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    def add_status(self, state: State, who: str, status: Status) -> State:
        sop = PatchOp(
            op="add",
            path=f"/entities/{who}/sheet/statuses/-",
            value=status.model_dump(mode="json"),
        )
        self.ops.append(sop)
        return self.world.apply(state, [sop])

    def spend_and_cool(
        self, state: State, who: str, spends: JsonValue, entry: str, cd: JsonValue
    ) -> State:
        for res, amount in sorted(_obj(spends).items()):
            have = self.num(state, who, res)
            if have is not None and isinstance(amount, int | float):
                state = self.put(state, who, res, have - float(amount))
        if isinstance(cd, int) and cd > 0 and who in _obj(state.get("entities")):
            state = self.add_status(
                state, who, Status(tag=COOLDOWN_TAG + entry, source=who, expires_at=self.end + cd)
            )
        return state

    def apply_actions(
        self, state: State, listed: JsonValue, source: str, entry: str, path: str
    ) -> State:
        """脚本算好的每一步（{entity, op, field, amount, seconds, formula}）。"""
        for raw in cast(list[JsonValue], listed) if isinstance(listed, list) else []:
            a = _obj(raw)
            who = a.get("entity")
            op = a.get("op")
            if not isinstance(who, str) or who not in _obj(state.get("entities")) or op == "negate":
                continue
            amount = float(cast(float, a.get("amount", 0)))
            dur = a.get("seconds")
            if op == "modify":
                state = self.add_status(
                    state,
                    who,
                    Status(
                        tag=entry,
                        source=source,
                        expires_at=self.end + dur if isinstance(dur, int) else None,
                        modifier=Effect(
                            description=entry,
                            target=str(a.get("field")),
                            formula=str(a.get("formula")),
                        ),
                    ),
                )
                continue
            if op == "damage":
                left = max(0.0, amount)
                if left > 0 and who != source:
                    self.hurt_by[who] = source
                shield = self.num(state, who, SHIELD_FIELD)
                if shield is not None and shield > 0 and left > 0:
                    take = min(shield, left)
                    state = self.put(state, who, SHIELD_FIELD, shield - take)
                    left -= take
                hp = self.num(state, who, HP_FIELD)
                if hp is not None and left > 0:
                    state = self.put(state, who, HP_FIELD, hp - left)
                continue
            name = str(a.get("field"))
            have = self.num(state, who, name)
            if have is None:
                self.problems.append(
                    Problem(code="adj.use_bad_field", path=path, params={"name": name})
                )
                continue
            if op == "set":
                state = self.put(state, who, name, amount)
            elif op == "subtract":
                state = self.put(state, who, name, have - amount)
            else:
                state = self.put(state, who, name, have + amount)
                gained = (self.num(state, who, name) or have) - have
                if isinstance(dur, int) and gained > 0:
                    state = self.add_status(
                        state,
                        who,
                        Status(
                            tag=entry,
                            source=source,
                            expires_at=self.end + dur,
                            grant=Grant(field=name, amount=gained),
                        ),
                    )
        return state
