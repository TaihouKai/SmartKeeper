"""各种调用的上下文构造。只经由 engine 的读取接口取得对局内容，没有绕过它直接查库的路径。

信息隔离靠“不把不该说的内容放进 prompt”来保证：每个构造函数只取这种调用需要的最小上下文。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from smartkeeper.contracts import (
    KP,
    Adjudication,
    Event,
    Intent,
    MemoryEntry,
)
from smartkeeper.engine import Engine, kp_meta, split_front_matter
from smartkeeper.kp import templates
from smartkeeper.kp.config import KPConfig
from smartkeeper.kp.render import dumps, player_text, render_events, replace_entity_tokens, section

UNKNOWN = {"zh": "某人", "en": "someone"}
STYLE = {
    "zh": "文风：简洁的第二人称小说体，三到八句。",
    "en": "Style: concise second-person prose, three to eight sentences.",
}
HISTORY_TYPES = (
    "broadcast",
    "pm_kp",
    "action_declared",
    "feedback",
    "round_opened",
    "round_closed",
)


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str


class Contexts:
    def __init__(self, engine: Engine, config: KPConfig) -> None:
        self.e = engine
        self.cfg = config

    # ---------------- 公共部分 ----------------

    def language(self, game_id: str) -> str:
        return self.e.game(game_id).settings.kp_language

    def names(self, game_id: str) -> dict[str, str]:
        out = {p.id: p.display_name for p in self.e.players(game_id)}
        out[KP] = "KP"
        return out

    def _reference_note(self, game_id: str) -> str:
        sites = self.e.rulepack(game_id).world.reference_sites
        if not sites:
            return ""
        lines = "\n".join(f"- {u}" for u in sites)
        return (
            "查世界观设定时，优先查下面这些参考网站；它们与别处的说法冲突时以它们为准；"
            f"查不到就去别处找。\n{lines}"
        )

    def _system(self, game_id: str, name: str) -> str:
        lang = templates.language_name(self.language(game_id))
        body = templates.render(name, language=lang)
        ref = self._reference_note(game_id)
        return f"{body}\n\n{ref}".strip()

    def _scenario(self, game_id: str, kp: bool) -> str:
        g = self.e.game(game_id)
        pub = g.scenario_public
        if not kp:
            return pub
        return f"{pub}\n\n---（以下是 KP 专属部分）---\n\n{g.scenario_kp}"

    # ---------------- 建角与开场 ----------------

    def review(self, player_id: str) -> Prompt:
        p = self.e.player(player_id)
        g = p.game_id
        identity = [e for e in self.e.view_for(g, player_id) if e.type == "identity_assigned"]
        subs = [s.model_dump(mode="json") for s in self.e.submitted_character(player_id)]
        user = "\n".join(
            [
                section("规则书", self.e.rulebook(g)),
                section("剧本（公开部分）", self._scenario(g, kp=False)),
                section(
                    "玩家的身份",
                    dumps([x.payload for x in identity]) if identity else "（剧本没有身份）",
                ),
                section("提交的角色卡", player_text(dumps(subs), p.display_name)),
            ]
        )
        return Prompt(self._system(g, "review_character"), user)

    def opening(self, game_id: str) -> tuple[Prompt, list[str]]:
        state = self.e.world_state(game_id)
        entities = state.get("entities")
        ents = entities if isinstance(entities, dict) else {}
        meta = kp_meta(self.e.game(game_id).scenario_kp)
        need = sorted(
            [eid for eid, ent in ents.items() if isinstance(ent, dict) and ent.get("pos") is None]
            + [n.id for n in meta.npcs if n.location is None]
        )
        players: list[dict[str, object]] = []
        for p in self.e.players(game_id):
            if not p.active:
                continue
            ident = [
                x.payload for x in self.e.view_for(game_id, p.id) if x.type == "identity_assigned"
            ]
            players.append(
                {
                    "player_id": p.id,
                    "display_name": p.display_name,
                    "entities": self.e.controlled(game_id, p.id),
                    "identity": ident,
                }
            )
        m = self.e.map_data(game_id)
        user = "\n".join(
            [
                section("规则书", self.e.rulebook(game_id)),
                section("剧本（全部）", self._scenario(game_id, kp=True)),
                section("玩家", dumps(players)),
                section("世界状态（含全部角色卡）", dumps(state)),
                section(
                    "地图",
                    dumps(
                        {
                            "id": m.id,
                            "bounds_m": m.bounds,
                            # 地名供 KP 选位置：有名字的地标和最高的 150 栋有名字的楼
                            "landmarks": sorted(
                                {f.name for f in m.features if f.kind == "landmark" and f.name}
                            )[:150],
                            "named_buildings": [
                                {"name": f.name, "height": f.height}
                                for f in sorted(
                                    (x for x in m.features if x.kind == "building" and x.name),
                                    key=lambda x: -x.height,
                                )[:150]
                            ],
                        }
                    ),
                ),
                section("需要初始位置的实体", dumps(need)),
            ]
        )
        return Prompt(self._system(game_id, "opening"), user), need

    def name_handle(self, game_id: str, player_id: str, entity_id: str) -> Prompt:
        appearance, labels = self.e.handle_context(game_id, player_id, entity_id)
        lang = templates.language_name(self.language(game_id))
        user = "\n".join(
            [
                section("对方的外观描述", player_text(appearance or "（没有描述）", "sheet")),
                section("该玩家已有的代号", dumps(labels)),
            ]
        )
        return Prompt(templates.render("name_handle", language=lang), user)

    # ---------------- 行动期 ----------------

    def chat(self, player_id: str) -> Prompt:
        p = self.e.player(player_id)
        g = p.game_id
        view = self.e.view_for(g, player_id)
        sheets = [s.model_dump(mode="json") for s in self.e.sheets(g, player_id)]
        user = "\n".join(
            [
                section("规则书", self.e.rulebook(g)),
                section(
                    "该玩家能看到的历史（最近的在后）",
                    render_events(view, self.names(g), self.cfg.history_events),
                ),
                section("该玩家的角色卡", dumps(sheets)),
                section(
                    "该玩家各实体此刻感知范围内的状态", dumps(self.e.state_slice(g, player_id))
                ),
                "请回答上面历史里该玩家在聊天框里最后提出的问题。",
            ]
        )
        return Prompt(self._system(g, "chat"), user)

    def intent(self, player_id: str, text: str) -> tuple[Prompt, dict[str, str]]:
        """返回 prompt 和 ref -> 实体 id 的对照（只在本地用，不进 prompt）。"""
        p = self.e.player(player_id)
        g = p.game_id
        resolved, _targets = self.e.resolve_mentions(g, player_id, text)
        scene = self.e.scene(g, player_id)
        refs: dict[str, str] = {}
        own: list[JsonValue] = []
        for ent in scene.entities:
            refs[ent.ref] = self.e.entity_for_ref(player_id, ent.ref)
            own.append(
                {
                    "ref": ent.ref,
                    "name": ent.name,
                    "mine": True,
                    "present": [
                        {"ref": x.ref, "label": x.label, "note": x.note} for x in ent.presence
                    ],
                }
            )
        seen: list[JsonValue] = []
        for s in scene.seen:
            refs[s.ref] = self.e.entity_for_ref(player_id, s.ref)
            seen.append({"ref": s.ref, "label": s.label, "note": s.note})
        user = "\n".join(
            [
                section("可指代的对象：玩家自己控制的实体（及各自的在场列表）", dumps(own)),
                section("可指代的对象：玩家见过的人和物（不一定在场）", dumps(seen)),
                section("附近的地物", dumps(self.e.nearby_features(g, player_id))),
                section("行动声明", player_text(resolved, p.display_name)),
            ]
        )
        return Prompt(templates.render("parse_intent"), user), refs

    # ---------------- 回合 ----------------

    def claim(self, game_id: str, player_id: str, claim: str) -> list[Prompt]:
        """一条往事引用的核对；视图过长时分段，每段一次调用。"""
        view = self.e.view_for(game_id, player_id)
        names = self.names(game_id)
        chunk = self.cfg.claim_chunk_events
        parts = [view[i : i + chunk] for i in range(0, len(view), chunk)] or [[]]
        who = names.get(player_id, player_id)
        return [
            Prompt(
                templates.render("claim_check"),
                "\n".join(
                    [
                        section(
                            "该玩家的完整视图"
                            + (f"（第 {i + 1}/{len(parts)} 段）" if len(parts) > 1 else ""),
                            render_events(part, names),
                        ),
                        section("要核对的引用", player_text(claim, who)),
                    ]
                ),
            )
            for i, part in enumerate(parts)
        ]

    def _round_body(self, game_id: str, include_results: bool) -> str:
        e = self.e
        r = e.round(game_id)
        names = self.names(game_id)
        kp_view = e.view_for(game_id, KP)
        this_round = [x for x in kp_view if x.round_no == r.no]
        state = e.world_state(game_id)
        now, end = e.round_window(game_id)
        acts = e.activities(game_id)
        # 条目 id -> (声明原文, 条目)：进行中的行动可能是前几轮确认的
        declared: dict[str, tuple[str, JsonValue]] = {}
        for x in kp_view:
            if x.type != "action_declared":
                continue
            for it in Intent.model_validate(x.payload["intent"]).items:
                if it.id is not None:
                    declared[it.id] = (str(x.payload.get("text", "")), it.model_dump(mode="json"))

        # 本轮行动
        acting: list[str] = []
        actors: set[str] = set()
        targets: set[str] = set()
        features: set[str] = set()
        quotes: set[int] = set()
        for p in e.players(game_id):
            pid = p.id
            ents = e.controlled(game_id, pid)
            if not p.active or not ents:
                continue
            who = names.get(pid, pid)
            lines = [f"### 玩家 {pid}（{who}），控制实体 {ents}"]
            texts: set[str] = set()
            for eid in ents:
                act = acts.get(eid)
                if act is None:
                    lines.append(f"- 实体 {eid}：没有进行中的行动（强制结算时没提交）。")
                    continue
                actors.add(eid)
                left = act.end - end
                status = "本轮内做完" if left <= 0 else f"本轮结束时还没做完，还剩 {left} 秒"
                lines.append(
                    f"- 实体 {eid}：进行中的行动，第 {act.start} 秒开始，第 {act.end} 秒结束（{status}）"
                )
                for st in act.steps:
                    text, item = declared.get(st.item, ("", None))
                    texts.add(text)
                    targets.update(st.targets)
                    if st.to is not None and st.to.inside:
                        features.add(st.to.inside)
                    lines.append(
                        f"  - 行动条目 {st.item}（移动 {st.move} 秒 + 动作 {st.act} 秒）: "
                        + player_text(dumps(item), who)
                    )
            for text in sorted(x for x in texts if x):
                lines.append("原文：" + player_text(text, who))
            acting.append("\n".join(lines))
        for ev in e.declarations(game_id).values():
            intent = Intent.model_validate(ev.payload["intent"])
            for c in intent.claims:
                targets.update(c.entities)
                features.update(c.features)
            quotes.update(intent.quotes)

        # 历史：最近几轮原文 + 按实体检索的记事条目 + 玩家引用的原文
        recent_from = max(0, r.no - self.cfg.recent_rounds)
        recent = [
            x for x in kp_view if recent_from <= x.round_no < r.no and x.type in HISTORY_TYPES
        ]
        memory = e.recall(game_id, sorted(actors | targets), sorted(features), sorted(actors))
        memory_text = self._memory_text(memory, kp_view, names)
        quoted = [x for x in kp_view if x.seq in quotes]

        chat = [x for x in this_round if x.type == "pm_kp"]
        talk = [x for x in this_round if x.type.startswith("talk_")]
        ends_at = {
            eid: loc.model_dump(mode="json") for eid, loc in e.positions_at_end(game_id).items()
        }
        claims = [x.payload for x in this_round if x.type == "claim_check"]
        parts = [
            section("规则书", e.rulebook(game_id)),
            section("剧本（全部）", self._scenario(game_id, kp=True)),
            section("世界状态", dumps(state)),
            section("各实体的推导值", dumps(e.derived_all(game_id))),
            section(
                "各实体此刻生效的固定条目（规则包写好的，不在世界状态里）",
                dumps(e.active_presets_all(game_id)),
            ),
            section(
                "地图上的设置物（陷阱、结界等）与本轮按行动推算会被触发的",
                dumps(e.placement_report(game_id)),
            ),
            section("滚动摘要（只提供氛围，不能作为事实依据）", e.latest_summary(game_id)),
            section(f"最近 {self.cfg.recent_rounds} 轮的事件原文", render_events(recent, names)),
            section("按实体检索到的往事（记事条目与原始裁定）", memory_text),
            section("玩家用引用按钮引用的原文", render_events(quoted, names)),
            section(
                "本轮的时间段",
                f"从游戏内第 {now} 秒到第 {end} 秒，共 {end - now} 秒。结束时刻由引擎取最早做完的行动，"
                "你只裁定这段时间里发生的事。",
            ),
            section("进行中的行动（按玩家）", "\n\n".join(acting)),
            section(
                "本轮结束时各实体按行动走到的位置（你没有另行安排移动时就在这里）", dumps(ends_at)
            ),
            section("必须有结果的玩家（行动做完了或没有行动）", dumps(e.outcome_required(game_id))),
            section("本轮的对话（对话模式，双方原话）", render_events(talk, names)),
            section(
                "旁听到对话的实体（对话 id -> 实体 id；他们听到了全部内容，要在他们的结果里转述）",
                dumps(e.overhearers(game_id)),
            ),
            section("声明核对结果", dumps(claims)),
            section("聊天问答（背景，不是行动）", render_events(chat, names)),
        ]
        if include_results:
            attempt = e.current_attempt(game_id, r.no)
            rolls = [x.payload for x in attempt if x.type == "dice_roll"]
            queries = [x.payload for x in attempt if x.type == "spatial_query"]
            parts.append(section("检定结果（引擎掷骰）", dumps(rolls)))
            parts.append(
                section(
                    "本轮声明的技能使用（引擎已算好数值；在 uses 里按 seq 写生效与否）",
                    dumps(e.planned_uses(game_id)),
                )
            )
            parts.append(section("空间查询结果", dumps(queries)))
        return "\n".join(parts)

    def _memory_text(
        self, memory: Sequence[MemoryEntry], kp_view: Sequence[Event], names: dict[str, str]
    ) -> str:
        if not memory:
            return "（无）"
        by_seq = {x.seq: x for x in kp_view}
        budget = self.cfg.memory_budget_chars
        lines: list[str] = []
        expanded: set[int] = set()
        for m in memory:
            lines.append(
                f"- R{m.round_no} [{', '.join(m.entities)}] [{', '.join(m.features)}] {m.text} (来源 #{m.source_seq})"
            )
        used = sum(len(x) for x in lines)
        for m in reversed(memory):
            src = by_seq.get(m.source_seq)
            if src is None or m.source_seq in expanded:
                continue
            text = render_events([src], names)
            if used + len(text) > budget:
                break
            lines.append(text)
            expanded.add(m.source_seq)
            used += len(text)
        return "\n".join(lines)

    def plan(self, game_id: str) -> Prompt:
        return Prompt(
            self._system(game_id, "plan"), self._round_body(game_id, include_results=False)
        )

    def adjudicate(self, game_id: str) -> Prompt:
        return Prompt(
            self._system(game_id, "adjudicate"), self._round_body(game_id, include_results=True)
        )

    # ---------------- 分发 ----------------

    def _labels(self, game_id: str, player_id: str) -> dict[str, str]:
        out = {h.entity_id: f"@{h.label}" for h in self.e.handles(player_id)}
        for ent in self.e.scene(game_id, player_id).entities:
            out[self.e.entity_for_ref(player_id, ent.ref)] = ent.name
        return out

    def feedback(self, game_id: str, player_id: str, adj: Adjudication) -> Prompt:
        """只有：p 的 outcome、涉及 p 的 encounters 里 observed_by[p]、public_events、推进时间、p 的历史视图。"""
        lang = self.language(game_id)
        labels = self._labels(game_id, player_id)
        unknown = UNKNOWN.get(lang, UNKNOWN["en"])

        def loc(t: str) -> str:
            return replace_entity_tokens(t, labels, unknown)

        outcome = next((o for o in adj.outcomes if o.player_id == player_id), None)
        mine = {
            "result": loc(outcome.result) if outcome else "",
            "observations": [loc(x) for x in outcome.observations] if outcome else [],
        }
        seen = [
            loc(enc.observed_by[player_id])
            for enc in adj.encounters
            if player_id in enc.observed_by
        ]
        public = [replace_entity_tokens(x, {}, unknown) for x in adj.public_events]
        view = self.e.view_for(game_id, player_id)
        user = "\n".join(
            [
                section(
                    "该玩家能看到的历史（最近的在后）",
                    render_events(view, self.names(game_id), self.cfg.history_events),
                ),
                section(
                    "距离该玩家上次收到消息过去的游戏内时间（秒）",
                    str(
                        self.e.round_window(game_id)[1] - self.e.player_seconds(game_id, player_id)
                    ),
                ),
                section("该玩家本轮的结果", dumps(mine)),
                section("该玩家看到的别人的行为", dumps(seen)),
                section("公共事件", dumps(public)),
            ]
        )
        system = templates.render(
            "feedback", language=templates.language_name(lang), style=STYLE.get(lang, STYLE["en"])
        )
        return Prompt(system, user)

    def broadcast(self, game_id: str, adj: Adjudication) -> Prompt:
        lang = self.language(game_id)
        unknown = UNKNOWN.get(lang, UNKNOWN["en"])
        public_history = self.e.view_for(game_id, "public")
        user = "\n".join(
            [
                section(
                    "公开历史",
                    render_events(public_history, self.names(game_id), self.cfg.history_events),
                ),
                section(
                    "本轮公共事件",
                    dumps([replace_entity_tokens(x, {}, unknown) for x in adj.public_events]),
                ),
            ]
        )
        return Prompt(templates.render("broadcast", language=templates.language_name(lang)), user)

    def scenario_body(self, game_id: str) -> str:
        return split_front_matter(self.e.game(game_id).scenario_public)[1]

    # ---------------- 加固 ----------------

    def leak(self, game_id: str, player_id: str, adj: Adjudication, text: str) -> Prompt:
        """泄密检查：这份反馈、允许的内容、不该让他知道的内容（别人的部分和剧本的 KP 专属部分）。"""
        allowed = self.feedback(game_id, player_id, adj).user
        others = {
            "outcomes": [
                o.model_dump(mode="json") for o in adj.outcomes if o.player_id != player_id
            ],
            "encounters": [
                {k: v for k, v in enc.observed_by.items() if k != player_id}
                for enc in adj.encounters
            ],
        }
        g = self.e.game(game_id)
        user = "\n".join(
            [
                section("要检查的反馈", text),
                section("允许的内容", allowed),
                section("不该让他知道的内容：本轮裁定里别人的部分", dumps(others)),
                section("不该让他知道的内容：剧本的 KP 专属部分", g.scenario_kp),
            ]
        )
        return Prompt(templates.render("leak_check"), user)

    def npc_talk(self, game_id: str, talk_id: str) -> Prompt:
        """对话模式里扮演 NPC：剧本、这个 NPC 的角色卡和位置、对方的外观、对话原文。"""
        t = self.e.talk(game_id, talk_id)
        state = self.e.world_state(game_id)
        ents = state.get("entities")
        npc = ents.get(t.b_entity) if isinstance(ents, dict) else None
        names = self.names(game_id)
        appearance = self.e.appearance_of(game_id, t.a_entity)
        lines = [
            f"{'NPC' if m.speaker == t.b_entity else '对方'}: "
            + (
                m.text
                if m.speaker == t.b_entity
                else player_text(m.text, names.get(t.a_player, "?"))
            )
            for m in t.messages
        ]
        user = "\n".join(
            [
                section("剧本（全部）", self._scenario(game_id, kp=True)),
                section("KP 长期备忘", str(state.get("kp_notes", ""))),
                section(f"你扮演的 NPC（实体 {t.b_entity}）", dumps(npc)),
                section(
                    "对方的外观（NPC 只知道这些）",
                    player_text(appearance or "（没有描述）", "sheet"),
                ),
                section("对话原文（最近的在后）", "\n".join(lines) or "（对方刚发起对话）"),
            ]
        )
        return Prompt(self._system(game_id, "npc_talk"), user)

    def summary(self, game_id: str, adj: Adjudication) -> Prompt:
        lang = templates.language_name(self.language(game_id))
        user = "\n".join(
            [
                section("上一版摘要", self.e.latest_summary(game_id)),
                section("本轮裁定", dumps(adj.model_dump(mode="json"))),
            ]
        )
        return Prompt(templates.render("summary", language=lang), user)
