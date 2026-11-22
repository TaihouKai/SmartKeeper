"""校验一个剧本目录的 front matter：uv run python scripts/check_scenario.py scenarios/demo"""

from __future__ import annotations

import sys
from pathlib import Path

from smartkeeper.engine import kp_meta, public_meta


def main() -> int:
    d = Path(sys.argv[1])
    pub = public_meta((d / "scenario_public.md").read_text(encoding="utf-8"))
    kp = kp_meta((d / "scenario_kp.md").read_text(encoding="utf-8"))
    print(
        f"identities={len(pub.identities.options)} npcs={len(kp.npcs)} positions={len(kp.initial_positions)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
