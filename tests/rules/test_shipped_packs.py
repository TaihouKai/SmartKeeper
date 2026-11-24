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
