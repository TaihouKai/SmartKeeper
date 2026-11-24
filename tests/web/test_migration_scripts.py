"""0004 迁移：作用效果和限时效果换成技能脚本，self.<列> 换成 this.<列>。"""

import importlib.util
from pathlib import Path
from typing import Any

PATH = Path(__file__).parents[2] / "smartkeeper/web/migrations/versions/0004_skill_scripts.py"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("m0004", PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_entries_become_scripts() -> None:
    m = load()
    entry = {
        "name": "ward",
        "fields": {"level": 2, "damage": "self.level d 6"},
        "effects": [
            {
                "target": "speed",
                "formula": "speed + self.level",
                "duration": "30",
                "priority": None,
            },
            {"target": "def", "formula": "def + 1", "duration": ""},
        ],
        "actions": [
            {"who": "target", "op": "damage", "field": None, "amount": "self.damage"},
            {"who": "self", "op": "add", "field": "shield", "amount": "4", "duration": "120"},
            {"op": "subtract", "field": "mp", "amount": "2", "duration": ""},
        ],
        "cast_time": "self.level",
    }
    out = m.convert({"pack": {"x": [entry]}})["pack"]["x"][0]
    assert "actions" not in out
    assert out["fields"]["damage"] == "this.level d 6"
    assert out["effects"] == [{"target": "def", "formula": "def + 1"}]
    assert out["cast_time"] == "this.level"
    assert out["script"].splitlines() == [
        "target.modify(speed, speed + this.level, 0.5)",
        "target.damage(this.damage)",
        "self.add(shield, 4, 2)",
        "target.sub(mp, 2)",
    ]


def test_status_modifier_loses_duration_and_text_is_left_alone() -> None:
    m = load()
    data = {
        "statuses": [{"tag": "t", "modifier": {"target": "a", "formula": "a", "duration": "5"}}],
        "description": "self.level stays",
    }
    out = m.convert(data)
    assert out["statuses"][0]["modifier"] == {"target": "a", "formula": "a"}
    assert out["description"] == "self.level stays"
