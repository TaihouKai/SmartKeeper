"""rulepacks/ 里带 playtest.py 的规则包：在引擎上把它的场景跑一遍（不调用模型），全部通过。"""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[2] / "rulepacks").glob("*/playtest.py"))


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.parent.name for p in SCRIPTS])
def test_playtest_passes(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = importlib.util.spec_from_file_location(f"playtest_{path.parent.name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    code = mod.main()
    out = capsys.readouterr().out
    assert code == 0, out
