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


# 引擎写进消息里的地点链接 [名字](place:id) / [名字](feature:id)：给 KP 看时换回它自己用的写法 {{place:名字}}
_PLACE_LINK = re.compile(r"\[([^\]\n]{1,80})\]\((?:place|feature):[A-Za-z0-9_.-]{1,80}\)")


# 引擎写进给玩家的消息里的 @[代号](ref)：给 KP 看时只留 @代号
_PERSON_LINK = re.compile(r"@\[([^\]\n]{1,80})\]\([A-Za-z0-9_\-]{1,80}\)")


def place_tokens(text: str) -> str:
    """消息里的链接换回 KP 自己的写法：地点 {{place:名字}}，提到的人 @代号。"""
    text = _PERSON_LINK.sub(lambda m: "@" + m.group(1), text)
    return _PLACE_LINK.sub(lambda m: "{{place:" + m.group(1) + "}}", text)


def render_event(e: Event, names: Mapping[str, str]) -> str:
    """一条事件一行（或几行）。names：玩家 id -> 显示名。"""
    p = e.payload
    head = f"[#{e.seq} R{e.round_no}]"
    actor = e.actor
    who = names.get(actor, actor) if actor else "?"
    text = place_tokens(str(p.get("text", "")))
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
        # 给玩家的反馈带着氛围修饰；KP 的上下文里只放它依据的事实（修饰写错了也不会被当真）
        facts = p.get("facts")
        if isinstance(facts, str):
            return f"{head} KP 反馈（事实）: {place_tokens(facts)}"
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
    """给模型看的 JSON：紧凑格式（缩进只是给人看的，模型不需要，还要按 token 付钱）。"""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


# 条目里引擎自己执行的代码：KP 不需要读（射程、对象、冷却、效果都由引擎检查和执行），只留整行的注释，
# 因为只写 `# 说明` 的效果就是写给 KP 读的
_CODE_KEYS = ("config", "script", "bonus")


def _comments(code: str) -> list[str]:
    return [ln.strip()[1:].strip() for ln in code.splitlines() if ln.strip().startswith("#")]


def kp_entry(entry: JsonValue) -> JsonValue:
    """条目（技能、魔术和它的用法、参数）给 KP 看的样子：去掉代码、id 和空字段，代码里整行的注释留作 notes。"""
    if isinstance(entry, list):
        return [kp_entry(x) for x in entry]
    if not isinstance(entry, dict):
        return entry
    out: dict[str, JsonValue] = {}
    notes: list[JsonValue] = []
    for k, v in entry.items():
        if k in _CODE_KEYS:
            if isinstance(v, str):
                notes += _comments(v)
            continue
        if k == "id" or v in ("", [], {}, None):
            continue
        out[k] = kp_entry(v) if k in ("uses", "params") else v
    if notes:
        out["notes"] = notes
    return out


def kp_groups(groups: JsonValue) -> JsonValue:
    """分组名 -> 条目列表：每个条目换成给 KP 看的样子。"""
    if not isinstance(groups, dict):
        return groups
    return {g: kp_entry(v) for g, v in groups.items()}


def kp_world_state(state: JsonValue) -> JsonValue:
    """世界状态给 KP 看的样子：各实体角色卡上的条目去掉代码（其余原样，KP 写 state_patch 的路径不变）。"""
    if not isinstance(state, dict):
        return state
    ents = state.get("entities")
    if not isinstance(ents, dict):
        return state
    slim: dict[str, JsonValue] = {eid: _slim_sheet_of(ent) for eid, ent in ents.items()}
    return {**state, "entities": slim}


def _slim_sheet_of(holder: JsonValue) -> JsonValue:
    """带 sheet 的东西（世界状态里的实体、SheetView）：sheet 里的条目换成给 KP 看的样子。"""
    if not isinstance(holder, dict):
        return holder
    sheet = holder.get("sheet")
    if not isinstance(sheet, dict):
        return holder
    slim_sheet: dict[str, JsonValue] = {**sheet, "groups": kp_groups(sheet.get("groups"))}
    out: dict[str, JsonValue] = {**holder, "sheet": slim_sheet}
    return out


def kp_presets(presets: JsonValue) -> JsonValue:
    """实体 id -> 分组名 -> 条目（各实体此刻生效的固定条目）给 KP 看的样子。"""
    if not isinstance(presets, dict):
        return presets
    return {eid: kp_groups(groups) for eid, groups in presets.items()}


_NOT_TEXT = {*_CODE_KEYS, "id", "template", "entity_id", "ref"}


def texts_of(value: JsonValue) -> list[str]:
    """一份数据里的文字（只取值，不取字段名、id 和代码）：挑资料用。英文字段名会误命中资料库的英文关键词。"""
    out: list[str] = []

    def walk(v: JsonValue) -> None:
        if isinstance(v, str):
            if v.strip():
                out.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in _NOT_TEXT:
                    walk(x)

    walk(value)
    return out


def sheet_texts(state: JsonValue) -> list[str]:
    """世界状态里各实体角色卡上的文字（名字、外观、生平、条目的名字和说明……）。"""
    ents = state.get("entities") if isinstance(state, dict) else None
    if not isinstance(ents, dict):
        return []
    return [t for ent in ents.values() if isinstance(ent, dict) for t in texts_of(ent.get("sheet"))]


def kp_sheets(sheets: list[JsonValue]) -> list[JsonValue]:
    """玩家自己的角色卡（SheetView）给 KP 看的样子：卡上的条目去掉代码。"""
    return [_slim_sheet_of(v) for v in sheets]
