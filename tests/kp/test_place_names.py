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
