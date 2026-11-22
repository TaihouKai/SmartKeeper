"""跨模块的错误类型。错误只带消息代码和参数，不带成句的文字；由前端按语言渲染。"""

from __future__ import annotations

from pydantic import JsonValue

from smartkeeper.contracts.base import Frozen


class Problem(Frozen):
    """一条校验问题。code 是消息代码，path 指出出问题的位置。"""

    code: str
    path: str = ""
    params: dict[str, JsonValue] = {}


class SmartKeeperError(Exception):
    """所有业务错误的基类。"""

    def __init__(
        self, code: str, problems: list[Problem] | None = None, /, **params: JsonValue
    ) -> None:
        self.code = code
        self.params: dict[str, JsonValue] = dict(params)
        self.problems: list[Problem] = list(problems or [])
        detail = f" {self.params}" if self.params else ""
        if self.problems:
            detail += " " + "; ".join(f"{p.code}@{p.path}{p.params or ''}" for p in self.problems)
        super().__init__(f"{code}{detail}")


class ValidationFailed(SmartKeeperError):
    """输入没有通过校验。problems 列出全部问题。"""


class NotFound(SmartKeeperError):
    """对象不存在。"""


class IllegalState(SmartKeeperError):
    """当前状态下不允许这个操作，例如非法的回合状态转换。"""


class Forbidden(SmartKeeperError):
    """调用者无权做这个操作。"""
