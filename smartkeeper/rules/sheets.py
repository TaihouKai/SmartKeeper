"""角色卡的辅助操作。"""

from __future__ import annotations

import copy

from pydantic import JsonValue
from pydantic import ValidationError as PydanticError

from smartkeeper.contracts import EntityTemplate, RulePack, Sheet
from smartkeeper.rules.evaluator import EntityContext


def init_sheet(pack: RulePack, tpl: EntityTemplate, raw: JsonValue) -> JsonValue:
    """补上运行值的初值。初值公式可以引用推导值和玩家填写的字段。

    卡的结构不合法时原样返回，由 validate_sheet 报告问题。
    """
    if not isinstance(raw, dict):
        return raw
    out = copy.deepcopy(raw)
    fields = out.setdefault("fields", {})
    if not isinstance(fields, dict):
        return out
    try:
        sheet = Sheet.model_validate(out)
    except PydanticError:
        return out
    ctx = EntityContext(pack, tpl, sheet)
    for fd in tpl.fields:
        if fd.cls != "runtime" or fd.name in fields:
            continue
        if fd.initial is None:
            fields[fd.name] = ""
        else:
            v = ctx.eval(fd.initial)
            fields[fd.name] = v
    return out
