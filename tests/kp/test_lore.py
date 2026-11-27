"""资料库：按关键词挑条目（常见词、次关键词、正则、整词、预算），以及它在各种调用的上下文里放在哪、按什么挑。"""

from __future__ import annotations

import json

from smartkeeper.contracts import LoreEntry
from smartkeeper.kp import lore
from smartkeeper.rules import RulesService, from_world_info
from tests.kp.harness import new_game


def entry(title: str, *keys: str, content: str = "", **kw: object) -> LoreEntry:
    return LoreEntry.model_validate(
        {"title": title, "keys": keys, "content": content or f"{title}的说明。", **kw}
    )


def titles(hits: list[lore.LoreHit]) -> list[str]:
    return [h.entry.title for h in hits]


def test_keys_secondary_logic_regex_and_whole_words() -> None:
    book = [
        entry("教会", "圣堂教会", "代行者"),
        entry("宝石", "宝石魔术", secondary=["远坂"], logic="all"),
        entry("黑键", "/黑键|Black ?Keys?/i"),
        entry("BB", "BB"),
        entry("关着的", "代行者", disabled=True),
    ]
    text = ["一名代行者从教会走出来，手里握着black key。远处有人在吃BBQ。"]
    assert titles(lore.pick(book, text, 5000)) == ["教会", "黑键"]  # BB 按整词，不命中 BBQ
    assert titles(lore.pick(book, ["他会宝石魔术"], 5000)) == []  # 次关键词要全部出现
    assert titles(lore.pick(book, ["远坂家的宝石魔术"], 5000)) == ["宝石"]
    assert titles(lore.pick(book, ["代行者"], 5000, exclude=["教会"])) == []


def test_common_words_need_a_second_key_and_the_budget_holds() -> None:
    # “魔术”出现在很多条目的正文里：单独出现不触发
    book = [
        entry(f"条目{i}", f"专名{i}", "魔术", content=f"关于魔术的第 {i} 条。" * 3)
        for i in range(30)
    ]
    assert lore.pick(book, ["这里有魔术的气息"], 10_000) == []
    assert titles(lore.pick(book, ["专名3 用了魔术"], 10_000)) == ["条目3"]
    hits = lore.pick(book, [" ".join(f"专名{i}" for i in range(30))], 200)
    assert 0 < len(hits) < 30
    assert sum(len(h.entry.content) for h in hits) <= 200


def test_world_info_import_keeps_what_we_use() -> None:
    data = {
        "name": "书",
        "entries": {
            "0": {
                "comment": "A",
                "key": ["甲", " "],
                "keysecondary": ["乙"],
                "selectiveLogic": 3,
                "content": "正文",
                "order": 5,
                "disable": False,
                "constant": True,
            },
            "1": {"comment": "空的", "key": ["丙"], "content": ""},
        },
    }
    (e,) = from_world_info(json.loads(json.dumps(data)))
    assert (e.title, e.keys, e.secondary, e.logic, e.order) == ("A", ("甲",), ("乙",), "all", 5)
    from tests.engine.harness import load_pack

    pack = load_pack("single").model_copy(update={"lore": (e, e)})
    assert [p.code for p in RulesService().validate_pack(pack)] == ["lore.duplicate_title"]


def test_lore_goes_into_the_judge_prefix_and_chat_never_sees_secret_driven_lore() -> None:
    pack_lore = (
        entry("秘密组织", "暗夜结社", content="暗夜结社是一个古老的秘密组织。"),
        entry("公开设定", "广场", content="广场是公开的地方。"),
    )
    from tests.engine.harness import load_pack

    pack = load_pack("single").model_copy(update={"lore": pack_lore})
    g = new_game(2, pack=pack, scenario_kp_extra="\n幕后黑手属于暗夜结社。\n")
    ctx = g.kp.ctx
    plan, adj = ctx.plan(g.game_id), ctx.adjudicate(g.game_id)
    # 裁定类调用：system 一样，正文开头（规则书、剧本、按剧本挑的资料、固定条目、世界状态……）逐字一样，任务说明在最后
    assert plan.system == adj.system
    shared = len(ctx._round_body(g.game_id, include_results=False))  # pyright: ignore[reportPrivateUsage]
    assert plan.user[:shared] == adj.user[:shared]
    assert (
        plan.user.index("## 规则书")
        < plan.user.index("暗夜结社是一个古老")
        < plan.user.index("## 世界状态")
    )
    assert plan.user.rindex("## 这次的任务") > plan.user.index("## 世界状态")
    # 聊天的回答给玩家看：不按 KP 专属的剧本挑资料
    assert "暗夜结社是一个古老" not in ctx.chat(g.players[0]).user


def test_engine_code_is_not_given_to_the_kp_but_comment_notes_are() -> None:
    from smartkeeper.kp.render import kp_entry

    raw = {
        "name": "城墙",
        "id": "",
        "description": "挡在同伴前面。",
        "config": 'target = "self"\naura = sphere(radius=100)  # 范围',
        "script": "",
        "bonus": "# 敌人只能攻击她本人",
        "effects": [],
        "uses": [
            {"name": "展开", "config": "release = 1", "description": "解放真名", "params": []}
        ],
    }
    assert kp_entry(raw) == {
        "name": "城墙",
        "description": "挡在同伴前面。",
        "uses": [{"name": "展开", "description": "解放真名"}],
        "notes": ["敌人只能攻击她本人"],
    }
