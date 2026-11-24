"""规则编辑器的技能脚本试运行。"""

from __future__ import annotations

import json

from tests.web.conftest import ROOT, Site


def _pack() -> dict[str, object]:
    text = (ROOT / "tests/fixtures/rulepack_single.json").read_text(encoding="utf-8")
    return json.loads(text)["pack"]


def test_try_script_plans_both_sides(site: Site) -> None:
    pack = _pack()
    sheet = pack["samples"][0]["sheet"]  # type: ignore[index]
    body = {
        "pack": pack,
        "script": 'target.damage(1d6 + this.level)\nif target.template == "person":\n    self.add(hp, 1)',
        "template": "person",
        "sheet": sheet,
        "entry": {"level": 2},
        "target_template": "person",
        "target_sheet": sheet,
    }
    r = site.admin.post("/api/admin/rulepacks/script/try", json=body).json()
    assert r["problems"] == []
    assert [(x["who"], x["op"]) for x in r["steps"]] == [("target", "damage"), ("self", "add")]
    dmg = r["steps"][0]
    assert len(dmg["rolls"]) == 1 and dmg["amount"] == dmg["rolls"][0] + 2
    assert "hp" in r["values"]["self"] and "hp" in r["values"]["target"]

    # 没有对象：target 的句子和问对象的 if 都跳过
    body.pop("target_template")
    body.pop("target_sheet")
    r = site.admin.post("/api/admin/rulepacks/script/try", json=body).json()
    assert r["steps"] == [] and "target" not in r["values"]


def test_try_script_reports_problems(site: Site) -> None:
    pack = _pack()
    body = {
        "pack": pack,
        "script": "self.damage(nope)",
        "template": "person",
        "sheet": pack["samples"][0]["sheet"],  # type: ignore[index]
    }
    r = site.admin.post("/api/admin/rulepacks/script/try", json=body).json()
    assert r["steps"] == []
    assert [p["code"] for p in r["problems"]] == ["formula.unknown_name"]
