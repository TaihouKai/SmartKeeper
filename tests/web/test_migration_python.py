"""0005 迁移：公式和脚本换成 Python 写法。"""

import importlib.util
from pathlib import Path
from typing import Any

from smartkeeper.lang import parse, parse_script

PATH = Path(__file__).parents[2] / "smartkeeper/web/migrations/versions/0005_python_syntax.py"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("m0005", PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_formulas() -> None:
    m = load()
    cases = {
        "str + 1": "str + 1",
        "3d6 + 2": "3d6 + 2",
        "this.level d 6 + 1": "dice(this.level, 6) + 1",
        'if(cls = "warrior", 2, 3)': '2 if cls == "warrior" else 3',
        "and(a > 1, or(b, not(c)))": "a > 1 and (b or not c)",
        "d%": "d%",
        "((2) d (6))": "2d6",
        "": "",
        "just some words": "just some words",
    }
    for old, new in cases.items():
        assert m.formula(old) == new, old
        if new.strip():
            try:
                parse(new)
            except Exception:  # 本来就不是公式的文字
                assert new == old


def test_pack_and_script() -> None:
    m = load()
    pack = {
        "derived": [{"name": "hp", "formula": "if(con > 10, con, 10)"}],
        "groups": [
            {
                "presets": [
                    {
                        "name": "bolt",
                        "description": "x = 1 stays",
                        "when": 'job = "mage"',
                        "fields": {"damage": "level d 4", "level": 2, "note": "hello"},
                        "script": (
                            "# zap\n"
                            "target.damage(this.damage)\n"
                            'if target.template = "monster":\n'
                            "    target.sub(mp, if(this.level > 1, 2, 1)); self.add(hp, 1)\n"
                            "else:\n"
                            "    pass_ = 1\n"
                        ),
                    },
                    {"name": "ok", "script": "target.damage(this.damage)  # keep comments"},
                ]
            }
        ],
    }
    out = m.convert(pack)
    assert out["derived"][0]["formula"] == "con if con > 10 else 10"
    p = out["groups"][0]["presets"][0]
    assert p["description"] == "x = 1 stays"
    assert p["when"] == 'job == "mage"'
    assert p["fields"] == {"damage": "dice(level, 4)", "level": 2, "note": "hello"}
    assert p["script"].splitlines() == [
        "# zap",
        "target.damage(this.damage)",
        'if target.template == "monster":',
        "    target.sub(mp, 2 if this.level > 1 else 1); self.add(hp, 1)",
        "else:",
        "    pass_ = 1",
    ]
    assert out["groups"][0]["presets"][1]["script"] == "target.damage(this.damage)  # keep comments"
    parse_script(out["groups"][0]["presets"][1]["script"])
