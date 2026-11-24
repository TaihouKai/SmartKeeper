"""0006 迁移：施放时间、冷却、范围形状、设置物搬进技能设置。"""

import importlib.util
from pathlib import Path
from typing import Any

from smartkeeper.rules import RulesService

PATH = Path(__file__).parents[2] / "smartkeeper/web/migrations/versions/0006_skill_config.py"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("m0006", PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_moved_into_config() -> None:
    m = load()
    entries = [
        {
            "name": "trap",
            "fields": {},
            "script": "",
            "cast_time": "2",
            "cooldown": "",
            "shape": {"kind": "sphere", "radius": 5, "length": None},
            "placement": {
                "radius": "3",
                "perceive_multiplier": "0.5",
                "charges": "",
                "duration": "120",
                "notify_owner": False,
            },
        },
        {"name": "bolt", "fields": {}, "script": "target.damage(1)", "cooldown": "this.level * 2"},
        {"name": "heal", "fields": {}, "script": "self.add(hp, 1)"},
    ]
    out = m.convert({"groups": {"skills": entries}})["groups"]["skills"]
    trap, bolt, heal = out
    assert trap["config"].splitlines() == [
        'target = "none"',
        "cast_time = 2",
        "shape = sphere(radius=5)",
        "placement = placement(radius=3, perceive=0.5, duration=2, notify=False)",
    ]
    assert not {"cast_time", "cooldown", "shape", "placement"} & set(trap)
    assert bolt["config"] == "cooldown = this.level * 2"
    assert heal["config"] == 'target = "self"'
    cfg = RulesService().skill_config(trap["config"])
    assert (
        cfg.target == "none" and cfg.placement is not None and cfg.placement.notify_owner is False
    )
