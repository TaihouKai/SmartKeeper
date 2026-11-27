"""离线量一局的 KP 上下文：按段落打印字数，估算 token。不调模型、不花钱。

    uv run python scripts/context_size.py <数据库> <局 id> [--pack 规则包.json] [plan adjudicate opening ...]

数据库会先复制一份再打开（不碰原库）。--pack 先在副本里把这一局换成这个规则包（看新规则包的效果）。token 按“字数 ÷ 1.93”估算（线上 gpt-6-luna 实测的比例）。
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartkeeper.kp import context as kp_context  # noqa: E402
from smartkeeper.rules import parse_import  # noqa: E402
from smartkeeper.web import Settings, build_services  # noqa: E402

CHARS_PER_TOKEN = 1.93
SIZES: list[tuple[str, int]] = []


def _measured(original: Callable[[str, str], str]) -> Callable[[str, str], str]:
    """包住上下文里的 section()：记下每个顶层段落的标题和字数（规则书里面的小标题不算）。"""

    def section(title: str, body: str) -> str:
        out = original(title, body)
        SIZES.append((title[:40], len(out)))
        return out

    return section


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, game_id = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    pack_file = None
    if "--pack" in rest:
        i = rest.index("--pack")
        pack_file = rest[i + 1]
        rest = rest[:i] + rest[i + 2 :]
    which = rest or ["plan", "adjudicate", "opening"]
    tmp = Path(tempfile.mkdtemp(prefix="sk-ctx-")) / "copy.db"
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as a, sqlite3.connect(tmp) as b:
        a.backup(b)
    s = build_services(
        Settings(
            db_path=str(tmp),
            maps_dir=str(Path(src).parent / "maps"),
            judge_provider="fake",
            writer_provider="fake",
        )
    )
    if pack_file:
        g = s.engine.game(game_id)
        pack = parse_import(Path(pack_file).read_text(encoding="utf-8"))
        v = s.packs.save_version(g.rulepack_id, pack)
        s.engine._repo.update_game(g.id, rulepack_version=v.version)  # pyright: ignore[reportPrivateUsage]
    ctx = s.kp.ctx
    kp_context.section = _measured(kp_context.section)  # pyright: ignore[reportAttributeAccessIssue]
    total_tokens = 0.0
    for name in which:
        SIZES.clear()
        prompt = ctx.opening(game_id)[0] if name == "opening" else getattr(ctx, name)(game_id)
        chars = len(prompt.system) + len(prompt.user)
        tokens = chars / CHARS_PER_TOKEN
        total_tokens += tokens
        print(f"=== {name}: {chars} 字，约 {tokens:,.0f} token（system {len(prompt.system)} 字）")
        for title, n in SIZES:
            print(f"  {n:7d}  {title}")
    print(f"合计约 {total_tokens:,.0f} token")
    s.db.dispose()
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
