"""prompt 模板：每种调用一个文件，`{{name}}` 占位。没提供的占位原样保留。"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

LANGUAGES = {"zh": "简体中文", "en": "English"}
_VAR = re.compile(r"\{\{(\w+)\}\}")


@cache
def load(name: str) -> str:
    return (
        resources.files("smartkeeper.kp").joinpath(f"prompts/{name}.md").read_text(encoding="utf-8")
    )


def render(name: str, **values: str) -> str:
    text = load(name)
    if "common" not in values and "{{common}}" in text:
        values["common"] = render("_common", language=values.get("language", ""))

    def sub(m: re.Match[str]) -> str:
        return values.get(m.group(1), m.group(0))

    return _VAR.sub(sub, text).strip()


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)
