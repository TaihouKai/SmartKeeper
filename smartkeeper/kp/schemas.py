"""各种调用的输出结构。LLM 的输出一律在本地解析和校验，失败带着错误重试。"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from smartkeeper.contracts import AdHocCheck, Location, Point, SpatialQuery


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ReviewOut(_Out):
    approved: bool
    comments: str = ""


class OpeningOut(_Out):
    broadcast: str
    messages: dict[str, str]
    positions: dict[str, Location] = {}


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


class ClaimOut(_Out):
    text: str
    refs: list[str] = []
    features: list[str] = []


class IntentOut(_Out):
    items: list[ItemOut]
    claims: list[ClaimOut] = []
    unresolved: list[str] = []


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


class PlanOut(_Out):
    checks: list[CheckOut] = []
    queries: list[SpatialQuery] = []


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


def parse[T: BaseModel](model: type[T], text: str) -> T:
    obj = extract_json(text)
    try:
        return model.model_validate(obj)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:20]
        )
        raise OutputError(f"JSON does not match the required structure: {details}") from e
