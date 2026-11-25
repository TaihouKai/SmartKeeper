"""房间列表：首页列出可以加入的局，填个名字就能直接加入，不用邀请链接。

这个浏览器加入过的局（“座位”）记在 HttpOnly cookie 里，换局时从这里取回那一局的 token；
当前在玩的那一局的 token 照旧放在玩家 cookie 里，玩家接口只认它。不需要登录，也不涉及管理权限。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from smartkeeper.contracts import DocEntry, NotFound
from smartkeeper.web.auth import PLAYER_COOKIE, RateLimiter, enter_seat, seats_of
from smartkeeper.web.services import Services


class LobbyGame(BaseModel):
    id: str
    name: str
    status: Literal["setup", "characters", "running", "ended"]
    players: int
    joinable: bool  # 建角阶段才能加入
    seat: str | None = None  # 这个浏览器在这一局里的名字（加入过的话）
    active: bool = False  # 是不是这个浏览器当前在玩的那一局


class RulebookOut(BaseModel):
    game_name: str
    world_name: str
    handbook: str  # 规则书（Markdown）
    scenario: str  # 剧本的公开部分


class JoinIn(BaseModel):
    game_id: str
    name: str


class EnterIn(BaseModel):
    game_id: str


class JoinOut(BaseModel):
    ok: bool = True
    link: str  # 个人链接：换浏览器、换设备时用它回到这一局


def build_lobby_router(s: Services) -> APIRouter:
    r = APIRouter(prefix="/api/lobby", tags=["lobby"])
    e = s.engine
    join_limit = RateLimiter(limit=10, window=60)

    def link(request: Request, token: str) -> str:
        # 用浏览器访问的地址（经过端口转发时也对）
        return f"{str(request.base_url).rstrip('/')}/join/{token}"

    def mine(request: Request) -> dict[str, tuple[str, str]]:
        """这个浏览器的座位：局 id -> (token, 名字)。作废了的不算。"""
        out: dict[str, tuple[str, str]] = {}
        # 以前用邀请链接进来的只有当前这一局的 cookie，也算一个座位
        for token in [*seats_of(request), request.cookies.get(PLAYER_COOKIE) or ""]:
            if not token:
                continue
            p = e.player_by_token(token)
            if p is not None and p.game_id not in out:
                out[p.game_id] = (token, p.display_name)
        return out

    @r.get("")
    def lobby(request: Request) -> list[LobbyGame]:
        seats = mine(request)
        active = e.player_by_token(request.cookies.get(PLAYER_COOKIE) or "")
        return [
            LobbyGame(
                id=g.id,
                name=g.name,
                status=g.status,
                players=n,
                joinable=g.status == "characters",
                seat=seats[g.id][1] if g.id in seats else None,
                active=active is not None and active.game_id == g.id,
            )
            for g, n in e.lobby()
        ]

    @r.get("/docs")
    def docs() -> list[DocEntry]:
        """语法手册的目录（公开，不用登录）。"""
        return list(s.rules.docs())

    @r.get("/{game_id}/rulebook")
    def rulebook(game_id: str) -> RulebookOut:
        """房间列表里的局的规则书和公开剧本：还没加入也能看。"""
        listed = {g.id: g for g, _n in e.lobby()}
        g = listed.get(game_id)
        if g is None:
            raise NotFound("lobby.not_listed")
        pack = e.rulepack(g.id)
        return RulebookOut(
            game_name=g.name,
            world_name=pack.world.name,
            handbook=pack.handbook,
            scenario=e.public_scenario(g.id),
        )

    @r.post("/join")
    def join(body: JoinIn, request: Request, response: Response) -> JoinOut:
        ip = request.client.host if request.client else "?"
        if not join_limit.hit(ip):
            raise HTTPException(status_code=429, detail={"code": "rate.lobby"})
        if body.game_id in mine(request):
            raise HTTPException(status_code=409, detail={"code": "lobby.already_in"})
        _p, token = e.join_open(body.game_id, body.name)
        enter_seat(request, response, token)
        return JoinOut(link=link(request, token))

    @r.post("/enter")
    def enter(body: EnterIn, request: Request, response: Response) -> JoinOut:
        seat = mine(request).get(body.game_id)
        if seat is None:
            raise NotFound("lobby.no_seat")
        enter_seat(request, response, seat[0])
        return JoinOut(link=link(request, seat[0]))

    return r
