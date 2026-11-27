"""裁定文字里用名字或外貌提到了实体却没写记号：按字面认出来。"""

from smartkeeper.engine.untokened import Looks, untokened

PRIEST = Looks(("神父·朝仓",), "穿黑色神父服的中年人，笑容温和，手里总拿着一本旧圣经")
KNIGHT = Looks(("Arthur Pendragon",), "a tall knight in silver armour with a blue cape")


def test_appearance_paraphrase_is_recognised() -> None:
    # 实际发生过的：KP 只写了外貌，没写 {{npc_father}}
    text = "{{ent_2}}注意到{{place:宫下公园}}附近有一名穿黑色神父服、手持旧圣经的中年人。"
    assert [e for e, _ in untokened(text, {"npc_father": PRIEST})] == ["npc_father"]
    # 名字里没有能对上的字，也能按外貌认出来
    anon = Looks(("朝仓",), PRIEST.appearance)
    assert untokened(text, {"npc_father": anon}) == [("npc_father", PRIEST.appearance)]


def test_name_or_part_of_it_is_recognised() -> None:
    assert untokened("朝仓向你点头。", {"npc_father": PRIEST}) == [("npc_father", "朝仓")]
    assert untokened("You meet arthur at the gate.", {"k": KNIGHT}) == [("k", "Arthur")]
    # 英文名按整词找
    assert untokened("Arthurian legends", {"k": KNIGHT}) == []


def test_tokens_and_unrelated_text_pass() -> None:
    looks = {"npc_father": PRIEST, "k": KNIGHT}
    assert untokened("{{npc_father}}（穿黑色神父服的中年人）向你点头。", looks) == []
    assert untokened("夜色笼罩着涩谷，街上的中年人行色匆匆。", looks) == []
    assert untokened("A tall man in a grey coat walks past.", looks) == []
