"""KP：几种互相独立、各自只拿最小必要上下文的 LLM 调用，以及回合裁定管线。

LLM 不直接改状态：它的输出是 JSON，先在本地解析校验，再交给 engine 应用。
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, JsonValue

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
    OpeningOut,
    OutputError,
    PlanOut,
    ReviewOut,
    parse,
)

SEARCH_PURPOSES = {"review_character", "opening", "chat", "plan", "adjudicate"}
RETRY_NOTE = "上一次的输出有错误，整份作废：\n{errors}\n请修正后重新输出完整的结果，格式要求不变。"

type LeakChecker = Callable[[str, str, str], list[str]]


def no_leak_check(game_id: str, player_id: str, text: str) -> list[str]:
    """泄密检查的占位实现：直接通过。真正的检查在 M5。"""
    del game_id, player_id, text
    return []


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
        leak_check: LeakChecker = no_leak_check,
    ) -> None:
        self.engine = engine
        self.judge = judge
        self.writer = writer
        self.cfg = config
        self.ctx = Contexts(engine, config)
        self._log = call_log
        self._leak_check = leak_check
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
    ) -> R:
        """解析成 model 并交给 apply（通常是 engine 的写入）。解析或校验失败带着错误重试，最多 max_retries 次。"""
        messages: list[Message] = [{"role": "user", "content": prompt.user}]
        last: Exception | None = None
        for _ in range(self.cfg.max_retries + 1):
            res = self._call(purpose, game_id, prompt, messages, judge)
            try:
                out = parse(model, res.text)
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
            positions = {k: v for k, v in out.positions.items() if k in need}
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
                return
            if adj is None:
                return
            ok = self._write_outputs(game_id, adj)
            if ok and not self.engine.game(game_id).settings.review_mode:
                self.engine.publish_round(game_id)
        self.name_pending_handles(game_id)

    def _fail(self, game_id: str, err: Exception) -> None:
        detail: dict[str, JsonValue] = {"type": type(err).__name__, "message": str(err)[:2000]}
        with contextlib.suppress(IllegalState):  # 已经在待审核了
            self.engine.fail_round(game_id, detail)

    def _check_claims(self, game_id: str) -> None:
        rank = {"fails": 0, "partial": 1, "holds": 2}
        for pid, ev in self.engine.declarations(game_id).items():
            intent = Intent.model_validate(ev.payload["intent"])
            for claim in intent.claims:
                best = ClaimCheckOut(verdict="fails", evidence=[], note="")
                for prompt in self.ctx.claim(game_id, pid, claim.text):
                    try:
                        out = self._structured(
                            "claim_check", game_id, prompt, ClaimCheckOut, lambda o: o, judge=False
                        )
                    except (OutputError, ValidationFailed):
                        continue
                    if rank[out.verdict] > rank[best.verdict]:
                        best = out
                visible = {e.seq for e in self.engine.view_for(game_id, pid)}
                evidence = [s for s in best.evidence if s in visible]
                self.engine.record_claim_check(
                    game_id, pid, claim.text, best.verdict, evidence, best.note
                )

    def _run_plan(self, game_id: str) -> None:
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
            return self._structured(
                "adjudicate", game_id, self.ctx.adjudicate(game_id), Adjudication, apply, judge=True
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
        try:
            text = self._text("feedback", game_id, self.ctx.feedback(game_id, player_id, adj))
            if self._leak_check(game_id, player_id, text):
                # 泄密检查命中：自动重写一次，仍命中则该回合停在“待审核”
                text = self._text("feedback", game_id, self.ctx.feedback(game_id, player_id, adj))
                if self._leak_check(game_id, player_id, text):
                    return False
            self.engine.set_feedback_draft(game_id, player_id, text)
            return True
        except LLMError:
            return False

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
