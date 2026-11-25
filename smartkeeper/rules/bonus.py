"""常驻加成：代码（GroupEntry.bonus / EntryUse.bonus）编译成一串修正。旧格式的 effects 列表接在后面。"""

from __future__ import annotations

import functools

from smartkeeper import lang as f
from smartkeeper.contracts import Effect


@functools.lru_cache(maxsize=2048)
def compile_bonus(text: str) -> tuple[Effect, ...]:
    """写错的代码编译成空（校验会报）。"""
    if not text.strip():
        return ()
    try:
        lines = f.parse_bonus(text)
    except f.FormulaError:
        return ()
    return tuple(
        Effect(description=b.description, target=b.target, formula=b.formula) for b in lines
    )


def effects_of(bonus: str, legacy: tuple[Effect, ...] = ()) -> tuple[Effect, ...]:
    """一个条目（或开关用途）的全部常驻加成：代码里的，加上旧格式列表里的。"""
    return (*compile_bonus(bonus), *legacy)
