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

    assert level(8) == "critical"
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
    assert (r.level, r.opponent, r.opp_target) == ("win", "b", 20)


def test_difficulty(rules: RulesService) -> None:
    pack = load_pack("multi")
    s = pack.samples[0].sheet
    kw = {"entity": "a", "template": "leader", "sheet": s, "check": "assault", "difficulty": 15.0}
    assert rules.resolve_check(pack, roll=roll(13), **kw).level == "hit"  # type: ignore[arg-type]
    assert rules.resolve_check(pack, roll=roll(12), **kw).level == "miss"  # type: ignore[arg-type]


def test_adhoc(rules: RulesService) -> None:
    spec = AdHocCheck(dice="1d100", target=30)
    assert rules.resolve_adhoc("e", spec, roll(30)).level == "success"
    assert rules.resolve_adhoc("e", spec, roll(31)).level == "failure"
