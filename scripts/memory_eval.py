"""对一局跑记忆的回放出题：uv run python scripts/memory_eval.py <game_id> [--db data/smartkeeper.db] [--no-llm]

只算检索召回率不调用模型（--no-llm）；默认还会用当前配置的模型跑声明核对，统计召回率和特异度。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from smartkeeper.kp import build_quiz, run_quiz
from smartkeeper.web import Settings, build_services


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_id")
    ap.add_argument("--db", default=None)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()
    settings = Settings.from_env()
    if args.db:
        settings = dataclasses.replace(settings, db_path=args.db)
    s = build_services(settings)
    quiz = build_quiz(s.engine, args.game_id)
    report = run_quiz(s.kp, args.game_id, quiz, with_claims=not args.no_llm)
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
