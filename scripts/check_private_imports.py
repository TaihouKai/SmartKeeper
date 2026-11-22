"""通信规则 1：模块对外只暴露包的 __init__ 导出的接口。

任何文件（含测试）导入 smartkeeper.<别的模块>.<子模块> 都是违规；只能导入 smartkeeper.<模块> 本身。
模块内部导入自己的子模块不受限制。tests/<模块>/ 视为该模块内部。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def owner_of(path: Path) -> str | None:
    parts = path.relative_to(ROOT).parts
    if parts[0] in ("smartkeeper", "tests") and len(parts) > 2:
        return parts[1]
    return None


def check_file(path: Path) -> list[str]:
    owner = owner_of(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    errors: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif node.module and node.level == 0:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            if parts[0] != "smartkeeper" or len(parts) < 3:
                continue
            if parts[1] != owner:
                rel = path.relative_to(ROOT).as_posix()
                errors.append(
                    f"{rel}:{node.lineno}: 导入了 {name}，只能导入 smartkeeper.{parts[1]}"
                )
    return errors


def main() -> int:
    errors: list[str] = []
    for base in ("smartkeeper", "tests", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            if "alembic" in path.parts:
                continue
            errors.extend(check_file(path))
    for e in errors:
        print(e)
    if errors:
        print(f"私有导入检查失败：{len(errors)} 处")
        return 1
    print("私有导入检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
