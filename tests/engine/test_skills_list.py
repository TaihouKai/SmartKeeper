"""玩家能主动用的技能清单：有设置或脚本的条目、物品的用途；不含只有常驻加成的、物品本身；冷却中的标出来。"""

from __future__ import annotations

from smartkeeper.contracts import PatchOp
from tests.engine.test_uses import table


def test_lists_active_entries_and_item_uses_with_cooldowns() -> None:
    t, a, _b = table()
    e, g = t.engine, t.game_id
    p0 = t.players[0]
    names = [s.name for s in e.skills(g, p0)]
    assert names == [
        "burst",
        "call",
        "recall",
        "fly",
        "camp",
        "kit/zap",
        "kit/arm",
        "kit/hype",
        "kit/try",
        "kit/sense",
    ]
    assert "first aid" not in names and "kit" not in names  # 只有加成的、物品本身不算
    assert {s.entity_id for s in e.skills(g, p0)} == {a}
    e.admin_patch(
        g,
        [
            PatchOp(
                op="add",
                path=f"/entities/{a}/sheet/statuses/-",
                value={"tag": "cooldown:burst", "source": "burst", "expires_at": None},
            )
        ],
    )
    cooling = {s.name for s in e.skills(g, p0) if s.cooldown}
    assert cooling == {"burst"}
