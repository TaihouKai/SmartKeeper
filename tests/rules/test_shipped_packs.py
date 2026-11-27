"""rulepacks/ 里随仓库发布的规则包都要能通过校验。"""

from pathlib import Path

import pytest

from smartkeeper.rules import RulesService
from smartkeeper.rules.store import parse_import

PACKS = sorted((Path(__file__).resolve().parents[2] / "rulepacks").glob("*/pack.json"))


@pytest.mark.parametrize("path", PACKS, ids=[p.parent.name for p in PACKS])
def test_shipped_pack_is_valid(path: Path) -> None:
    pack = parse_import(path.read_text(encoding="utf-8"))
    assert RulesService().validate_pack(pack) == []


BUILDS = sorted((Path(__file__).resolve().parents[2] / "rulepacks").glob("*/build.py"))


@pytest.mark.parametrize("path", BUILDS, ids=lambda p: p.parent.name)
def test_shipped_lore_passes_its_own_content_check(path: Path) -> None:
    """规则包的构建脚本可以给资料库定内容检查（例如不收某部作品专属的设定）：随仓库发布的资料库要通过。"""
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(f"build_{path.parent.name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    check = getattr(mod, "lore_problems", None)
    src = path.with_name("lore_worldinfo.json")
    if check is None or not src.exists():
        pytest.skip("no lore check")
    assert check(json.loads(src.read_text(encoding="utf-8"))) == []
