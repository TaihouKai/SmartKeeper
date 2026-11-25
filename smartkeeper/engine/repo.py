"""engine 自己的表：局、玩家、回合。"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import Game, GameSettings, NotFound, Player, Round

metadata = sa.MetaData()

game = sa.Table(
    "game",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("rulepack_id", sa.String, nullable=False),
    sa.Column("rulepack_version", sa.Integer, nullable=False),
    sa.Column("map_id", sa.String, nullable=True),
    sa.Column("scenario_public", sa.Text, nullable=False),
    sa.Column("scenario_kp", sa.Text, nullable=False),
    sa.Column("settings", sa.Text, nullable=False),
    sa.Column("current_round", sa.Integer, nullable=False, default=0),
    sa.Column("created_at", sa.String, nullable=False),
)

player = sa.Table(
    "player",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("game_id", sa.String, sa.ForeignKey("game.id"), nullable=False),
    sa.Column("display_name", sa.String, nullable=False),
    sa.Column("token_hash", sa.String, nullable=False, unique=True),
    sa.Column("ui_language", sa.String, nullable=False, default="zh"),
    sa.Column("active", sa.Boolean, nullable=False, default=True),
    sa.Column("created_at", sa.String, nullable=False),
    # 没提交的角色卡（建角表单自动保存的，原样存 JSON，不校验）
    sa.Column("character_draft", sa.Text, nullable=True),
    sa.Column("character_draft_at", sa.String, nullable=True),
)

round_ = sa.Table(
    "round",
    metadata,
    sa.Column("game_id", sa.String, sa.ForeignKey("game.id"), primary_key=True),
    sa.Column("no", sa.Integer, primary_key=True),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("started_second", sa.Integer, nullable=False),
    sa.Column("ended_second", sa.Integer, nullable=True),
    sa.Column("forced", sa.Boolean, nullable=False, default=False),
    sa.Column("submitted", sa.Text, nullable=False, default="[]"),
    sa.Column("draft", sa.Text, nullable=True),
    sa.Column("discarded", sa.Text, nullable=False, default="[]"),
    sa.Column("snapshot", sa.Text, nullable=True),
)


def _game(m: Any) -> Game:
    return Game(
        id=m["id"],
        name=m["name"],
        status=m["status"],
        rulepack_id=m["rulepack_id"],
        rulepack_version=m["rulepack_version"],
        map_id=m["map_id"],
        scenario_public=m["scenario_public"],
        scenario_kp=m["scenario_kp"],
        settings=GameSettings.model_validate_json(m["settings"]),
        current_round=m["current_round"],
    )


def _player(m: Any) -> Player:
    return Player(
        id=m["id"],
        game_id=m["game_id"],
        display_name=m["display_name"],
        ui_language=m["ui_language"],
        active=bool(m["active"]),
    )


def _round(m: Any) -> Round:
    return Round(
        game_id=m["game_id"],
        no=m["no"],
        status=m["status"],
        started_second=m["started_second"],
        ended_second=m["ended_second"],
        forced=bool(m["forced"]),
        submitted=tuple(json.loads(m["submitted"])),
        draft=json.loads(m["draft"]) if m["draft"] else None,
        snapshot=json.loads(m["snapshot"]) if m["snapshot"] else None,
    )


class Repo:
    def __init__(self, db: sa.Engine) -> None:
        self.db = db
        metadata.create_all(db)

    # ---- game ----

    def insert_game(self, g: Game, created_at: str) -> None:
        with self.db.begin() as c:
            c.execute(
                game.insert().values(
                    id=g.id,
                    name=g.name,
                    status=g.status,
                    rulepack_id=g.rulepack_id,
                    rulepack_version=g.rulepack_version,
                    map_id=g.map_id,
                    scenario_public=g.scenario_public,
                    scenario_kp=g.scenario_kp,
                    settings=g.settings.model_dump_json(),
                    current_round=g.current_round,
                    created_at=created_at,
                )
            )

    def get_game(self, game_id: str) -> Game:
        with self.db.connect() as c:
            row = c.execute(sa.select(game).where(game.c.id == game_id)).first()
        if row is None:
            raise NotFound("game.not_found", game_id=game_id)
        return _game(row._mapping)  # pyright: ignore[reportPrivateUsage]

    def list_games(self) -> list[Game]:
        with self.db.connect() as c:
            rows = c.execute(sa.select(game).order_by(game.c.created_at)).all()
        return [_game(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def update_game(self, game_id: str, **values: Any) -> None:
        if "settings" in values and isinstance(values["settings"], GameSettings):
            values["settings"] = values["settings"].model_dump_json()
        with self.db.begin() as c:
            c.execute(game.update().where(game.c.id == game_id).values(**values))

    def games_using(self, pack_id: str, version: int) -> list[str]:
        with self.db.connect() as c:
            rows = c.execute(
                sa.select(game.c.id).where(
                    game.c.rulepack_id == pack_id, game.c.rulepack_version == version
                )
            ).all()
        return [r[0] for r in rows]

    # ---- player ----

    def insert_player(self, p: Player, token_hash: str, created_at: str) -> None:
        with self.db.begin() as c:
            c.execute(
                player.insert().values(
                    id=p.id,
                    game_id=p.game_id,
                    display_name=p.display_name,
                    token_hash=token_hash,
                    ui_language=p.ui_language,
                    active=p.active,
                    created_at=created_at,
                )
            )

    def get_player(self, player_id: str) -> Player:
        with self.db.connect() as c:
            row = c.execute(sa.select(player).where(player.c.id == player_id)).first()
        if row is None:
            raise NotFound("player.not_found", player_id=player_id)
        return _player(row._mapping)  # pyright: ignore[reportPrivateUsage]

    def player_by_token_hash(self, token_hash: str) -> Player | None:
        with self.db.connect() as c:
            row = c.execute(sa.select(player).where(player.c.token_hash == token_hash)).first()
        return _player(row._mapping) if row is not None else None  # pyright: ignore[reportPrivateUsage]

    def players(self, game_id: str) -> list[Player]:
        with self.db.connect() as c:
            rows = c.execute(
                sa.select(player)
                .where(player.c.game_id == game_id)
                .order_by(player.c.created_at, player.c.id)
            ).all()
        return [_player(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def character_draft(self, player_id: str) -> tuple[JsonValue, str] | None:
        with self.db.connect() as c:
            row = c.execute(
                sa.select(player.c.character_draft, player.c.character_draft_at).where(
                    player.c.id == player_id
                )
            ).first()
        if row is None or row[0] is None:
            return None
        return json.loads(row[0]), str(row[1])

    def set_character_draft(self, player_id: str, draft: JsonValue | None, at: str | None) -> None:
        body = None if draft is None else json.dumps(draft, ensure_ascii=False)
        self.update_player(player_id, character_draft=body, character_draft_at=at)

    def update_player(self, player_id: str, **values: Any) -> None:
        with self.db.begin() as c:
            c.execute(player.update().where(player.c.id == player_id).values(**values))

    # ---- round ----

    def insert_round(self, r: Round) -> None:
        with self.db.begin() as c:
            c.execute(
                round_.insert().values(
                    game_id=r.game_id,
                    no=r.no,
                    status=r.status,
                    started_second=r.started_second,
                    ended_second=r.ended_second,
                    forced=r.forced,
                    submitted=json.dumps(list(r.submitted)),
                    draft=None,
                    discarded="[]",
                    snapshot=None,
                )
            )

    def get_round(self, game_id: str, no: int) -> Round:
        with self.db.connect() as c:
            row = c.execute(
                sa.select(round_).where(round_.c.game_id == game_id, round_.c.no == no)
            ).first()
        if row is None:
            raise NotFound("round.not_found", game_id=game_id, no=no)
        return _round(row._mapping)  # pyright: ignore[reportPrivateUsage]

    def rounds(self, game_id: str) -> list[Round]:
        with self.db.connect() as c:
            rows = c.execute(
                sa.select(round_).where(round_.c.game_id == game_id).order_by(round_.c.no)
            ).all()
        return [_round(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def rounds_in(self, status: str) -> list[Round]:
        with self.db.connect() as c:
            rows = c.execute(sa.select(round_).where(round_.c.status == status)).all()
        return [_round(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def update_round(self, game_id: str, no: int, **values: Any) -> None:
        for key in ("draft", "snapshot"):
            if key in values and values[key] is not None:
                values[key] = json.dumps(values[key], ensure_ascii=False, sort_keys=True)
        if "submitted" in values:
            values["submitted"] = json.dumps(list(values["submitted"]))
        with self.db.begin() as c:
            c.execute(
                round_.update()
                .where(round_.c.game_id == game_id, round_.c.no == no)
                .values(**values)
            )

    def discard_draft(self, game_id: str, no: int, draft: JsonValue) -> None:
        with self.db.begin() as c:
            row = c.execute(
                sa.select(round_.c.discarded).where(round_.c.game_id == game_id, round_.c.no == no)
            ).first()
            old: list[JsonValue] = json.loads(row[0]) if row else []
            old.append(draft)
            c.execute(
                round_.update()
                .where(round_.c.game_id == game_id, round_.c.no == no)
                .values(discarded=json.dumps(old, ensure_ascii=False), draft=None)
            )
