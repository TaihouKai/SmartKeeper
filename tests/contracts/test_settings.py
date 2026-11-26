"""局的设置：已经删掉的“审核模式”，旧的局里存着也能照常读。"""

from __future__ import annotations

from smartkeeper.contracts import GameSettings


def test_removed_review_mode_in_old_games_is_ignored() -> None:
    s = GameSettings.model_validate({"review_mode": True, "web_search": False})
    assert s.web_search is False
    assert "review_mode" not in s.model_dump()
