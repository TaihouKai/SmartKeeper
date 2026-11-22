"""一条命令跑完全部检查：uv run python scripts/check.py [--fix] [--no-frontend]

格式、lint、类型、依赖方向、私有导入、翻译完整性、专有名词、后端测试、前端类型与测试。
任何一项失败，整体失败。
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def steps(fix: bool, frontend: bool) -> list[tuple[str, list[str], Path]]:
    py = sys.executable
    s: list[tuple[str, list[str], Path]] = [
        ("格式", [py, "-m", "ruff", "format", *([] if fix else ["--check"]), "."], ROOT),
        ("lint", [py, "-m", "ruff", "check", *(["--fix"] if fix else []), "."], ROOT),
        ("类型", [py, "-m", "pyright"], ROOT),
        ("依赖方向", [str(Path(py).parent / "lint-imports")], ROOT),
        ("私有导入", [py, "scripts/check_private_imports.py"], ROOT),
        ("翻译", [py, "scripts/check_i18n.py"], ROOT),
        ("专有名词", [py, "scripts/check_terms.py"], ROOT),
        ("后端测试", [py, "-m", "pytest"], ROOT),
    ]
    if frontend:
        s += [
            ("前端类型", [npm(), "run", "--silent", "typecheck"], ROOT / "frontend"),
            ("前端测试", [npm(), "run", "--silent", "test"], ROOT / "frontend"),
        ]
    return s


def main() -> int:
    out = sys.stdout
    if isinstance(out, io.TextIOWrapper):
        out.reconfigure(encoding="utf-8")  # pyright: ignore[reportUnknownMemberType]
    fix = "--fix" in sys.argv
    frontend = "--no-frontend" not in sys.argv
    failed: list[str] = []
    for name, cmd, cwd in steps(fix, frontend):
        t0 = time.monotonic()
        print(f"\n=== {name} ===", flush=True)
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        rc = subprocess.run(cmd, cwd=cwd, env=env).returncode
        print(
            f"--- {name}: {'通过' if rc == 0 else '失败'} ({time.monotonic() - t0:.1f}s)",
            flush=True,
        )
        if rc != 0:
            failed.append(name)
    print()
    if failed:
        print("检查失败：" + "、".join(failed))
        return 1
    print("全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
