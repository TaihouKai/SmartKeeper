"""技能命中的结算：使用者这一方（检定、几个取最好的、或定好的等级）对上对象的应对（检定、应对技能、或不抵抗）。

两边各按自己的检定算等级（1 起是成功，越大越好），再由技能的 hit 条件判命中；不写 hit 时：
没有检定也没有定好等级的必中；否则要成功，并且被对抗时等级高过对方（平手算对象赢）。
这里不掷应对技能的脚本、不碰世界状态；掷骰都经由 rules（随机数来自 engine 给的 faces）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    CheckResult,
    DiceResult,
    NotFound,
    RulePack,
    Rules,
    SkillConfig,
    ValidationFailed,
)


@dataclass(frozen=True, slots=True)
class Side:
    """一方：实体、模板、完整角色卡（含固定条目）、同伴。"""

    entity: str
    template: str
    sheet: dict[str, JsonValue]
    peers: dict[str, JsonValue | None]

    def as_target(self) -> tuple[str, JsonValue, Mapping[str, JsonValue | None]]:
        return (self.template, self.sheet, self.peers)


@dataclass(frozen=True, slots=True)
class Strike:
    """用技能那一刻就定下来的：掷好的骰子、定好的等级、难度、距离、对象有没有发现使用者。"""

    rolls: tuple[tuple[str, DiceResult], ...] = ()  # (检定, 骰子)
    auto_level: int | None = None
    difficulty: float = 0.0
    distance: float = 0.0
    unseen: bool = False

    def dump(self) -> dict[str, JsonValue]:
        return {
            "attack_rolls": [
                {"check": c, "roll": r.model_dump(mode="json")} for c, r in self.rolls
            ],
            "auto_level": self.auto_level,
            "difficulty": self.difficulty,
            "distance": round(self.distance, 2),
            "unseen": self.unseen,
        }

    @staticmethod
    def load(p: Mapping[str, JsonValue]) -> Strike:
        raw = p.get("attack_rolls")
        rolls: list[tuple[str, DiceResult]] = []
        for x in raw if isinstance(raw, list) else []:
            if isinstance(x, dict) and isinstance(x.get("roll"), dict):
                rolls.append((str(x.get("check", "")), DiceResult.model_validate(x["roll"])))
        auto = p.get("auto_level")
        diff = p.get("difficulty")
        dist = p.get("distance")
        return Strike(
            rolls=tuple(rolls),
            auto_level=int(auto) if isinstance(auto, int | float) else None,
            difficulty=float(diff) if isinstance(diff, int | float) else 0.0,
            distance=float(dist) if isinstance(dist, int | float) else 0.0,
            unseen=p.get("unseen") is True,
        )


@dataclass(frozen=True, slots=True)
class Result:
    attack: CheckResult | None  # 使用者的检定（几个时取最好的那个）；不掷骰时 None
    defense: CheckResult | None  # 对象的检定；没掷时 None
    level: int
    opp_level: int
    opposed: bool
    hit: bool

    def outcome(self, strike: Strike) -> dict[str, float]:
        """使用者的脚本里的数。"""
        return {
            "level": float(self.level),
            "opp_level": float(self.opp_level),
            "opposed": 1.0 if self.opposed else 0.0,
            "distance": strike.distance,
            "unseen": 1.0 if strike.unseen else 0.0,
        }

    def flipped(self, strike: Strike) -> dict[str, float]:
        """应对技能的脚本里的数：自己是对象那一方。"""
        return {
            "level": float(self.defense.level if self.defense else 0),
            "opp_level": float(self.level),
            "opposed": 1.0 if self.opposed else 0.0,
            "distance": strike.distance,
            "unseen": 0.0,
            "reacting": 1.0,
        }


class Duel:
    def __init__(self, rules: Rules, pack: RulePack, faces: f.Faces) -> None:
        self.rules = rules
        self.pack = pack
        self.faces = faces

    def roll_check(self, side: Side, check: str) -> DiceResult:
        dice = self.rules.check_spec(self.pack, check).dice
        return self.rules.roll(
            self.pack, dice, self.faces, side.template, side.sheet, None, side.peers
        )

    def evaluate(
        self,
        side: Side,
        text: str,
        fields: dict[str, JsonValue],
        target: Side | None,
        extra: Mapping[str, float],
    ) -> float:
        return self.rules.roll(
            self.pack,
            text,
            self.faces,
            side.template,
            side.sheet,
            fields,
            side.peers,
            target.as_target() if target else None,
            extra,
        ).total

    def strike(
        self,
        side: Side,
        cfg: SkillConfig,
        fields: dict[str, JsonValue],
        target: Side | None,
        distance: float,
        unseen: bool,
    ) -> Strike:
        """用技能的那一刻：使用者的检定都掷好，定好的等级和难度算好。"""
        extra = {"distance": distance, "unseen": 1.0 if unseen else 0.0}
        rolls = tuple((c, self.roll_check(side, c)) for c in cfg.check)
        auto = (
            math.floor(self.evaluate(side, cfg.auto_level, fields, target, extra))
            if cfg.auto_level.strip()
            else None
        )
        diff = (
            self.evaluate(side, cfg.difficulty, fields, target, extra)
            if cfg.difficulty.strip()
            else 0.0
        )
        return Strike(
            rolls=rolls, auto_level=auto, difficulty=diff, distance=distance, unseen=unseen
        )

    def defend(
        self, defender: Side, check: str, roll: DiceResult, attacker: Side, strike: Strike
    ) -> CheckResult:
        """对象自己的检定结果（难度不算在对象身上）；对方的点数取使用者掷得最高的那个。"""
        top = max((r for _c, r in strike.rolls), key=lambda r: r.total, default=None)
        return self.rules.resolve_check(
            self.pack,
            entity=defender.entity,
            template=defender.template,
            sheet=defender.sheet,
            check=check,
            roll=roll,
            difficulty=None,
            opponent=(attacker.entity, attacker.template, attacker.sheet, top) if top else None,
            peers=defender.peers,
            opp_check=strike.rolls[0][0] if strike.rolls else None,
            distance=strike.distance,
            vs_template=attacker.template,
        )

    def settle(
        self,
        attacker: Side,
        cfg: SkillConfig,
        fields: dict[str, JsonValue],
        strike: Strike,
        defender: Side | None,
        defense: tuple[str, DiceResult] | None,
        negated: bool = False,
    ) -> Result:
        """算两边的等级和命中。defense 是对象掷的 (检定, 骰子)；negated 是应对技能把这次使用作废了。"""
        opposed = defense is not None and defender is not None
        vs = defender.template if defender else ""
        attack: CheckResult | None = None
        d_res: CheckResult | None = None
        if defense is not None and defender is not None:
            d_res = self.defend(defender, defense[0], defense[1], attacker, strike)
        if strike.rolls:
            results = [
                self.rules.resolve_check(
                    self.pack,
                    entity=attacker.entity,
                    template=attacker.template,
                    sheet=attacker.sheet,
                    check=c,
                    roll=r,
                    difficulty=strike.difficulty,
                    opponent=(defender.entity, defender.template, defender.sheet, defense[1])
                    if defense is not None and defender is not None
                    else None,
                    peers=attacker.peers,
                    opp_check=defense[0] if defense is not None else None,
                    distance=strike.distance,
                    vs_template=vs,
                )
                for c, r in strike.rolls
            ]
            attack = max(results, key=lambda x: (x.level, x.roll.total))
            level = attack.level
        elif strike.auto_level is not None:
            level = strike.auto_level
        else:
            level = 1
        opp_level = d_res.level if d_res is not None else 0
        if negated:
            hit = False
        elif cfg.hit.strip():
            extra = {
                "distance": strike.distance,
                "unseen": 1.0 if strike.unseen else 0.0,
                "level": float(level),
                "opp_level": float(opp_level),
                "opposed": 1.0 if opposed else 0.0,
            }
            hit = self.evaluate(attacker, cfg.hit, fields, defender, extra) != 0
        elif not cfg.rolls:
            hit = True
        else:
            hit = level >= 1 and (not opposed or level > opp_level)
        return Result(
            attack=attack,
            defense=d_res,
            level=level,
            opp_level=opp_level,
            opposed=opposed,
            hit=hit,
        )

    def save(
        self, defender: Side, check: str, attacker: Side, strike: Strike
    ) -> CheckResult | None:
        """对象的豁免：对技能的难度做 check。做不了（没有这个检定、卡上缺字段）时 None。"""
        try:
            roll = self.roll_check(defender, check)
            return self.rules.resolve_check(
                self.pack,
                entity=defender.entity,
                template=defender.template,
                sheet=defender.sheet,
                check=check,
                roll=roll,
                difficulty=strike.difficulty,
                opponent=None,
                peers=defender.peers,
                distance=strike.distance,
                vs_template=attacker.template,
            )
        except (ValidationFailed, NotFound):
            return None
