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
    ValidationFailed,
    World,
)
from smartkeeper.engine import sightings
from smartkeeper.engine.space import peers_of


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def _ptr(key: str) -> str:
    """JSON 指针里的一段（~ 和 / 要转义）。"""
    return key.replace("~", "~0").replace("/", "~1")


def _num(v: JsonValue) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v) if isinstance(v, int | float) else None


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

    def _blocked(self, state: State, eid: str, cond: str) -> bool:
        ent = _obj(_obj(state.get("entities")).get(eid))
        try:
            return (
                self.rules.roll(
                    self.pack,
                    cond,
                    self.faces,
                    str(ent.get("template", "")),
                    ent.get("sheet"),
                    None,
                    peers_of(state, eid),
                ).total
                != 0
            )
        except ValidationFailed:
            return False

    def put(self, state: State, eid: str, name: str, value: float) -> State:
        ent = _obj(_obj(state.get("entities")).get(eid))
        tpl = self.pack.template(str(ent.get("template", "")))
        fd = next((x for x in tpl.fields if x.name == name), None) if tpl else None
        v: JsonValue
        if fd is not None and fd.kind == "boolean":
            v = value != 0  # 是/否：非 0 是“是”
            op = PatchOp(op="replace", path=f"/entities/{eid}/sheet/fields/{name}", value=v)
            self.ops.append(op)
            return self.world.apply(state, [op])
        if fd is not None and fd.gain_blocked:
            # 加不上去的时候（例如被禁止治疗）：只能减少
            cur = self.num(state, eid, name)
            if cur is not None and value > cur and self._blocked(state, eid, fd.gain_blocked):
                value = cur
        lo, hi = self._bound(state, eid, name)
        if lo is not None:
            value = max(value, lo)
        if hi is not None:
            value = min(value, hi)
        value = round(value, 2)
        v = int(value) if value.is_integer() else value
        op = PatchOp(op="replace", path=f"/entities/{eid}/sheet/fields/{name}", value=v)
        self.ops.append(op)
        return self.world.apply(state, [op])

    def num(self, state: State, eid: str, name: str) -> float | None:
        return _num(self._fields(state, eid).get(name))

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

    def cool_tags(self, state: State, who: str, tags: JsonValue) -> State:
        """另外的冷却（例如参数的冷却）：状态名 -> 秒数。"""
        for tag, sec in sorted(_obj(tags).items()):
            if isinstance(sec, int) and sec > 0 and who in _obj(state.get("entities")):
                state = self.add_status(
                    state, who, Status(tag=tag, source=who, expires_at=self.end + sec)
                )
        return state

    def _column(
        self, state: State, who: str, group: str, owner: str, col: str
    ) -> tuple[str, float | None, list[PatchOp]]:
        """条目的一列在角色卡上的位置：(JSON 指针, 现在的值, 要先建好的上层)。
        玩家写的条目在 groups 里；固定条目存在 preset_fields 里（没存过时值取读卡时算出的初值）。"""
        sheet = _obj(_obj(_obj(state.get("entities")).get(who)).get("sheet"))
        base = f"/entities/{who}/sheet"
        rows = sheet.get("groups")
        for i, e in enumerate(cast(list[JsonValue], _obj(rows).get(group)) or []):
            row = _obj(e)
            if row.get("name") == owner:
                v = _obj(row.get("fields")).get(col)
                return f"{base}/groups/{_ptr(group)}/{i}/fields/{_ptr(col)}", _num(v), []
        made: list[PatchOp] = []
        pf = _obj(sheet.get("preset_fields"))
        if "preset_fields" not in sheet:
            made.append(PatchOp(op="add", path=f"{base}/preset_fields", value={}))
        if group not in pf:
            made.append(PatchOp(op="add", path=f"{base}/preset_fields/{_ptr(group)}", value={}))
        if owner not in _obj(pf.get(group)):
            made.append(
                PatchOp(
                    op="add", path=f"{base}/preset_fields/{_ptr(group)}/{_ptr(owner)}", value={}
                )
            )
        v = _obj(_obj(pf.get(group)).get(owner)).get(col)
        if v is None:
            ent = _obj(_obj(state.get("entities")).get(who))
            full = _obj(
                self.rules.full_sheet(
                    self.pack, str(ent.get("template", "")), ent.get("sheet"), peers_of(state, who)
                )
            )
            for e in cast(list[JsonValue], _obj(full.get("groups")).get(group)) or []:
                if _obj(e).get("name") == owner:
                    v = _obj(_obj(e).get("fields")).get(col)
        path = f"{base}/preset_fields/{_ptr(group)}/{_ptr(owner)}/{_ptr(col)}"
        return path, _num(v), made

    def _put_column(
        self, state: State, who: str, group: str, owner: str, col: str, op: str, amount: float
    ) -> State:
        path, have, made = self._column(state, who, group, owner, col)
        cur = have or 0.0
        value = amount if op == "set" else cur - amount if op == "subtract" else cur + amount
        gdef = next(
            (
                g
                for t in self.pack.templates
                for g in t.groups
                if g.name == group
                and t.name == _obj(_obj(state.get("entities")).get(who)).get("template")
            ),
            None,
        )
        fd = next((x for x in gdef.fields if x.name == col), None) if gdef else None
        v: JsonValue
        if fd is not None and fd.kind == "boolean":
            v = value != 0
        else:
            value = round(value, 2)
            v = int(value) if value.is_integer() else value
        ops = [*made, PatchOp(op="add", path=path, value=v)]
        self.ops += ops
        return self.world.apply(state, ops)

    def _teleport(self, state: State, who: str, to: JsonValue) -> State:
        """瞬间移动到另一个角色身边（同一个位置、同一栋建筑里）。"""
        dest = _obj(_obj(state.get("entities")).get(to)) if isinstance(to, str) else {}
        if not dest or dest.get("pos") is None:
            return state
        ops = [
            PatchOp(op="replace", path=f"/entities/{who}/pos", value=dest.get("pos")),
            PatchOp(op="replace", path=f"/entities/{who}/inside", value=dest.get("inside")),
        ]
        self.ops += ops
        return self.world.apply(state, ops)

    def _summon(
        self,
        state: State,
        who: str,
        template: str,
        count: int,
        seconds: JsonValue,
        values: dict[str, JsonValue],
    ) -> State:
        """在召唤者身边放 count 个新角色，归召唤者的玩家控制；限时的到期后由引擎移除。"""
        ents = _obj(state.get("entities"))
        me = _obj(ents.get(who))
        tpl = self.pack.template(template)
        if not me or tpl is None or count <= 0:
            return state
        label = tpl.label or tpl.name
        ops: list[PatchOp] = []
        made: list[str] = []
        n = 1
        while len(made) < count:
            eid = f"{who}_{template}_{n}"
            if eid not in ents:
                made.append(eid)
            n += 1
        controls = _obj(state.get("controls"))
        player = next(
            (pid for pid, ctl in controls.items() if isinstance(ctl, list) and who in ctl), None
        )
        # 脚本算出来的是数或文字：按字段的类型放进角色卡（是/否字段非 0 是“是”）
        kinds = {x.name: x.kind for x in tpl.fields}
        typed: dict[str, JsonValue] = {}
        for k, v in values.items():
            if kinds.get(k) == "boolean":
                typed[k] = v not in (0, 0.0, "", False)
            elif isinstance(v, float) and v.is_integer():
                typed[k] = int(v)
            else:
                typed[k] = v
        for eid in made:
            sheet: JsonValue = {
                "name": f"{label}{eid.rsplit('_', 1)[-1]}",
                "fields": dict(typed),
            }
            sheet = self.rules.init_sheet(self.pack, template, sheet, peers_of(state, who))
            bad = self.rules.validate_sheet(self.pack, template, sheet)
            if bad:
                # 召唤脚本给的字段不全或不合法：这次召唤不算（规则包的问题，由裁定报出来）
                self.problems.append(
                    Problem(
                        code="adj.summon_bad_sheet",
                        path=f"summon.{template}",
                        params={"problem": f"{bad[0].code} {bad[0].path}"},
                    )
                )
                return state
            ops.append(
                PatchOp(
                    op="add",
                    path=f"/entities/{eid}",
                    value={
                        "template": template,
                        "pos": me.get("pos"),
                        "inside": me.get("inside"),
                        "sheet": sheet,
                        "summoned": {
                            "by": who,
                            "until": self.end + seconds if isinstance(seconds, int) else None,
                        },
                    },
                )
            )
            if player is not None:
                ops.append(PatchOp(op="add", path=f"/controls/{player}/-", value=eid))
        self.ops += ops
        return self.world.apply(state, ops)

    def apply_actions(
        self,
        state: State,
        listed: JsonValue,
        source: str,
        entry: str,
        path: str,
        group: str = "",
        owner: str = "",
    ) -> State:
        """脚本算好的每一步（{entity, op, field, amount, seconds, formula}）。group、owner 是用的那个条目
        所在的分组和条目名：field 写成 this.<列> 的步骤改的是它的列。"""
        for raw in cast(list[JsonValue], listed) if isinstance(listed, list) else []:
            a = _obj(raw)
            who = a.get("entity")
            op = a.get("op")
            if not isinstance(who, str) or who not in _obj(state.get("entities")) or op == "negate":
                continue
            amount = float(cast(float, a.get("amount", 0)))
            dur = a.get("seconds")
            field = str(a.get("field") or "")
            if op == "teleport":
                state = self._teleport(state, who, a.get("to_entity"))
                continue
            if op == "locate":
                marks = {who: {sightings.side_of(state, source): self.end}}
                lops = sightings.stamp_ops(state, marks)
                self.ops += lops
                state = self.world.apply(state, lops) if lops else state
                continue
            if op == "summon":
                state = self._summon(state, who, field, int(amount), dur, _obj(a.get("values")))
                continue
            if field.startswith("this.") and op != "modify":
                if who == source and group and owner and op in ("set", "add", "subtract"):
                    state = self._put_column(state, who, group, owner, field[5:], str(op), amount)
                continue
            if op == "modify":
                if field.startswith("this."):
                    field = f"{owner}.{field[5:]}"  # 这个条目的一列：<条目名>.<列>
                state = self.add_status(
                    state,
                    who,
                    Status(
                        tag=entry,
                        source=source,
                        expires_at=self.end + dur if isinstance(dur, int) else None,
                        modifier=Effect(
                            description=entry,
                            target=field,
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
