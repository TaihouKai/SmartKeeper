"""剧本文件的结构化部分：Markdown 开头的 YAML front matter。正文是给 KP 和玩家读的自由文字。

scenario_public.md 的 front matter：
    start_time: "2030-01-01T22:00"      # 游戏内起始时刻，显示用
    identities:                         # 可选
      mode: draw | choose
      options: [{id, name, description}]

scenario_kp.md 的 front matter：
    npcs: [{id, template, sheet, location: {place: "地名", floor: 3}}]     # location 可省略，由 KP 开场时决定
    initial_positions: {<身份 id 或玩家显示名>: {place: "地名"}}             # 可省略，由 KP 开场时决定
  位置可以写地名（place，可加 floor 楼层或 roof: true），也可以直接写坐标（pos: {x, y, z} 米，inside 建筑 id）。
"""

from __future__ import annotations

from typing import Any, cast

import yaml
from pydantic import JsonValue, ValidationError

from smartkeeper.contracts import Frozen, IdentityRules, Place, Problem, ValidationFailed


class NpcSpec(Frozen):
    id: str
    template: str
    sheet: dict[str, JsonValue]
    location: Place | None = None


class PublicMeta(Frozen):
    start_time: str | None = None
    identities: IdentityRules = IdentityRules()


class KpMeta(Frozen):
    npcs: tuple[NpcSpec, ...] = ()
    initial_positions: dict[str, Place] = {}


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip("﻿")
    if not stripped.startswith("---"):
        return {}, text
    lines = stripped.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                meta: object = yaml.safe_load("\n".join(lines[1:i])) or {}
            except yaml.YAMLError as e:
                raise ValidationFailed("scenario.bad_yaml", reason=str(e)) from e
            if not isinstance(meta, dict):
                raise ValidationFailed("scenario.bad_front_matter")
            return cast(dict[str, Any], meta), "\n".join(lines[i + 1 :]).lstrip("\n")
    raise ValidationFailed("scenario.unterminated_front_matter")


def _parse[T: Frozen](model: type[T], meta: dict[str, Any], code: str) -> T:
    try:
        return model.model_validate(meta)
    except ValidationError as e:
        raise ValidationFailed(
            code,
            [
                Problem(code="scenario.malformed", path=".".join(str(x) for x in err["loc"]))
                for err in e.errors()
            ],
        ) from e


def public_meta(text: str) -> PublicMeta:
    return _parse(PublicMeta, split_front_matter(text)[0], "scenario.bad_public")


def kp_meta(text: str) -> KpMeta:
    return _parse(KpMeta, split_front_matter(text)[0], "scenario.bad_kp")
