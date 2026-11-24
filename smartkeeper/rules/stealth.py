"""隐匿：模板的 stealth 公式（在隐匿者身上算）给出某个观察者在某个距离上发现它的难度，0 及以下是不隐匿。

公式里 distance 是两者的距离（米），observer.<名字> 是观察者卡上的名字（例如 observer.template）。
观察者用自己模板的 search 骰子公式去掷，掷出的点数不小于难度就发现了。
"""

from __future__ import annotations

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import Peers, RulePack, ValidationFailed
from smartkeeper.rules.checks import context
from smartkeeper.rules.evaluator import table_lookup

OBSERVER = "observer."
VARS = ("distance",)


def as_target(node: f.Node) -> f.Node:
    """observer.x 换成 target.x：求值时观察者放在 target 的位置上。"""
    return f.substitute(
        node, lambda n: f.Name("target." + n[len(OBSERVER) :]) if n.startswith(OBSERVER) else None
    )


def text_as_target(text: str) -> str:
    return f.to_text(as_target(f.parse(text)))


def stealth(
    pack: RulePack,
    hider: tuple[str, JsonValue, Peers | None],
    observer: tuple[str, JsonValue, Peers | None],
    distance: float,
) -> float:
    """观察者在这个距离上发现隐匿者的难度；0 及以下（或模板没写 stealth）是不隐匿。写错抛 ValidationFailed。"""
    tpl = pack.template(hider[0])
    if tpl is None or not tpl.stealth.strip():
        return 0.0
    try:
        ctx = context(pack, hider[0], hider[1], hider[2])
        ctx.target = context(pack, observer[0], observer[1], observer[2])
        node = as_target(ctx.prepare(tpl.stealth))
        v = f.evaluate(
            node, ctx.resolver(None, {"distance": distance}), table_lookup(pack), None, ctx.collect
        )
    except f.FormulaError as e:
        raise ValidationFailed(e.code, formula=tpl.stealth, **e.params) from e
    if isinstance(v, str):
        raise ValidationFailed("formula.text_result", value=v)
    return v
