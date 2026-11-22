"""真模型泄密测试：需要真模型的凭据，默认不跑。uv run pytest -m live tests/e2e"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
def test_ten_rounds_with_a_prying_player_leak_nothing() -> None:
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "live_leak_test.py"), "--rounds", "10"], cwd=ROOT
    )
    assert rc.returncode == 0
