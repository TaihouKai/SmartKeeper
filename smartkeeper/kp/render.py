"""把事件和玩家文本渲染成 prompt 里的文字。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from smartkeeper.contracts import KP, Event

_TOKEN = re.compile(r"\{\{([A-Za-z0-9_\-]{1,64})\}\}")


_TAG_LIKE = re.compile(r"<(\s*/?\s*player_text)", re.IGNORECASE)


def player_text(text: str, who: str) -> str:
    """玩家写的文字一律包进标签。只把像这个标签的写法（<player_text、</player_text）的尖括号换成全角，
    标签里的内容就无法闭合或伪造标签；别的 < > & 原样保留（卡上的公式 time < 13:00 要让 KP 看到原样）。"""
    safe = _TAG_LIKE.sub(lambda m: "＜" + m.group(1), text)
    return f'<player_text from="{who}">{safe}</player_text>'


def replace_entity_tokens(text: str, labels: Mapping[str, str], unknown: str) -> str:
    """把裁定里的 {{实体ID}} 换成读者自己的称呼；读者不认识的实体换成 unknown。"""
    return _TOKEN.sub(lambda m: labels.get(m.group(1), unknown), text)


def entity_tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text))


def _compact(v: JsonValue) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def render_event(e: Event, names: Mapping[str, str]) -> str:
    """一条事件一行（或几行）。names：玩家 id -> 显示名。"""
    p = e.payload
    head = f"[#{e.seq} R{e.round_no}]"
    actor = e.actor
    who = names.get(actor, actor) if actor else "?"
    text = str(p.get("text", ""))
    t = e.type
    if t == "broadcast":
        if actor == KP:
            return f"{head} 广播 KP: {text}"
        speaker = "匿名" if actor is None else who
        return f"{head} 广播 {speaker}: {player_text(text, speaker)}"
    if t == "pm_kp":
        if actor == KP:
            kind = "开场信息" if p.get("kind") == "opening" else "KP 回复"
            return f"{head} {kind}: {text}"
        return f"{head} 聊天（{who} 问 KP）: {player_text(text, who)}"
    if t == "action_declared":
        intent = p.get("intent")
        return f"{head} 行动声明（{who}）: {player_text(text, who)} 结构化: {_compact(intent)}"
    if t == "feedback":
        return f"{head} KP 反馈: {text}"
    if t == "round_opened":
        return f"{head} 第 {p.get('round')} 轮开始，游戏内第 {p.get('game_seconds')} 秒"
    if t == "round_closed":
        return f"{head} 第 {p.get('round')} 轮结束，游戏内第 {p.get('game_seconds')} 秒"
    if t == "talk_message":
        return f"{head} 对话 {p.get('talk')}（{p.get('from')} 说）: {player_text(text, str(p.get('from')))}"
    if t.startswith("talk_"):
        return f"{head} 对话 {p.get('talk')}: {t[5:]} {_compact(p)}"
    if t == "identity_assigned":
        return f"{head} 身份: {p.get('name')} — {p.get('description')}"
    if t == "character_submitted":
        return f"{head} 提交了角色卡"
    if t in ("character_approved", "character_rejected"):
        return f"{head} 角色卡审核: {t} {p.get('comments', '')}"
    # 以下是 kp_only 的事件，只会出现在 KP 的上下文里
    return f"{head} {t}: {_compact(p)}"


def render_events(
    events: Sequence[Event], names: Mapping[str, str], limit: int | None = None
) -> str:
    chosen = list(events)[-limit:] if limit else list(events)
    return "\n".join(render_event(e, names) for e in chosen) or "（无）"


def section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip() or '（无）'}\n"


def dumps(v: object) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1, default=str)
