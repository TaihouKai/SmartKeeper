"""翻译检查。

1. frontend/src/i18n/ 下各语言文件的键集合必须一致，且值都非空。
2. 源码里用到的 t("key") 必须在翻译文件里存在。
3. .tsx 里不得出现未经翻译函数包裹的界面文字：JSX 文本节点，或 placeholder/title/alt/aria-label/label 的字面量。
   确实不需要翻译的文字（例如 "OpenStreetMap" 署名）在同一行加注释 `i18n-ignore`。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "frontend" / "src" / "i18n"
SRC_DIRS = (ROOT / "frontend" / "src", ROOT / "frontend" / "demo")

JSX_TEXT = re.compile(r">([^<>{}]*[A-Za-z一-鿿][^<>{}]*)<")
ATTR_LITERAL = re.compile(
    r"\b(placeholder|title|alt|aria-label|label)=\"([^\"]*[A-Za-z一-鿿][^\"]*)\""
)
T_CALL = re.compile(r"\bt\(\s*[\"']([A-Za-z0-9_.\-]+)[\"']")


def flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))  # pyright: ignore[reportUnknownArgumentType]
        else:
            out[key] = str(v)
    return out


def main() -> int:
    errors: list[str] = []
    langs: dict[str, dict[str, str]] = {}
    for f in sorted(I18N_DIR.glob("*.json")):
        langs[f.stem] = flatten(json.loads(f.read_text(encoding="utf-8")))
    if set(langs) != {"zh", "en"}:
        errors.append(f"翻译文件应为 zh.json 和 en.json，实际为 {sorted(langs)}")
    all_keys: set[str] = set()
    for table in langs.values():
        all_keys |= set(table)
    for lang, table in langs.items():
        for k in sorted(all_keys - set(table)):
            errors.append(f"{lang}.json 缺少键 {k}")
        for k, v in table.items():
            if not v.strip():
                errors.append(f"{lang}.json 的 {k} 为空")

    files = [p for d in SRC_DIRS for ext in ("*.tsx", "*.ts") for p in d.rglob(ext)]
    for path in files:
        if (
            "node_modules" in path.parts
            or path.name.endswith(".test.tsx")
            or path.name.endswith(".test.ts")
            or path.parent.name == "api"
        ):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for key in T_CALL.findall(text):
            if key not in all_keys:
                errors.append(f"{rel}: 用到了不存在的翻译键 {key}")
        if path.suffix != ".tsx":
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "i18n-ignore" in line or line.strip().startswith(("//", "*", "/*")):
                continue
            for m in JSX_TEXT.finditer(line):
                frag = m.group(1).strip()
                if (
                    frag
                    and not re.fullmatch(r"[\s\W\d]*", frag)
                    and "=>" not in frag
                    and "&&" not in frag
                ):
                    errors.append(f"{rel}:{lineno}: 未翻译的界面文字 {frag!r}")
            for m in ATTR_LITERAL.finditer(line):
                errors.append(f"{rel}:{lineno}: 未翻译的属性 {m.group(1)}={m.group(2)!r}")
    for e in errors:
        print(e)
    if errors:
        print(f"翻译检查失败：{len(errors)} 处")
        return 1
    print(f"翻译检查通过（{len(all_keys)} 个键）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
