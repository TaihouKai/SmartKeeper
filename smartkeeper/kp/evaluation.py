"""回放出题：从一局的事件日志自动生成事实问答，对检索和声明核对跑召回率。

改 prompt 或换模型后重跑，对比前后数值。

- 正例：每条标了两个以上实体的记事条目，对每个“自己的实体在里面、那一轮收到了反馈”的玩家，
  生成一条“我以前……”的引用，期望核对结果成立；同时检查按实体检索能取回这条条目。
- 反例：从没在同一条记事条目里一起出现过的两个实体，生成一条编造的引用，期望核对结果不成立。
"""

from __future__ import annotations

import itertools
from typing import Literal

from pydantic import BaseModel

from smartkeeper.contracts import KP as KP_AUDIENCE
from smartkeeper.contracts import Adjudication
from smartkeeper.engine import Engine
from smartkeeper.kp.pipeline import KP
from smartkeeper.kp.render import replace_entity_tokens

FABRICATED = {
    "zh": "我记得 {a} 和 {b} 之前当众大吵过一架。",
    "en": "I remember {a} and {b} having a loud public fight earlier.",
}


class QuizItem(BaseModel):
    player_id: str
    claim: str
    entities: list[str]
    expected: Literal["holds", "fails"]
    adjudication_seq: int | None = None


class QuizReport(BaseModel):
    items: int
    positives: int
    negatives: int
    retrieval_recall: float | None
    claim_recall: float | None = None
    claim_specificity: float | None = None


def build_quiz(engine: Engine, game_id: str, max_negatives: int = 20) -> list[QuizItem]:
    lang = engine.game(game_id).settings.kp_language
    kp_view = engine.view_for(game_id, KP_AUDIENCE)
    feedback_rounds: dict[str, set[int]] = {}
    for e in kp_view:
        if e.type == "feedback":
            for p in e.visibility.players:
                feedback_rounds.setdefault(p, set()).add(e.round_no)
    controls = {p.id: set(engine.controlled(game_id, p.id)) for p in engine.players(game_id)}
    labels = {
        p.id: {h.entity_id: f"@{h.label}" for h in engine.handles(p.id)}
        for p in engine.players(game_id)
    }
    items: list[QuizItem] = []
    together: set[frozenset[str]] = set()
    for e in kp_view:
        if e.type != "adjudication":
            continue
        adj = Adjudication.model_validate(e.payload["adjudication"])
        for m in adj.memory_entries:
            for a, b in itertools.combinations(sorted(set(m.entities)), 2):
                together.add(frozenset((a, b)))
            if len(set(m.entities)) < 2:
                continue
            for pid, mine in controls.items():
                if not (mine & set(m.entities)) or e.round_no not in feedback_rounds.get(
                    pid, set()
                ):
                    continue
                own = {x: ("我" if lang == "zh" else "I") for x in mine}
                text = replace_entity_tokens(m.text, {**labels[pid], **own}, "?")
                items.append(
                    QuizItem(
                        player_id=pid,
                        claim=("我记得：" if lang == "zh" else "I remember: ") + text,
                        entities=sorted(set(m.entities)),
                        expected="holds",
                        adjudication_seq=e.seq,
                    )
                )
    negatives = 0
    for pid, mine in controls.items():
        known = sorted(set(labels[pid]) - mine)
        for a, b in itertools.combinations(known, 2):
            if negatives >= max_negatives:
                break
            if frozenset((a, b)) in together:
                continue
            claim = FABRICATED.get(lang, FABRICATED["en"]).format(
                a=labels[pid][a], b=labels[pid][b]
            )
            items.append(QuizItem(player_id=pid, claim=claim, entities=[a, b], expected="fails"))
            negatives += 1
    return items


def retrieval_recall(engine: Engine, game_id: str, quiz: list[QuizItem]) -> float | None:
    """正例里，按实体检索能取回对应记事条目的比例。"""
    pos = [q for q in quiz if q.expected == "holds"]
    if not pos:
        return None
    hit = 0
    for q in pos:
        mine = set(engine.controlled(game_id, q.player_id))
        got = engine.recall(game_id, q.entities, (), sorted(mine & set(q.entities)))
        if any(m.source_seq == q.adjudication_seq for m in got):
            hit += 1
    return hit / len(pos)


def run_quiz(kp: KP, game_id: str, quiz: list[QuizItem], with_claims: bool = True) -> QuizReport:
    pos = [q for q in quiz if q.expected == "holds"]
    neg = [q for q in quiz if q.expected == "fails"]
    report = QuizReport(
        items=len(quiz),
        positives=len(pos),
        negatives=len(neg),
        retrieval_recall=retrieval_recall(kp.engine, game_id, quiz),
    )
    if not with_claims:
        return report

    def verdict(q: QuizItem) -> str:
        return kp.check_claim(game_id, q.player_id, q.claim).verdict

    if pos:
        report.claim_recall = sum(verdict(q) in ("holds", "partial") for q in pos) / len(pos)
    if neg:
        report.claim_specificity = sum(verdict(q) == "fails" for q in neg) / len(neg)
    return report
