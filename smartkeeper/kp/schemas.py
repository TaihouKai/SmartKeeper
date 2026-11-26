"""各种调用的输出结构。LLM 的输出一律在本地解析和校验，失败带着错误重试。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from smartkeeper.contracts import AdHocCheck, PatchOp, Place, PlaceNameIn, Point, SpatialQuery


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ReviewOut(_Out):
    approved: bool
    comments: str = ""


class OpeningOut(_Out):
    broadcast: str
    messages: dict[str, str]
    places: list[PlaceNameIn] = []
    positions: dict[str, Place] = {}


class HandleOut(_Out):
    label: str = Field(min_length=1, max_length=40)


class TargetOut(_Out):
    ref: str | None = None
    feature: str | None = None
    point: Point | None = None


class DestinationOut(_Out):
    feature: str | None = None
    z: float | None = None
    point: Point | None = None


class ItemOut(_Out):
    actor: str
    verb: str
    targets: list[TargetOut] = []
    destination: DestinationOut | None = None
    detail: str = ""
    seconds: int = Field(ge=0)  # 动作本身的耗时，不含移动；必填，所以 KP 一定会给出一个时间
    entry: str | None = None  # 用了角色卡上的哪个技能（条目名或 ID）


class NpcTalkOut(_Out):
    text: str = Field(min_length=1)
    end: bool = False


class ClaimOut(_Out):
    text: str
    refs: list[str] = []
    features: list[str] = []


class IntentOut(_Out):
    items: list[ItemOut]
    claims: list[ClaimOut] = []
    unresolved: list[str] = []
    conflict: str = ""  # 补充文字和界面上点的行动矛盾时写原因
    instant: bool = False  # 几秒以内、只涉及自己、别人察觉不到的小事


class InstantOut(_Out):
    result: str = Field(min_length=1)
    state_patch: list[PatchOp] = []


class ClaimCheckOut(_Out):
    verdict: Literal["holds", "partial", "fails"]
    evidence: list[int] = []
    note: str = ""


class CheckOut(_Out):
    entity: str
    check: str | None = None
    adhoc: AdHocCheck | None = None
    against: float | str | None = None
    reason: str = ""


class LeakItem(_Out):
    sentence: str
    reason: str = ""


class LeakOut(_Out):
    leaks: list[LeakItem] = []


class RollOut(_Out):
    """掷某个实体角色卡上的掷骰公式字段，例如技能的伤害。"""

    entity: str
    entry: str | None = None  # 条目名（技能名等）；模板本身的字段时为 null
    field: str
    params: dict[str, float] = {}  # 这个条目“使用时填写”的列这次填的数，例如 {"mp_spent": 20}
    reason: str = ""


class UseOut(_Out):
    """谁对谁用了哪个技能：引擎算好技能脚本的数值，裁定时再决定生效没有。"""

    source: str
    entry: str  # 条目名或 ID
    target: str | None = None
    params: dict[str, float] = {}
    reason: str = ""


class PlanOut(_Out):
    checks: list[CheckOut] = []
    rolls: list[RollOut] = []
    uses: list[UseOut] = []
    queries: list[SpatialQuery] = []

    @field_validator("queries", mode="before")
    @classmethod
    def _drop_unknown_keys(cls, v: object) -> object:
        """查询里模型顺手加的说明字段（例如 reason）不影响含义，去掉再校验。"""
        if not isinstance(v, list):
            return v
        allowed = set(SpatialQuery.model_fields)
        return [
            {k: x for k, x in cast(dict[str, object], q).items() if k in allowed}
            if isinstance(q, dict)
            else q
            for q in cast(list[object], v)
        ]


class OutputError(Exception):
    """输出不是合法的 JSON 或不符合结构。message 会回传给模型重试。"""


def extract_json(text: str) -> object:
    """从回复里取出第一个 JSON 对象，允许外面包着 ```json 代码块或少量文字。"""
    start = text.find("{")
    if start < 0:
        raise OutputError("no JSON object found in the reply")
    decoder = json.JSONDecoder()
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    raise OutputError("the reply contains no valid JSON object")


def parse[T: BaseModel](
    model: type[T], text: str, repair: Callable[[object], object] | None = None
) -> T:
    obj = extract_json(text)
    if repair is not None:
        obj = repair(obj)
    try:
        return model.model_validate(obj)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:20]
        )
        raise OutputError(f"JSON does not match the required structure: {details}") from e


def repair_adjudication(raw: object, owner: dict[str, str]) -> object:
    """修正模型常见的、含义无歧义的写法，不改变裁定的内容：

    - movements 里用 pos 表示终点 → to
    - encounters 里用 entities 表示参与者 → players；参与者或 observed_by 的键写成了实体 id → 换成控制它的玩家 id
    修正之后照样过完整的 schema 和引擎校验。
    """
    if not isinstance(raw, dict):
        return raw
    adj = dict(cast(dict[str, object], raw))
    mvs = adj.get("movements")
    if isinstance(mvs, list):
        fixed: list[object] = []
        for m in cast(list[object], mvs):
            if isinstance(m, dict):
                d = dict(cast(dict[str, object], m))
                if "to" not in d and "pos" in d:
                    d["to"] = d.pop("pos")
                fixed.append(d)
            else:
                fixed.append(m)
        adj["movements"] = fixed
    encs = adj.get("encounters")
    if isinstance(encs, list):
        out: list[object] = []
        for enc in cast(list[object], encs):
            if not isinstance(enc, dict):
                out.append(enc)
                continue
            d = dict(cast(dict[str, object], enc))
            if "players" not in d and "entities" in d:
                d["players"] = d.pop("entities")
            ps = d.get("players")
            if isinstance(ps, list):
                d["players"] = list(
                    dict.fromkeys(owner.get(str(p), str(p)) for p in cast(list[object], ps))
                )
            ob = d.get("observed_by")
            if isinstance(ob, dict):
                d["observed_by"] = {
                    owner.get(str(k), str(k)): v for k, v in cast(dict[str, object], ob).items()
                }
            out.append(d)
        adj["encounters"] = out
    return adj
