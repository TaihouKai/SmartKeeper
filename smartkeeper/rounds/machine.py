"""回合状态机：collecting（行动期）→ adjudicating（裁定中）→ review（待审核）→ published（已发布）。"""

from __future__ import annotations

from smartkeeper.contracts import IllegalState, RoundStatus

TRANSITIONS: dict[tuple[RoundStatus, str], RoundStatus] = {
    ("collecting", "declare"): "collecting",  # 提交或覆盖行动声明
    ("collecting", "close"): "adjudicating",  # 全员提交或强制结算
    ("adjudicating", "roll"): "adjudicating",  # 掷骰、检定、空间查询
    ("adjudicating", "restart"): "adjudicating",  # 进程重启后重跑
    ("adjudicating", "to_review"): "review",  # 裁定通过校验，或重试用尽
    ("review", "edit"): "review",  # 保存对裁定或反馈草稿的修改
    ("review", "rerun"): "adjudicating",  # 整轮重跑
    ("review", "publish"): "published",
}


class RoundStateMachine:
    def transition(self, status: RoundStatus, action: str) -> RoundStatus:
        nxt = TRANSITIONS.get((status, action))
        if nxt is None:
            raise IllegalState("round.illegal_transition", status=status, action=action)
        return nxt

    def allowed(self, status: RoundStatus) -> list[str]:
        return sorted(a for (s, a) in TRANSITIONS if s == status)
