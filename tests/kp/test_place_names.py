"""KP 的上下文里，写给一个玩家的调用只列他知道的地点名字；裁定能看到全部和谁知道。"""

from __future__ import annotations

from smartkeeper.contracts import PatchOp
from tests.kp.harness import new_game


def test_writers_only_see_names_their_reader_knows() -> None:
    g = new_game(2)
    e = g.engine
    p0, p1 = g.players
    e.admin_patch(
        g.game_id,
        [
            PatchOp(
                op="add",
                path="/places/place_9",
                value={"name": "秘密据点", "pos": {"x": 10, "y": 10, "z": 0}, "public": False},
            )
        ],
    )
    assert "秘密据点" not in g.kp.ctx.chat(p0).user
    e.post_kp_chat(p0, "{{place:秘密据点}}就在那里。", from_kp=True)
    assert "秘密据点" in g.kp.ctx.chat(p0).user
    assert "秘密据点" not in g.kp.ctx.chat(p1).user
    judge = g.kp.ctx.adjudicate(g.game_id).user
    assert '"name": "秘密据点"' in judge and f'"{p0}"' in judge.split("秘密据点", 1)[1][:400]


def test_someone_first_seen_this_round_is_named_before_the_feedback_is_written() -> None:
    """本轮才见到的人：写反馈之前就有了外号，反馈里用外号，而不是临时的“某人”。"""
    import copy

    from smartkeeper.llm import FakeCall

    g = new_game(1)
    e = g.engine
    (pid,) = g.players
    state = e.world_state(g.game_id)
    thief = copy.deepcopy(state["entities"]["npc_thief"])  # type: ignore[index]
    thief["pos"] = {"x": 190.0, "y": 190.0, "z": 0.0}  # type: ignore[index]
    e.admin_patch(g.game_id, [PatchOp(op="add", path="/entities/npc_far", value=thief)])
    assert "npc_far" not in {h.entity_id for h in e.handles(pid)}
    adjudicate = g.llm.handlers["adjudicate"]

    def far(c: FakeCall) -> str:
        return adjudicate(c).replace("{{npc_thief}}", "{{npc_far}}")

    g.llm.on("adjudicate", far)
    g.play_round()
    label = next(h.label for h in e.handles(pid) if h.entity_id == "npc_far")
    feedback = g.llm.by_purpose("feedback")[-1].prompt
    assert f"@{label}" in feedback.split("## 该玩家本轮的结果")[1][:200]
