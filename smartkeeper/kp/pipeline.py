"""KP：几种互相独立、各自只拿最小必要上下文的 LLM 调用，以及回合裁定管线。

LLM 不直接改状态：它的输出是 JSON，先在本地解析校验，再交给 engine 应用。
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import KP as KP_ACTOR
from smartkeeper.contracts import (
    ActionItem,
    Adjudication,
    ClaimRef,
    IllegalState,
    Intent,
    LLMCallLog,
    LLMClient,
    LLMError,
    LLMResult,
    Location,
    Message,
    NotFound,
    Opening,
    Round,
    SmartKeeperError,
    TargetRef,
    ValidationFailed,
)
from smartkeeper.engine import MAX_TEXT, Engine
from smartkeeper.kp.config import KPConfig
from smartkeeper.kp.context import Contexts, Prompt
from smartkeeper.kp.schemas import (
    ClaimCheckOut,
    HandleOut,
    IntentOut,
    LeakOut,
    NpcTalkOut,
    OpeningOut,
    OutputError,
    PlanOut,
    ReviewOut,
    parse,
    repair_adjudication,
)

SEARCH_PURPOSES = {"review_character", "opening", "chat", "plan", "adjudicate"}
RETRY_NOTE = "上一次的输出有错误，整份作废：\n{errors}\n请修正后重新输出完整的结果，格式要求不变。"

type RoundHook = Callable[[str, int], None]

# 反馈里出现实体 ID 或未替换的实体记号，一定是泄密（玩家永远不该看到实体 ID）
_RAW_ID = re.compile(r"\{\{[A-Za-z0-9_\-]+\}\}|\b(?:ent|npc)_[A-Za-z0-9_]+\b")


def _problems_text(err: SmartKeeperError) -> str:
    lines = [f"- {err.code} {err.params or ''}".rstrip()]
    lines += [f"- {p.code} at {p.path} {p.params or ''}".rstrip() for p in err.problems[:30]]
    return "\n".join(lines)


class KP:
    def __init__(
        self,
        engine: Engine,
        judge: LLMClient,
        writer: LLMClient,
        config: KPConfig,
        *,
        call_log: LLMCallLog | None = None,
        on_published: RoundHook | None = None,
        on_review: RoundHook | None = None,
    ) -> None:
        self.engine = engine
        self.judge = judge
        self.writer = writer
        self.cfg = config
        self.ctx = Contexts(engine, config)
        self._log = call_log
        self._on_published = on_published
        self._on_review = on_review
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ================= 调用的公共部分 =================

    def _lock(self, game_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(game_id, threading.Lock())

    def _client(self, judge: bool) -> tuple[LLMClient, str]:
        return (self.judge, self.cfg.judge_model) if judge else (self.writer, self.cfg.writer_model)

    def _allow_search(self, game_id: str, purpose: str, client: LLMClient) -> bool:
        return (
            purpose in SEARCH_PURPOSES
            and self.engine.game(game_id).settings.web_search
            and client.supports_search
        )

    def _call(
        self, purpose: str, game_id: str, prompt: Prompt, messages: list[Message], judge: bool
    ) -> LLMResult:
        client, model = self._client(judge)
        return client.complete(
            purpose=purpose,
            model=model,
            system=prompt.system,
            messages=messages,
            allow_search=self._allow_search(game_id, purpose, client),
            game_id=game_id,
        )

    def _mark(self, res: LLMResult, ok: bool) -> None:
        if self._log is not None and res.call_id is not None:
            self._log.mark(res.call_id, ok)

    def _text(self, purpose: str, game_id: str, prompt: Prompt, judge: bool = False) -> str:
        res = self._call(
            purpose, game_id, prompt, [{"role": "user", "content": prompt.user}], judge
        )
        text = res.text.strip()
        self._mark(res, bool(text))
        if not text:
            raise LLMError("llm.empty_reply", purpose)
        return text[:MAX_TEXT]

    def _structured[T: BaseModel, R](
        self,
        purpose: str,
        game_id: str,
        prompt: Prompt,
        model: type[T],
        apply: Callable[[T], R],
        judge: bool,
        repair: Callable[[object], object] | None = None,
    ) -> R:
        """解析成 model 并交给 apply（通常是 engine 的写入）。解析或校验失败带着错误重试，最多 max_retries 次。"""
        messages: list[Message] = [{"role": "user", "content": prompt.user}]
        last: Exception | None = None
        for _ in range(self.cfg.max_retries + 1):
            res = self._call(purpose, game_id, prompt, messages, judge)
            try:
                out = parse(model, res.text, repair)
                result = apply(out)
            except OutputError as e:
                errors = str(e)
                last = e
            except ValidationFailed as e:
                errors = _problems_text(e)
                last = e
            else:
                self._mark(res, True)
                return result
            self._mark(res, False)
            messages = [
                *messages,
                {"role": "assistant", "content": res.text or "（空）"},
                {"role": "user", "content": RETRY_NOTE.format(errors=errors)},
            ]
        assert last is not None
        raise last

    # ================= 建角与开场 =================

    def review_character(self, player_id: str) -> ReviewOut:
        """建角审核：通过，或给出修改意见。只看描述性内容，不评判强弱。"""
        game_id = self.engine.player(player_id).game_id

        def apply(out: ReviewOut) -> ReviewOut:
            if out.approved:
                self.engine.approve_character(player_id, out.comments)
            else:
                self.engine.reject_character(player_id, out.comments or "-")
            return out

        return self._structured(
            "review_character", game_id, self.ctx.review(player_id), ReviewOut, apply, judge=False
        )

    def open_game(self, game_id: str) -> Round:
        """开场：广播起始剧情、私发开场信息、给出剧本没有指定的初始位置，开启第 1 轮。"""
        prompt, need = self.ctx.opening(game_id)

        def apply(out: OpeningOut) -> Round:
            positions = {
                k: self.engine.resolve_place(game_id, v)
                for k, v in out.positions.items()
                if k in need
            }
            opening = Opening(broadcast=out.broadcast, messages=out.messages, positions=positions)
            return self.engine.start_game(game_id, opening)

        r = self._structured("opening", game_id, prompt, OpeningOut, apply, judge=True)
        self.name_pending_handles(game_id)
        return r

    # ================= 代号 =================

    def name_handle(self, game_id: str, player_id: str, entity_id: str) -> str:
        """外观代号：只依据对方的外观描述。"""

        def apply(out: HandleOut) -> str:
            return self.engine.set_handle_label(player_id, entity_id, out.label).label

        prompt = self.ctx.name_handle(game_id, player_id, entity_id)
        return self._structured("name_handle", game_id, prompt, HandleOut, apply, judge=False)

    def name_pending_handles(self, game_id: str) -> None:
        for player_id, entity_id in self.engine.unnamed_handles(game_id):
            try:
                self.name_handle(game_id, player_id, entity_id)
            except (LLMError, OutputError, ValidationFailed):
                continue  # 命名失败就保留临时代号 #n，下次再试

    # ================= 行动期 =================

    def answer_chat(self, player_id: str) -> str:
        """澄清对话：只读。它的输出只有一段回复文字，没有任何途径改变世界。"""
        game_id = self.engine.player(player_id).game_id
        reply = self._text("chat", game_id, self.ctx.chat(player_id))
        self.engine.post_kp_chat(player_id, reply, from_kp=True)
        return reply

    def parse_intent(self, player_id: str, text: str) -> Intent:
        """意图解析：不写入。玩家确认后才由调用方调用 engine.declare_action。"""
        game_id = self.engine.player(player_id).game_id
        prompt, refs = self.ctx.intent(player_id, text)
        own = set(self.engine.controlled(game_id, player_id))
        m = self.engine.map_data(game_id)

        def convert(out: IntentOut) -> Intent:
            unresolved = list(out.unresolved)
            items: list[ActionItem] = []
            for it in out.items:
                actor = refs.get(it.actor)
                if actor is None or actor not in own:
                    if len(own) == 1:
                        actor = next(iter(own))
                    else:
                        unresolved.append(it.actor)
                        continue
                targets: list[TargetRef] = []
                for t in it.targets:
                    if t.ref is not None:
                        if t.ref in refs:
                            targets.append(TargetRef(kind="entity", id=refs[t.ref]))
                        else:
                            unresolved.append(t.ref)
                    elif t.feature is not None:
                        if m.feature(t.feature) is not None:
                            targets.append(TargetRef(kind="feature", id=t.feature))
                        else:
                            unresolved.append(t.feature)
                    elif t.point is not None:
                        targets.append(TargetRef(kind="point", point=t.point))
                dest: Location | None = None
                if it.destination is not None:
                    d = it.destination
                    if d.point is not None:
                        dest = Location(pos=d.point)
                    elif d.feature is not None:
                        try:
                            dest = self.engine.feature_location(game_id, d.feature, d.z)
                        except (NotFound, ValidationFailed):
                            unresolved.append(d.feature)
                items.append(
                    ActionItem(
                        actor=actor,
                        verb=it.verb,
                        targets=tuple(targets),
                        destination=dest,
                        detail=it.detail,
                        # 用了技能：耗时至少是施放时间（引擎算）
                        act_seconds=max(
                            it.seconds,
                            self.engine.cast_seconds(game_id, actor, it.entry) if it.entry else 0,
                        ),
                        entry=it.entry,
                    )
                )
            claims = tuple(
                ClaimRef(
                    text=c.text,
                    entities=tuple(refs[r] for r in c.refs if r in refs),
                    features=tuple(f for f in c.features if m.feature(f) is not None),
                )
                for c in out.claims
            )
            return Intent(
                items=tuple(items), claims=claims, unresolved=tuple(dict.fromkeys(unresolved))
            )

        return self._structured("parse_intent", game_id, prompt, IntentOut, convert, judge=False)

    def npc_reply(
        self, game_id: str, talk_id: str, wait: Callable[[str], None] | None = None
    ) -> str:
        """对话模式里替 NPC 回一句；KP 也可以让 NPC 结束对话。wait 在写入前调用（模拟打字的延迟）。"""
        out = self._structured(
            "npc_talk",
            game_id,
            self.ctx.npc_talk(game_id, talk_id),
            NpcTalkOut,
            lambda o: o,
            judge=False,
        )
        if wait is not None:
            wait(out.text)
        with contextlib.suppress(IllegalState):  # 等待期间对方已经结束了对话
            self.engine.say(game_id, talk_id, KP_ACTOR, out.text)
            if out.end:
                self.engine.end_talk(game_id, talk_id, KP_ACTOR)
        return out.text

    def on_action(self, game_id: str) -> bool:
        """有人提交行动后调用：全员都已确认行动就自动结算。返回是否开始了结算。"""
        with self._lock(game_id):
            if not self.engine.ready_to_close(game_id):
                return False
            self.engine.close_round(game_id)
        self.run_round(game_id)
        return True

    def force_close(self, game_id: str) -> None:
        """管理员强制结算：未提交的玩家本轮视为没有行动。"""
        with self._lock(game_id):
            self.engine.close_round(game_id, forced=True)
        self.run_round(game_id)

    # ================= 回合裁定管线 =================

    def run_round(self, game_id: str) -> None:
        """声明核对 → 检定与查询规划 → 掷骰与空间查询 → 裁定 → 各反馈 → 泄密检查 → 发布。

        接口不依赖“一次调用处理全体玩家”：以后可以在这里按互不影响的区域分组多次裁定，
        engine 和裁定 JSON 的结构不变。
        """
        with self._lock(game_id):
            if self.engine.round(game_id).status != "adjudicating":
                return
            try:
                self._check_claims(game_id)
                self._run_plan(game_id)
                adj = self._adjudicate(game_id)
            except (LLMError, OutputError, SmartKeeperError) as e:
                self._fail(game_id, e)
                self._hook(self._on_review, game_id, self.engine.round(game_id).no)
                return
            if adj is None:
                self._hook(self._on_review, game_id, self.engine.round(game_id).no)
                return
            ok = self._write_outputs(game_id, adj)
            round_no = self.engine.round(game_id).no
            published = ok and not self.engine.game(game_id).settings.review_mode
            if published:
                self.engine.publish_round(game_id)
        if published:
            self.after_publish(game_id, round_no, adj)
        else:
            self._hook(self._on_review, game_id, round_no)
        self.name_pending_handles(game_id)

    def after_publish(self, game_id: str, round_no: int, adj: Adjudication | None = None) -> None:
        """发布之后：更新滚动摘要，通知（webhook）。失败都不影响游戏。"""
        if adj is not None and self.cfg.rolling_summary:
            with contextlib.suppress(LLMError, SmartKeeperError):
                text = self._text("summary", game_id, self.ctx.summary(game_id, adj))
                self.engine.record_summary(game_id, round_no, text)
        self._hook(self._on_published, game_id, round_no)

    @staticmethod
    def _hook(hook: RoundHook | None, game_id: str, round_no: int) -> None:
        if hook is not None:
            with contextlib.suppress(Exception):
                hook(game_id, round_no)

    def _fail(self, game_id: str, err: Exception) -> None:
        detail: dict[str, JsonValue] = {"type": type(err).__name__, "message": str(err)[:2000]}
        with contextlib.suppress(IllegalState):  # 已经在待审核了
            self.engine.fail_round(game_id, detail)

    def check_claim(self, game_id: str, player_id: str, claim: str) -> ClaimCheckOut:
        """核对一条对往事的引用。依据只有该玩家的完整视图（过长时分段，取最好的结果）。不写入。"""
        rank = {"fails": 0, "partial": 1, "holds": 2}
        best = ClaimCheckOut(verdict="fails", evidence=[], note="")
        for prompt in self.ctx.claim(game_id, player_id, claim):
            try:
                out = self._structured(
                    "claim_check", game_id, prompt, ClaimCheckOut, lambda o: o, judge=False
                )
            except (OutputError, ValidationFailed):
                continue
            if rank[out.verdict] > rank[best.verdict]:
                best = out
        visible = {e.seq for e in self.engine.view_for(game_id, player_id)}
        return best.model_copy(update={"evidence": [s for s in best.evidence if s in visible]})

    def _check_claims(self, game_id: str) -> None:
        for pid, ev in self.engine.declarations(game_id).items():
            intent = Intent.model_validate(ev.payload["intent"])
            for claim in intent.claims:
                out = self.check_claim(game_id, pid, claim.text)
                self.engine.record_claim_check(
                    game_id, pid, claim.text, out.verdict, out.evidence, out.note
                )

    def _run_plan(self, game_id: str) -> None:
        self.engine.begin_plan(game_id)  # 重跑时，之前那次的掷骰和查询作废
        plan = self._structured(
            "plan", game_id, self.ctx.plan(game_id), PlanOut, lambda o: o, judge=True
        )
        for c in plan.checks:
            try:
                if c.adhoc is not None:
                    self.engine.run_adhoc_check(game_id, c.entity, c.adhoc, c.reason)
                elif c.check is not None:
                    self.engine.run_check(game_id, c.entity, c.check, c.against, c.reason)
            except (ValidationFailed, NotFound):
                continue  # 声明不合法的检定不执行；裁定时看不到它的结果
        for roll in plan.rolls:
            try:
                self.engine.roll_formula(
                    game_id, roll.entity, roll.field, roll.entry, roll.reason, roll.params
                )
            except (ValidationFailed, NotFound):
                continue  # 不存在的条目或字段不掷；裁定时看不到它的结果
        for use in plan.uses:
            try:
                self.engine.use_entry(
                    game_id, use.source, use.entry, use.target, use.params, use.reason
                )
            except (ValidationFailed, NotFound):
                continue  # 用不了（没有这个技能、魔力不够等）：裁定时就看不到它
        for q in plan.queries:
            try:
                self.engine.spatial_query(game_id, q)
            except (ValidationFailed, NotFound):
                continue

    def _adjudicate(self, game_id: str) -> Adjudication | None:
        def apply(adj: Adjudication) -> Adjudication:
            self.engine.apply_adjudication(game_id, adj)
            return adj

        try:
            owner = {
                e: p.id
                for p in self.engine.players(game_id)
                for e in self.engine.controlled(game_id, p.id)
            }
            return self._structured(
                "adjudicate",
                game_id,
                self.ctx.adjudicate(game_id),
                Adjudication,
                apply,
                judge=True,
                repair=lambda raw: repair_adjudication(raw, owner),
            )
        except (OutputError, ValidationFailed) as e:
            self._fail(game_id, e)  # 重试用尽：回合停在“待审核”，等管理员处理
            return None

    def _write_outputs(self, game_id: str, adj: Adjudication) -> bool:
        """各玩家的反馈并行撰写，各自过泄密检查；有公共事件时写广播。全部成功返回 True。"""
        players = [o.player_id for o in adj.outcomes]
        with ThreadPoolExecutor(max_workers=max(1, self.cfg.writer_concurrency)) as pool:

            def one(pid: str) -> bool:
                return self._feedback_one(game_id, pid, adj)

            results = list(pool.map(one, players))
        ok = all(results)
        if adj.public_events:
            try:
                text = self._text("broadcast", game_id, self.ctx.broadcast(game_id, adj))
                self.engine.set_broadcast_draft(game_id, text)
            except LLMError:
                ok = False
        return ok

    def _feedback_one(self, game_id: str, player_id: str, adj: Adjudication) -> bool:
        """写一份反馈并过泄密检查。命中就自动重写一次；仍命中则把草稿和命中的句子留给审核，返回 False。"""
        try:
            leaks: list[str] = []
            text = ""
            for _attempt in range(2):
                text = self._text("feedback", game_id, self.ctx.feedback(game_id, player_id, adj))
                leaks = self.leak_check(game_id, player_id, adj, text)
                if not leaks:
                    break
            self.engine.set_feedback_draft(game_id, player_id, text)
            self.engine.set_feedback_leaks(game_id, player_id, leaks)
            return not leaks
        except (LLMError, SmartKeeperError):
            return False

    def leak_check(self, game_id: str, player_id: str, adj: Adjudication, text: str) -> list[str]:
        """泄密检查：先做确定性的检查（实体 ID、未替换的记号），再让模型对照不该知道的内容找句子。"""
        raw = _RAW_ID.findall(text)
        if raw:
            return [f"raw id: {x}" for x in raw]
        if not self.cfg.leak_check:
            return []
        try:
            out = self._structured(
                "leak_check",
                game_id,
                self.ctx.leak(game_id, player_id, adj, text),
                LeakOut,
                lambda o: o,
                judge=False,
            )
        except (OutputError, ValidationFailed):
            return ["leak check failed to produce a verdict"]
        return [f"{x.sentence} — {x.reason}" for x in out.leaks]

    def rewrite_feedback(self, game_id: str, player_id: str) -> None:
        draft = self.engine.draft(game_id)
        if draft is None or draft.get("adjudication") is None:
            raise IllegalState("round.no_adjudication")
        adj = Adjudication.model_validate(draft["adjudication"])
        if not self._feedback_one(game_id, player_id, adj):
            raise IllegalState("feedback.rewrite_failed")

    def rerun(self, game_id: str) -> None:
        """管理员整轮重跑。"""
        self.engine.rerun_round(game_id)
        self.run_round(game_id)

    def recover(self) -> list[str]:
        """进程启动时：停在“裁定中”的回合自动重跑一次。"""
        games = self.engine.recover()
        for g in games:
            self.run_round(g)
        return games
