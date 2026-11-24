from pydantic import JsonValue

from smartkeeper.contracts import AdHocCheck, DiceResult
from smartkeeper.rules import RulesService
from tests.fixtures import load_pack


def roll(n: int) -> DiceResult:
    return DiceResult(expr="1d100", rolls=(n,), total=n)


def sheet(**fields: JsonValue) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "appearance": "a",
        "occupation": "doctor",
        "str": 50,
        "dex": 60,
        "per": 40,
    }
    return {"name": "X", "fields": {**base, **fields}}


def test_levels(rules: RulesService) -> None:
    pack = load_pack("single")

    def level(n: int) -> str:
        return rules.resolve_check(
            pack, entity="e", template="person", sheet=sheet(), check="spot", roll=roll(n)
        ).level

    assert level(8) == "critical_success"
    assert level(40) == "success"
    assert level(41) == "failure"


def test_opposed(rules: RulesService) -> None:
    pack = load_pack("single")
    r = rules.resolve_check(
        pack,
        entity="a",
        template="person",
        sheet=sheet(),
        check="struggle",
        roll=roll(30),
        opponent=("b", "person", sheet(str=20), roll(10)),
    )
    assert (r.level, r.opponent, r.opp_target) == ("success", "b", 20)


def test_difficulty(rules: RulesService) -> None:
    pack = load_pack("multi")
    s = pack.samples[0].sheet
    kw = {"entity": "a", "template": "leader", "sheet": s, "check": "assault", "difficulty": 15.0}
    assert rules.resolve_check(pack, roll=roll(13), **kw).level == "success"  # type: ignore[arg-type]
    assert rules.resolve_check(pack, roll=roll(12), **kw).level == "failure"  # type: ignore[arg-type]


def test_adhoc(rules: RulesService) -> None:
    spec = AdHocCheck(dice="1d100", target=30)
    assert rules.resolve_adhoc("e", spec, roll(30)).level == "success"
    assert rules.resolve_adhoc("e", spec, roll(31)).level == "failure"


def test_fixed_order_and_opposed_difficulty(rules: RulesService) -> None:
    from smartkeeper.contracts import CheckDef

    pack = load_pack("single")
    d20 = CheckDef(
        name="per20",
        config="dice = 1d20 + per\ncritical_success = natural == 20\ncritical_failure = natural == 1\nsuccess = roll > difficulty",
    )
    pack = pack.model_copy(update={"checks": (*pack.checks, d20)})

    def level(n: int, difficulty: float | None = 10, opp: int | None = None) -> str:
        r = DiceResult(expr="1d20 + per", rolls=(n,), total=n + 40)
        o = (
            ("b", "person", sheet(), DiceResult(expr="1d20", rolls=(opp,), total=opp))
            if opp
            else None
        )
        return rules.resolve_check(
            pack,
            entity="e",
            template="person",
            sheet=sheet(),
            check="per20",
            roll=r,
            difficulty=difficulty,
            opponent=o,
        ).level

    assert level(20) == "critical_success"
    assert level(1) == "critical_failure"  # 先看大失败再看成功：41 > 10 也是大失败
    assert level(5) == "success"
    assert level(5, difficulty=50) == "failure"
    # 对抗：难度就是对方的点数
    assert level(5, difficulty=None, opp=44) == "success"
    assert level(5, difficulty=None, opp=46) == "failure"


def test_checks_can_branch_on_templates(rules: RulesService) -> None:
    from smartkeeper.contracts import CheckDef

    pack = load_pack("single")
    code = (
        'dice = 1d20 + per if self.template == "person" else 1d20\n'
        'success = roll > difficulty + (5 if opponent.template == "person" else 0)'
    )
    assert rules.validate_formula(pack, None, code, None, "check") == []
    bad = rules.validate_formula(
        pack, None, "dice = 1d20 + opponent.template\nsuccess = True", None, "check"
    )
    assert [p.code for p in bad] == ["formula.unknown_name"]  # 掷骰时还不知道对手
    pack = pack.model_copy(update={"checks": (*pack.checks, CheckDef(name="t", config=code))})
    s = sheet()
    r = DiceResult(expr="x", rolls=(10,), total=12)
    opp = DiceResult(expr="x", rolls=(5,), total=9)
    kw = {"entity": "a", "template": "person", "sheet": s, "check": "t", "roll": r}
    # 对手是 person：难度 9 + 5，打不过
    assert rules.resolve_check(pack, opponent=("b", "person", s, opp), **kw).level == "failure"  # type: ignore[arg-type]
    assert rules.resolve_check(pack, difficulty=9, **kw).level == "success"  # type: ignore[arg-type]
