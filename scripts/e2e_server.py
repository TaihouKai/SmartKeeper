"""端到端测试用的服务器：新的临时数据库、脚本化的假 KP、已知的管理员密码。

uv run python scripts/e2e_server.py --port 8765
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E_PASSWORD = "e2e-admin-password"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    import uvicorn

    from smartkeeper.web import Settings, create_app, hash_password

    tmp = Path(tempfile.mkdtemp(prefix="sk-e2e-"))
    settings = Settings(
        db_path=str(tmp / "e2e.db"),
        maps_dir=str(ROOT / "maps"),
        scenarios_dir=str(ROOT / "scenarios"),
        static_dir=str(ROOT / "frontend" / "dist"),
        admin_password_hash=hash_password(E2E_PASSWORD),
        session_secret="e2e",
        judge_provider=os.environ.get("SMARTKEEPER_JUDGE_PROVIDER", "fake"),
        writer_provider=os.environ.get("SMARTKEEPER_WRITER_PROVIDER", "fake"),
        base_url=f"http://127.0.0.1:{args.port}",
    )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
