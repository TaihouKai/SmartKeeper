"""结盟：玩家之间互相同意以后，双方的角色互为友军；任何一方可以随时单方面解除。

全部记在事件日志里（alliance_change，只有 KP 看得到），当前的结盟和待回应的提议由日志折叠出来；
给当事玩家的通知另记 alliance_notice（只给那个玩家，带他对另一方的叫法）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import JsonValue

from smartkeeper.contracts import Event

CHANGE = "alliance_change"
NOTICE = "alliance_notice"


@dataclass(frozen=True, slots=True)
class Proposal:
    id: int  # 提议那条事件的 seq
    by: str  # 提议的玩家
    to: str | None  # 对方玩家；对着 NPC 提的是 None（永远没人回应）
    entity: str  # 提议时指着的对方实体


@dataclass(frozen=True, slots=True)
class Pact:
    id: int  # 结成那条事件的 seq
    players: frozenset[str]


@dataclass(slots=True)
class Alliances:
    pending: dict[int, Proposal] = field(default_factory=dict[int, Proposal])
    pacts: dict[int, Pact] = field(default_factory=dict[int, Pact])

    def allied(self, a: str, b: str) -> bool:
        """两个玩家是不是盟友（同一个玩家算）。"""
        return a == b or any({a, b} == set(p.players) for p in self.pacts.values())

    def pact_between(self, a: str, b: str) -> Pact | None:
        return next((p for p in self.pacts.values() if {a, b} == set(p.players)), None)


def _str(v: JsonValue) -> str | None:
    return v if isinstance(v, str) else None


def fold(events: Iterable[Event]) -> Alliances:
    out = Alliances()
    for e in events:
        if e.type != CHANGE:
            continue
        p = e.payload
        kind = p.get("kind")
        if kind == "proposed":
            out.pending[e.seq] = Proposal(
                e.seq, str(p.get("by")), _str(p.get("to")), str(p.get("entity"))
            )
        elif kind in ("declined", "cancelled"):
            out.pending.pop(int(str(p.get("proposal"))), None)
        elif kind == "formed":
            players = frozenset(str(x) for x in p.get("players") or [] if isinstance(x, str))  # type: ignore[union-attr]
            out.pending = {k: v for k, v in out.pending.items() if {v.by, v.to} != set(players)}
            out.pacts[e.seq] = Pact(e.seq, players)
        elif kind == "broken":
            out.pacts.pop(int(str(p.get("pact"))), None)
    return out
