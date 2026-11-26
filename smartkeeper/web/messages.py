"""界面的翻译表（frontend/src/i18n/{zh,en}.json，由 scripts/i18n_source.py 生成），给后端需要把文案键写成文字的地方用
（例如建卡助手要把语法手册和问题代码写成文字）。找不到文件时是空表，用的地方退回文案键本身。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

I18N_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"


def _flatten(prefix: str, node: Any, out: dict[str, str]) -> None:
    if isinstance(node, dict):
        for k, v in cast(dict[str, Any], node).items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(node, str):
        out[prefix] = node


def load_messages(directory: Path = I18N_DIR) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for lang in ("zh", "en"):
        try:
            data = json.loads((directory / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        flat: dict[str, str] = {}
        _flatten("", data, flat)
        out[lang] = flat
    return out
