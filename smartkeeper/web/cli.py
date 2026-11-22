"""命令行：用真模型跑通建角、开场和若干轮，不经过网站。

    uv run python -m smartkeeper.web.cli demo --rulepack tests/fixtures/rulepack_single.json \\
        --map demo_shibuya --scenario scenarios/demo --players 2 --rounds 1

需要 ANTHROPIC_API_KEY（或 SMARTKEEPER_*_PROVIDER=openai_compat 加 OPENAI_COMPAT_*）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from smartkeeper.contracts import KP, GameConfig, GameSettings, Sheet, SheetSubmission
from smartkeeper.rules import parse_import
from smartkeeper.web.app import Services, Settings, build_services

ACTIONS = [
    "我环顾四周，看看刚才大屏幕黑掉时附近有没有人行为可疑。",
    "我拦住离我最近的路人，问他有没有看见一个抱着包裹的人。",
    "我往车站西侧走，留意有没有人背着很大的包匆匆离开。",
]


def _print(title: str, body: str) -> None:
    print(f"\n===== {title} =====\n{body}", flush=True)


def run_demo(
    s: Services,
    *,
    rulepack_text: str,
    map_id: str | None,
    scenario_dir: Path,
    players: int,
    rounds: int,
    language: str = "zh",
) -> str:
    e, kp = s.engine, s.kp
    pack = parse_import(rulepack_text)
    pack_id = s.packs.create_pack(pack.world.name)
    s.packs.save_version(pack_id, pack)
    game = e.create_game(
        GameConfig(
            name="cli demo",
            rulepack_id=pack_id,
            rulepack_version=1,
            map_id=map_id,
            scenario_public=(scenario_dir / "scenario_public.md").read_text(encoding="utf-8"),
            scenario_kp=(scenario_dir / "scenario_kp.md").read_text(encoding="utf-8"),
            settings=GameSettings(kp_language=language, web_search=False),
        )
    )
    gid = game.id
    pids: list[str] = []
    for i in range(players):
        p, _ = e.add_player(gid, f"玩家{i + 1}")
        pids.append(p.id)
        if e.identity_rules(gid).options:
            ident = e.assign_identity(p.id)
            _print(f"{p.display_name} 的身份", json.dumps(ident.payload, ensure_ascii=False))
        subs: list[SheetSubmission] = []
        for pe in pack.player_entities:
            sample = next(x for x in pack.samples if x.template == pe.template)
            for k in range(max(pe.min, 1)):
                raw = dict(sample.sheet)
                raw["name"] = f"{p.display_name}-{pe.template}-{k + 1}"
                subs.append(SheetSubmission(template=pe.template, sheet=Sheet.model_validate(raw)))
        e.submit_character(p.id, subs)
        review = kp.review_character(p.id)
        _print(f"{p.display_name} 建角审核", json.dumps(review.model_dump(), ensure_ascii=False))
        if not review.approved:
            # 演示里不改卡：审核意见已经写入日志，重新提交后直接通过
            e.submit_character(p.id, subs)
            e.approve_character(p.id, "cli demo override")
    kp.open_game(gid)
    for ev in e.view_for(gid, "public"):
        if ev.type == "broadcast":
            _print("开场广播", str(ev.payload.get("text")))
    for pid in pids:
        for ev in e.view_for(gid, pid):
            if ev.type == "pm_kp":
                _print(f"{pid} 的开场信息", str(ev.payload.get("text")))
    for n in range(rounds):
        for i, pid in enumerate(pids):
            text = ACTIONS[(n + i) % len(ACTIONS)]
            intent = kp.parse_intent(pid, text)
            _print(f"{pid} 的行动解析", intent.model_dump_json(indent=1))
            if intent.unresolved:
                # 网站上玩家必须把它们改成 @ 才能提交；命令行演示里视为玩家确认忽略
                _print(f"{pid} 有对应不上的指代（演示中忽略）", ", ".join(intent.unresolved))
                intent = intent.model_copy(update={"unresolved": ()})
            e.declare_action(pid, text, intent)
        kp.on_action(gid)
        r = e.round(gid, n + 1)
        _print(f"第 {n + 1} 轮状态", r.status + (f" {r.draft.get('error')}" if r.draft else ""))
        for pid in pids:
            for ev in e.view_for(gid, pid):
                if ev.type == "feedback" and ev.round_no == n + 1:
                    _print(f"{pid} 第 {n + 1} 轮反馈", str(ev.payload.get("text")))
        if r.status != "published":
            break
    calls = s.llm_log.list(gid, limit=1000)
    total_in = sum(c.input_tokens for c in calls)
    total_out = sum(c.output_tokens for c in calls)
    _print("LLM 调用", f"{len(calls)} 次，输入 {total_in} tokens，输出 {total_out} tokens")
    for ev in e.view_for(gid, KP):
        if ev.type == "adjudication":
            _print(
                f"第 {ev.round_no} 轮裁定 JSON",
                json.dumps(ev.payload["adjudication"], ensure_ascii=False, indent=1),
            )
    return gid


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--rulepack", default="tests/fixtures/rulepack_single.json")
    d.add_argument("--map", default="demo_shibuya")
    d.add_argument("--scenario", default="scenarios/demo")
    d.add_argument("--players", type=int, default=2)
    d.add_argument("--rounds", type=int, default=1)
    d.add_argument("--db", default="data/cli-demo.db")
    d.add_argument("--language", default="zh")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
    settings = Settings.from_env()
    settings = Settings(**{**settings.__dict__, "db_path": args.db})
    services = build_services(settings)
    run_demo(
        services,
        rulepack_text=Path(args.rulepack).read_text(encoding="utf-8"),
        map_id=args.map or None,
        scenario_dir=Path(args.scenario),
        players=args.players,
        rounds=args.rounds,
        language=args.language,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
