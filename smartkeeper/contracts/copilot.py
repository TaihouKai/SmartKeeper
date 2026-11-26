"""建卡助手（copilot）的数据类型：玩家在建卡页问问题，助手回答，必要时给出可以一键应用的修改。

助手和 KP 是两回事：它不读对局内容、不读 KP 的记事，只看规则书、语法说明和玩家正在写的卡。
"""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.errors import Problem


class CopilotTurn(Frozen):
    role: Literal["user", "assistant"]
    text: str


class CopilotFocus(Frozen):
    """玩家正在看的地方：哪张卡（模板），哪个分组里的哪一条（编辑条目时）。都可以空着。"""

    template: str = ""
    sheet_name: str = ""
    group: str = ""
    entry: JsonValue = None  # 正在编辑的那一条（原样）


class CopilotQuestion(Frozen):
    question: str
    history: tuple[CopilotTurn, ...] = ()  # 之前几轮的问答（只在这一页里，不存）
    sheets: JsonValue = None  # 正在写的整套卡：[{template, sheet}, ...]
    focus: CopilotFocus = CopilotFocus()
    lang: Literal["zh", "en"] = "zh"


class CopilotProposal(Frozen):
    """一处可以一键应用的修改。

    - entry：在 template 这张卡的 group 分组里加一条，或换掉名叫 replace 的那一条（空是新加；
      正在编辑某一条时就是换掉那一条）。entry 和角色卡上的条目一个格式。
    - fields：改 template 这张卡的字段（fields）和角色名（name，空是不改）。
    problems 是引擎按规则书检查出来的问题（空是检查通过）。
    """

    kind: Literal["entry", "fields"]
    template: str
    group: str = ""
    replace: str = ""
    entry: JsonValue = None
    name: str = ""
    fields: dict[str, JsonValue] = {}
    note: str = ""
    problems: tuple[Problem, ...] = ()


class CopilotAnswer(Frozen):
    answer: str  # Markdown
    proposals: tuple[CopilotProposal, ...] = ()
