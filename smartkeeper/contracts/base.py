"""所有契约类型的基类：不可变、禁止多余字段。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

__all__ = ["Frozen", "JsonDict", "JsonValue"]

type JsonDict = dict[str, JsonValue]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
