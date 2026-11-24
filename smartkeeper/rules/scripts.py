"""技能脚本的规划：在使用者的角色卡上把每一句的数值算好（掷骰、冻结），交给引擎在生效时执行。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import Peers, RulePack, ScriptStep, ValidationFailed
from smartkeeper.rules import skillconfig
from smartkeeper.rules.checks import context
from smartkeeper.rules.evaluator import EntityContext, table_lookup

type Op = Literal["damage", "add", "subtract", "set", "modify"]
_OPS: dict[str, Op] = {
    "damage": "damage",
    "add": "add",
    "sub": "subtract",
    "set": "set",
    "modify": "modify",
}


def plan_script(
    pack: RulePack,
    script: str,
    faces: f.Faces,
    template: str,
    sheet: JsonValue,
    entry: dict[str, JsonValue],
    peers: Peers | None = None,
    target: tuple[str, JsonValue, Peers | None] | None = None,
    config: str = "",
) -> tuple[ScriptStep, ...]:
    try:
        nodes = f.parse_script(script)
    except f.FormulaError as e:
        raise ValidationFailed(e.code, **e.params) from e
    ctx = context(pack, template, sheet, peers)
    if target is not None:
        ctx.target = context(pack, target[0], target[1], target[2])
    lookup = table_lookup(pack)
    steps: list[ScriptStep] = []
    local: dict[str, f.Value] = {}  # 局部变量：算一次，后面的句子按名字取
    # 设置的各项：在脚本的公式里换成它们的公式
    env = {k: v for k, v in skillconfig.names(config, script).items() if k in skillconfig.KEYS}

    def prep(text: str) -> f.Node:
        return skillconfig.expand(ctx.prepare(text, entry), env)

    def run(body: tuple[f.ScriptNode, ...]) -> None:
        for node in body:
            line = node.line
            try:
                if isinstance(node, f.Let):
                    v = f.evaluate(
                        prep(node.value),
                        ctx.resolver(entry, local),
                        lookup,
                        None,
                        ctx.collect,
                    )
                    local[node.name] = v
                    continue
                if isinstance(node, f.Statement):
                    if node.receiver == "target" and target is None:
                        continue
                    steps.append(_step(ctx, lookup, faces, entry, node, local, prep))
                    continue
                for b in node.branches:
                    if b.condition is None:
                        run(b.body)
                        break
                    line = b.line
                    cond = prep(b.condition)
                    if target is None and any(n.startswith("target.") for n in f.names(cond)):
                        break  # 没有对象时，问对象的条件整块跳过
                    if f.truthy(
                        f.evaluate(cond, ctx.resolver(entry, local), lookup, None, ctx.collect)
                    ):
                        run(b.body)
                        break
            except f.FormulaError as e:
                raise ValidationFailed(e.code, line=line, **e.params) from e

    run(nodes)
    return tuple(steps)


def _step(
    ctx: EntityContext,
    lookup: f.TableLookup,
    faces: f.Faces,
    entry: dict[str, JsonValue],
    st: f.Statement,
    local: dict[str, f.Value],
    prep: Callable[[str], f.Node],
) -> ScriptStep:
    rolls: list[int] = []

    def record(count: int, sides: int) -> tuple[int, ...]:
        got = faces(count, sides)
        rolls.extend(got)
        return got

    def num(text: str) -> float:
        v = f.evaluate(prep(text), ctx.resolver(entry, local), lookup, record, ctx.collect)
        if isinstance(v, str):
            raise f.FormulaError("formula.text_result", value=v)
        return v

    seconds = int(num(st.minutes) * 60) if st.minutes is not None else None
    if st.verb == "modify":
        assert st.formula is not None and st.field is not None
        # 被修正的推导值自己的名字留着（在带着这条修正的角色身上求值），其余名字都换成此刻的值
        node = prep(st.formula)
        resolve = ctx.resolver(entry, local)
        values = {n: resolve(n) for n in f.names(node) if n != st.field}
        return ScriptStep(
            who=st.receiver,
            op="modify",
            field=st.field,
            formula=f.to_text(node, values),
            seconds=seconds,
        )
    assert st.amount is not None
    rolls.clear()
    amount = num(st.amount)
    return ScriptStep(
        who=st.receiver,
        op=_OPS[st.verb],
        field=st.field,
        amount=amount,
        rolls=tuple(rolls),
        seconds=seconds,
    )
