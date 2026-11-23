"""前端“公式速查”里的函数表要和后端公式语言的函数白名单一致，说明文字要有翻译。"""

import json
import re
from pathlib import Path

from smartkeeper.rules import FUNCTIONS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def test_formula_help_lists_every_function() -> None:
    src = (FRONTEND / "ui" / "FormulaHelp.tsx").read_text(encoding="utf-8")
    block = src.split("FUNCTION_SIGNATURES", 1)[1]
    listed = re.findall(r'\["(\w+)", "\1\(', block)
    assert sorted(listed) == sorted(FUNCTIONS)
    for lang in ("zh", "en"):
        table = json.loads((FRONTEND / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert set(table["fh"]["fn"]) == set(FUNCTIONS)
