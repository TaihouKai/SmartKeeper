"""导出 HTTP API 的 OpenAPI schema，并生成前端的 API 类型（frontend/src/api/schema.ts）。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smartkeeper.web import Settings, create_app

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        app = create_app(
            Settings(
                db_path=str(Path(d) / "x.db"),
                judge_provider="fake",
                writer_provider="fake",
                static_dir=str(Path(d) / "none"),
            )
        )
        schema = app.openapi()
        app.state.services.db.dispose()
    out = ROOT / "frontend" / "openapi.json"
    out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    rc = subprocess.run(
        [npx, "openapi-typescript", "openapi.json", "-o", "src/api/schema.ts"],
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
    )
    if rc.returncode != 0:
        print(rc.stdout, rc.stderr)
        return rc.returncode
    print("api types regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
