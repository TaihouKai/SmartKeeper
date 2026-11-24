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

    def level(n: int) -> tuple[int, str]:
        r = rules.resolve_check(
            pack, entity="e", template="person", sheet=sheet(), check="spot", roll=roll(n)
        )
        return r.level, r.level_name

    assert level(8) == (2, "extreme")
    assert level(40) == (1, "success")
    assert level(41) == (0, "failure")


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
    # 对方也按自己的检定算等级：20 - 10 = 10 不大于 50 - 30 = 20，失败
    assert (r.level, r.opponent, r.opp_target, r.opp_level) == (1, "b", 20, 0)


def test_difficulty(rules: RulesService) -> None:
    pack = load_pack("multi")
    s = pack.samples[0].sheet
    kw = {"entity": "a", "template": "leader", "sheet": s, "check": "assault", "difficulty": 15.0}
    assert rules.resolve_check(pack, roll=roll(13), **kw).level == 1  # type: ignore[arg-type]
    assert rules.resolve_check(pack, roll=roll(12), **kw).level == 0  # type: ignore[arg-type]


def test_adhoc(rules: RulesService) -> None:
    spec = AdHocCheck(dice="1d100", target=30)
    assert rules.resolve_adhoc("e", spec, roll(30)).level == 1
    assert rules.resolve_adhoc("e", spec, roll(31)).level == 0


def test_level_formula_difficulty_and_distance(rules: RulesService) -> None:
    from smartkeeper.contracts import CheckDef

    pack = load_pack("single")
    d20 = CheckDef(
        name="per20",
        config=(
            "dice = 1d20 + per\n"
            "level = 0 if roll - difficulty - floor(distance / 500) <= 50 "
            "else 1 if roll - difficulty - floor(distance / 500) <= 55 else 2\n"
            'levels = ["fail", "ok", "great"]'
        ),
    )
    pack = pack.model_copy(update={"checks": (*pack.checks, d20)})
    assert rules.validate_pack(pack) == []

    def level(
        n: int, difficulty: float | None = None, opp: int | None = None, distance: float = 0
    ) -> int:
        r = DiceResult(expr="1d20 + per", rolls=(n,), total=n + 40)
        o = (
            ("b", "person", sheet(), DiceResult(expr="1d20", rolls=(opp,), total=opp + 40))
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
            distance=distance,
        ).level

    assert level(10) == 0
    assert level(11) == 1
    assert level(16) == 2
    assert level(16, difficulty=3) == 1
    assert level(16, distance=1200) == 1  # 每 500 米难度加 1
    # 对抗时难度不再被对方的点数替换：两边各算各的等级
    assert level(16, opp=20) == 2


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
    # 对手是 person：12 > 0 + 5 成功；有难度 9 时 12 > 9 + 5 不成立
    assert rules.resolve_check(pack, opponent=("b", "person", s, opp), **kw).level == 1  # type: ignore[arg-type]
    assert rules.resolve_check(pack, difficulty=9, vs_template="person", **kw).level == 0  # type: ignore[arg-type]
    assert rules.resolve_check(pack, difficulty=9, **kw).level == 1  # type: ignore[arg-type]
