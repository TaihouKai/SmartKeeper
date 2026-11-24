"""死亡时的脚本：self 是死者、target 是最后伤到它的角色、同伴用模板名。"""

from smartkeeper.contracts import GroupPreset, RulePack, UseResult
from smartkeeper.rules import RulesService
from tests.engine.harness import setup_table
from tests.engine.test_timeline import fields_of, publish, wait
from tests.fixtures import load_pack


def death_pack() -> RulePack:
    pack = load_pack("multi")
    leader, companion = pack.templates[0], pack.templates[1]
    fields = tuple(f.model_copy(update={"vital": f.name == "hp"}) for f in leader.fields)
    smite = GroupPreset(name="smite", fields={"rank": 1}, script="target.damage(1000)")
    g0 = leader.groups[0].model_copy(update={"presets": (smite,)})
    leader = leader.model_copy(
        update={
            "fields": fields,
            "groups": (g0, *leader.groups[1:]),
            # 领队死了：同伴只剩 1 点生命，杀死他的领队丢一个筹码
            "on_death": "companion.set(hp, 1)\ntarget.sub(tokens, 1)",
        }
    )
    return pack.model_copy(update={"templates": (leader, companion, *pack.templates[2:])})


def test_on_death_reaches_partner_and_killer() -> None:
    pack = death_pack()
    assert RulesService().validate_pack(pack) == []
    t = setup_table("multi", 2, pack=pack)
    e, g = t.engine, t.game_id
    p0, p1 = t.players
    lead0 = next(
        x
        for x in t.entities(p0)
        if x.startswith("ent_") and fields_of(t, x).get("tokens") is not None
    )
    lead1, comp1 = sorted(t.entities(p1), key=lambda x: fields_of(t, x).get("tokens") is None)
    tokens = fields_of(t, lead0)["tokens"]
    for p in t.players:
        wait(t, p, 10)
    e.close_round(g)
    e.begin_plan(g)
    hit = e.use_entry(g, lead0, "smite", lead1, {}, "x")
    publish(t, only=t.players, uses=[UseResult(seq=hit.seq)])
    assert fields_of(t, comp1)["hp"] == 1
    assert fields_of(t, lead0)["tokens"] == tokens - 1  # type: ignore[operator]


def test_unknown_receiver_is_reported() -> None:
    pack = death_pack()
    leader = pack.templates[0].model_copy(update={"on_death": "nobody.set(hp, 1)"})
    pack = pack.model_copy(update={"templates": (leader, *pack.templates[1:])})
    codes = [p.code for p in RulesService().validate_pack(pack)]
    assert codes == ["script.unknown_receiver"]


def test_damage_to_zero_kills_before_regeneration() -> None:
    """生命值打到 0 就死：不能先回复一点再判死亡。"""
    from tests.engine.test_timeline import magic_pack

    pack = magic_pack()
    tpl = pack.templates[0]
    fields = tuple(
        f.model_copy(update={"vital": True, "per_minute": "60"}) if f.name == "hp" else f
        for f in tpl.fields
    )
    pack = pack.model_copy(
        update={"templates": (tpl.model_copy(update={"fields": fields}), *pack.templates[1:])}
    )
    t = setup_table("single", 2, pack=pack)
    e, g = t.engine, t.game_id
    a, b = t.entities(t.players[0])[0], t.entities(t.players[1])[0]
    hp = fields_of(t, b)["hp"]
    for p in t.players:
        wait(t, p, 60)
    e.close_round(g)
    e.begin_plan(g)
    uses = [e.use_entry(g, a, "bolt", b, {}, "x") for _ in range(int(hp) // 5 + 1)]  # type: ignore[call-overload]
    publish(t, only=t.players, uses=[UseResult(seq=u.seq) for u in uses])
    statuses = e.world_state(g)["entities"][b]["sheet"]["statuses"]  # type: ignore[index]
    assert any(s["tag"] == "dead" for s in statuses)  # type: ignore[index,union-attr]
