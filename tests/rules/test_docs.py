"""语法手册：公式语言、技能设置、脚本、检定代码里的每一样都有一条，说明都有中英文翻译。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smartkeeper import lang as f
from smartkeeper.rules import RulesService, checkconfig, skillconfig

I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"


def names(category: str) -> set[str]:
    return {d.name for d in RulesService().docs() if d.category == category}


def test_every_part_of_the_language_is_documented() -> None:
    assert names("function") == set(f.FUNCTIONS)
    assert names("verb") == set(f.VERBS)
    assert names("config") == set(skillconfig.KEYS)
    assert names("shape") == {*skillconfig.SHAPES, "placement"}
    assert set(skillconfig.SCRIPT_VARS) <= names("variable")
    assert {*checkconfig.KEYS, *checkconfig.VARS} == names("check")
    placement = next(
        d for d in RulesService().docs() if d.name == "placement" and d.category == "shape"
    )
    assert [p for p, _ in placement.params] == list(skillconfig.PLACEMENT_ARGS)


def lookup(table: dict[str, Any], key: str) -> object:
    node: object = table
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]  # type: ignore[index]
    return node


def test_every_description_is_translated() -> None:
    keys = {d.desc for d in RulesService().docs()}
    keys |= {k for d in RulesService().docs() for _, k in d.params}
    for lang in ("zh", "en"):
        table = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if not isinstance(lookup(table, k), str))
        assert missing == [], (lang, missing)
