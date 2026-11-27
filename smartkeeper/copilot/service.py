"""建卡助手：把规则书、结构和语法手册放进系统提示，回答玩家的问题；给出的修改先用规则书检查，
有问题时让模型改一次。和 KP 无关：不读对局、不读记事。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue, ValidationError

from smartkeeper.contracts import (
    CopilotAnswer,
    CopilotProposal,
    CopilotQuestion,
    DocEntry,
    LLMClient,
    Message,
    Problem,
    RulePack,
    Rules,
)

PROMPT = (Path(__file__).with_name("prompt.md")).read_text(encoding="utf-8")
LANGUAGE = {"zh": "简体中文", "en": "English"}
MAX_HISTORY = 12  # 只带最近几轮问答
SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "proposals": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["answer"],
}

type Messages = Mapping[str, Mapping[str, str]]  # 语言 -> 文案键 -> 文字（界面的翻译表）


class Copilot:
    """models：用哪个实现和模型（给了局 id 就用那一局 KP 的裁定模型）；
    describe：把规则包写成结构说明（给模型看的文字）；messages：界面的翻译表，用来把语法手册和问题代码写成文字。"""

    def __init__(
        self,
        models: Callable[[str | None], tuple[LLMClient, str]],
        rules: Rules,
        describe: Callable[[RulePack], str],
        messages: Messages,
    ) -> None:
        self._models = models
        self._rules = rules
        self._describe = describe
        self._messages = messages

    # ---- 对外 ----

    def ask(self, pack: RulePack, q: CopilotQuestion, game_id: str | None = None) -> CopilotAnswer:
        system = self.system_prompt(pack, q.lang)
        messages: list[Message] = [
            {"role": t.role, "content": t.text} for t in q.history[-MAX_HISTORY:]
        ]
        messages.append({"role": "user", "content": self._user_message(q)})
        raw = self._call(system, messages, game_id)
        answer = self._parse(raw)
        if answer is None:
            # 不是 JSON：再要一次；还不行就把原文当回答
            messages += _turns(("assistant", raw), ("user", self._tr(q.lang, "copilot.need_json")))
            raw = self._call(system, messages, game_id)
            answer = self._parse(raw) or CopilotAnswer(answer=raw.strip())
        answer = self._checked(pack, q, answer)
        if any(p.problems for p in answer.proposals):
            # 引擎检查不过：把问题告诉模型，改一次
            fix = self._fix_request(q.lang, answer)
            messages += _turns(("assistant", raw), ("user", fix))
            raw2 = self._call(system, messages, game_id)
            again = self._parse(raw2)
            if (
                again is not None and again.proposals
            ):  # 改的这一版没给修改时，留着原来的（带着问题）
                answer = self._checked(pack, q, again)
        return answer

    def system_prompt(self, pack: RulePack, lang: str) -> str:
        return (
            PROMPT.replace("{handbook}", pack.handbook.strip() or "（没有）")
            .replace("{structure}", self._describe(pack))
            .replace("{reference}", self.reference(lang))
            .replace("{language}", LANGUAGE.get(lang, LANGUAGE["zh"]))
        )

    def reference(self, lang: str) -> str:
        """语法手册：按类别列出每个名字的写法、说明、能填的值和例子。"""
        lines: list[str] = []
        cat = ""
        for d in self._rules.docs():
            if d.category != cat:
                cat = d.category
                lines.append(f"\n#### {self._tr(lang, f'docs.cat.{cat}', cat)}")
            lines.append(self._doc_line(lang, d))
        return "\n".join(lines).strip()

    # ---- 内部 ----

    def _call(self, system: str, messages: list[Message], game_id: str | None) -> str:
        llm, model = self._models(game_id)
        return llm.complete(
            purpose="copilot",
            model=model,
            system=system,
            messages=messages,
            json_schema=SCHEMA,
            game_id=game_id,
        ).text

    def _user_message(self, q: CopilotQuestion) -> str:
        focus = q.focus
        parts = ["## 玩家正在写的卡", json.dumps(q.sheets, ensure_ascii=False)]
        where = [x for x in (focus.template, focus.sheet_name, focus.group) if x]
        if where or focus.entry is not None:
            parts += ["## 玩家正在看", " / ".join(where) or "（整套卡）"]
            if focus.entry is not None:
                parts += ["正在编辑的条目：", json.dumps(focus.entry, ensure_ascii=False)]
        parts += ["## 问题", q.question.strip()]
        return "\n".join(parts)

    def _doc_line(self, lang: str, d: DocEntry) -> str:
        text = f"- `{d.sig}`：{self._tr(lang, d.desc, d.desc)}"
        if d.params:
            text += "；参数：" + "，".join(f"{n}（{self._tr(lang, k, k)}）" for n, k in d.params)
        if d.values:
            text += "；可以填：" + "，".join(f"{v}（{self._tr(lang, k, k)}）" for v, k in d.values)
        if d.example:
            text += f"；例：`{d.example}`"
        return text

    def _tr(self, lang: str, key: str, fallback: str | None = None, **params: object) -> str:
        table = self._messages.get(lang) or self._messages.get("zh") or {}
        text = table.get(key)
        if text is None:
            return fallback if fallback is not None else key
        for k, v in params.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    @staticmethod
    def _parse(raw: str) -> CopilotAnswer | None:
        """取出回答里的 JSON 对象（允许包在代码块里）；读不出来是 None。"""
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
        if fence:
            text = fence.group(1)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            loaded: object = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(loaded, dict):
            return None
        data = cast(dict[str, Any], loaded)
        answer = data.get("answer")
        if not isinstance(answer, str):
            return None
        proposals: list[CopilotProposal] = []
        for item in cast(list[Any], data.get("proposals") or []):
            if not isinstance(item, dict):
                continue
            try:
                proposals.append(
                    CopilotProposal.model_validate({**cast(dict[str, Any], item), "problems": ()})
                )
            except ValidationError:
                continue
        return CopilotAnswer(answer=answer, proposals=tuple(proposals))

    def _checked(self, pack: RulePack, q: CopilotQuestion, a: CopilotAnswer) -> CopilotAnswer:
        """每处修改按规则书检查一遍（放进玩家现在的卡里检查，只留这处修改自己的问题）。"""
        return a.model_copy(
            update={"proposals": tuple(self._check_one(pack, q, p) for p in a.proposals)}
        )

    def _check_one(self, pack: RulePack, q: CopilotQuestion, p: CopilotProposal) -> CopilotProposal:
        tpl = pack.template(p.template)
        if tpl is None:
            bad = Problem(code="rules.unknown_template", params={"name": p.template})
            return p.model_copy(update={"problems": (bad,)})
        sheet = _sheet_of(q, p.template)
        if p.kind == "entry":
            if all(g.name != p.group for g in tpl.groups):
                bad = Problem(code="copilot.unknown_group", params={"name": p.group})
                return p.model_copy(update={"problems": (bad,)})
            groups = cast(dict[str, Any], sheet.setdefault("groups", {}))
            entries = list(cast(list[Any], groups.get(p.group) or []))
            old = p.replace or _name(q.focus.entry if q.focus.group == p.group else None)
            idx = next((i for i, e in enumerate(entries) if _name(e) == old), None) if old else None
            if idx is None:
                entries.append(p.entry)
                idx = len(entries) - 1
            else:
                entries[idx] = p.entry
            groups[p.group] = entries
            prefix = f"groups.{p.group}[{idx}]"
            found = [
                x
                for x in self._rules.validate_sheet(
                    pack, p.template, cast(JsonValue, sheet), creation=True
                )
                if x.path == prefix or x.path.startswith(prefix + ".")
            ]
        else:
            fields = cast(dict[str, Any], sheet.setdefault("fields", {}))
            fields.update(p.fields)
            if p.name:
                sheet["name"] = p.name
            names = {f"fields.{k}" for k in p.fields}
            found = [
                x
                for x in self._rules.validate_sheet(
                    pack, p.template, cast(JsonValue, sheet), creation=True
                )
                if x.path in names or any(x.path.startswith(n + ".") for n in names)
            ]
        return p.model_copy(update={"problems": tuple(found)})

    def _fix_request(self, lang: str, a: CopilotAnswer) -> str:
        lines = [self._tr(lang, "copilot.fix_intro")]
        for i, p in enumerate(a.proposals):
            for x in p.problems:
                params = {k: v for k, v in x.params.items()}
                msg = self._tr(lang, f"codes.{x.code}", x.code, **params)
                lines.append(f"- proposals[{i}] {x.path}：{msg}")
        return "\n".join(lines)


def _sheet_of(q: CopilotQuestion, template: str) -> dict[str, Any]:
    """玩家现在这张卡的一份拷贝（同模板有几张时优先正在看的那张）；没有就是一张空卡。"""
    found: list[dict[str, Any]] = []
    for raw in cast(list[Any], q.sheets if isinstance(q.sheets, list) else []):
        if not isinstance(raw, dict):
            continue
        s = cast(dict[str, Any], raw)
        if s.get("template") == template and isinstance(s.get("sheet"), dict):
            found.append(cast(dict[str, Any], s["sheet"]))
    pick = next(
        (s for s in found if q.focus.sheet_name and s.get("name") == q.focus.sheet_name),
        found[0] if found else None,
    )
    base: dict[str, Any] = pick if pick is not None else {"name": "", "fields": {}, "groups": {}}
    return cast(dict[str, Any], json.loads(json.dumps(base)))


def _name(entry: object) -> str:
    return str(cast(dict[str, Any], entry).get("name", "")) if isinstance(entry, dict) else ""


def _turns(*pairs: tuple[str, str]) -> list[Message]:
    return [{"role": role, "content": text} for role, text in pairs]
