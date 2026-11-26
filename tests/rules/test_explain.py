"""技能设置、脚本、常驻加成写成句子：名字换成显示名，局部变量代回去，没有代码。"""

from pydantic import JsonValue

from smartkeeper.rules import RulesService
from tests.fixtures import load_pack

WORDS = {
    "ex.self": "自己",
    "ex.target": "对象",
    "ex.of": "{who}的{what}",
    "ex.this_of": "{what}",
    "ex.c.range": "射程 {x} 米",
    "ex.c.check": "命中：掷{x}检定",
    "ex.c.cooldown": "冷却 {x} 分钟",
    "ex.s.damage": "对{who}造成 {x} 点伤害",
    "ex.s.add": "{what}增加 {x}",
    "ex.s.if": "如果{c}：",
    "ex.s.minutes": "，持续 {x} 分钟",
    "ex.fn.floor": "{x}（向下取整）",
    "ex.b.line": "常驻：{what}变为 {x}",
    "ex.is_not": "{who}不是{what}",
    "ex.list_sep": "、",
    "ex.params": "使用时可以选：{x}",
}


def test_config_script_and_bonus_become_sentences(rules: RulesService) -> None:
    pack = load_pack("single")
    tpl = pack.templates[0]
    hp = next(f for f in tpl.fields if f.name == "hp")
    str_label = next(f for f in tpl.fields if f.name == "str").label or "str"
    entry: JsonValue = {
        "config": "range = 30\ncooldown = range / 3",
        "script": (
            "n = floor(self.str / 10)\n"
            'if target.template != "person":\n'
            "    target.damage(n * 2)\n"
            "with minutes(5):\n"
            "    target.hp += 1"
        ),
        "bonus": "self.str += 1",
    }
    lines = rules.explain(pack, "person", "skills", entry, WORDS)
    text = [(x.depth, x.text) for x in lines]
    assert (0, "射程 30 米") in text
    assert (0, "冷却 30 ÷ 3 分钟") in text  # 设置的各项互相引用：代回去
    damage = next(t for d, t in text if t.startswith("对对象造成"))
    assert "（向下取整）" in damage and "n" not in damage.replace("（向下取整）", "")
    assert any(t.startswith("如果") and "不是" in t for _, t in text)
    assert any(d == 1 for d, t in text if t.startswith("对对象造成"))
    assert (0, f"对象的{hp.label or 'hp'}增加 1，持续 5 分钟") in text
    assert (0, f"常驻：{str_label}变为 {str_label} + 1") in text
    for code in ("self.", "target.", "floor(", "+=", "minutes("):
        assert all(code not in t for _, t in text)


def test_broken_code_is_skipped(rules: RulesService) -> None:
    pack = load_pack("single")
    assert (
        rules.explain(pack, "person", "skills", {"config": "range = (", "script": "x("}, WORDS)
        == []
    )
