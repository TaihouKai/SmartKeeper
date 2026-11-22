from smartkeeper.contracts import PatchOp
from smartkeeper.kp import build_quiz, run_quiz
from tests.kp.harness import new_game


def test_replay_quiz_measures_retrieval_and_claims() -> None:
    g = new_game(3)
    p1, p2, p3 = g.players
    a, b, c = g.ents(p1)[0], g.ents(p2)[0], g.ents(p3)[0]
    # 让三个人互相看得见，彼此都有代号
    g.engine.admin_patch(
        g.game_id,
        [
            PatchOp(
                op="replace", path=f"/entities/{e}/pos", value={"x": -50 + i * 3, "y": -60, "z": 0}
            )
            for i, e in enumerate((a, b, c))
        ],
    )
    g.engine.refresh_handles(g.game_id)
    g.round_hooks[1] = {
        "memory_entries": [{"entities": [a, b], "text": "{{" + a + "}} 推了 {{" + b + "}} 一把"}]
    }
    g.round_hooks[2] = {"memory_entries": [{"entities": [b], "text": "{{" + b + "}} 独自离开"}]}
    g.play_round()
    g.play_round()
    quiz = build_quiz(g.engine, g.game_id)
    pos = [q for q in quiz if q.expected == "holds"]
    neg = [q for q in quiz if q.expected == "fails"]
    assert {q.player_id for q in pos} == {p1, p2}  # 第三个玩家不在那条条目里
    assert any("我" in q.claim for q in pos)
    assert neg and all(set(q.entities) != {a, b} for q in neg)
    report = run_quiz(g.kp, g.game_id, quiz)
    assert report.retrieval_recall == 1.0
    assert report.claim_recall == 1.0  # 假模型总是回答成立
    assert report.claim_specificity == 0.0
