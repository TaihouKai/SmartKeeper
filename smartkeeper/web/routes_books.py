"""规则书：和对局列表分开的总览。每套规则书下面有它的剧本（只看公开部分）和角色库。

不用登录：谁都能看规则书、剧本和角色列表；不进局也能新建、编辑、删除角色库里的角色
（设了密码的要密码，猜密码按 IP 限速）。规则书和剧本本身只能由管理员改。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from smartkeeper.contracts import (
    CopilotAnswer,
    CopilotQuestion,
    LibraryCharacter,
    LibraryCharacterFull,
    NotFound,
    RulePack,
)
from smartkeeper.engine import public_meta, split_front_matter
from smartkeeper.web import sheetform
from smartkeeper.web.auth import RateLimiter
from smartkeeper.web.services import Services
from smartkeeper.web.sheetform import (
    FormRules,
    FormulaOut,
    LibraryOpenIn,
    LibrarySaveIn,
    PreviewIn,
    PreviewOut,
    SheetFormulaIn,
)

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class ScenarioSummary(BaseModel):
    id: str
    title: str
    start_time: str = ""
    intro: str = ""  # 开头一段


class BookSummary(BaseModel):
    id: str
    name: str
    world_name: str
    description: str = ""
    scenarios: int = 0
    characters: int = 0


class BookOut(BookSummary):
    handbook: str = ""
    scenario_list: list[ScenarioSummary] = []
    character_list: list[LibraryCharacter] = []


class BookScenarioOut(BaseModel):
    id: str
    title: str
    book: str  # 规则书名
    text: str  # 公开部分（不含开头的设置）


class OkOut(BaseModel):
    ok: bool = True


def _title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _intro(body: str) -> str:
    """标题后面的第一段。"""
    paras = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    return paras[0][:200] if paras else ""


def build_books_router(s: Services) -> APIRouter:
    r = APIRouter(prefix="/api/books", tags=["books"])
    e = s.engine
    scen_dir = Path(s.scenarios_dir)
    limit = RateLimiter(limit=10, window=60)

    def ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def guard(request: Request) -> None:
        if not limit.hit(ip(request)):
            raise HTTPException(status_code=429, detail={"code": "rate.library"})

    def scenarios_of(pack: RulePack) -> list[tuple[str, str]]:
        """这套规则书的剧本：(剧本 id, 公开部分全文)。剧本开头写了 rulebook: 规则书名 的才算。"""
        out: list[tuple[str, str]] = []
        if not scen_dir.is_dir():
            return out
        for d in sorted(scen_dir.iterdir()):
            f = d / "scenario_public.md"
            if not _NAME.match(d.name) or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
                book = str(split_front_matter(text)[0].get("rulebook") or "")
            except (OSError, ValueError):
                continue
            if book == pack.world.name:
                out.append((d.name, text))
        return out

    def summary(sid: str, text: str) -> ScenarioSummary:
        body = split_front_matter(text)[1]
        try:
            start = public_meta(text).start_time
        except Exception:
            start = ""
        return ScenarioSummary(
            id=sid, title=_title(body, sid), start_time=start, intro=_intro(body)
        )

    @r.get("")
    def books() -> list[BookSummary]:
        out: list[BookSummary] = []
        for info in e.books():
            pack = e.book_pack(info.pack_id)
            out.append(
                BookSummary(
                    id=info.pack_id,
                    name=info.name,
                    world_name=pack.world.name,
                    description=pack.world.description,
                    scenarios=len(scenarios_of(pack)),
                    characters=len(e.library_of(info.pack_id)),
                )
            )
        return out

    @r.get("/{book_id}")
    def book(book_id: str) -> BookOut:
        pack = e.book_pack(book_id)
        info = next(p for p in e.books() if p.pack_id == book_id)
        scen = [summary(sid, text) for sid, text in scenarios_of(pack)]
        chars = e.library_of(book_id)
        return BookOut(
            id=book_id,
            name=info.name,
            world_name=pack.world.name,
            description=pack.world.description,
            scenarios=len(scen),
            characters=len(chars),
            handbook=pack.handbook,
            scenario_list=scen,
            character_list=chars,
        )

    @r.get("/{book_id}/scenarios/{scenario_id}")
    def scenario(book_id: str, scenario_id: str) -> BookScenarioOut:
        pack = e.book_pack(book_id)
        text = dict(scenarios_of(pack)).get(scenario_id)
        if text is None:
            raise NotFound("scenario.not_found", name=scenario_id)
        body = split_front_matter(text)[1]
        return BookScenarioOut(
            id=scenario_id, title=_title(body, scenario_id), book=pack.world.name, text=body
        )

    # ---- 不进局建卡：表单要的规则、预览、公式检查（按规则书的最新版本） ----

    @r.get("/{book_id}/form")
    def form(book_id: str) -> FormRules:
        return sheetform.form_rules(e.book_pack(book_id))

    @r.post("/{book_id}/preview")
    def preview(book_id: str, body: PreviewIn) -> PreviewOut:
        return sheetform.preview(s.rules, e.book_pack(book_id), body, {})

    @r.post("/{book_id}/formula")
    def formula(book_id: str, body: SheetFormulaIn) -> FormulaOut:
        return sheetform.check_formula(s.rules, e.book_pack(book_id), body)

    # 建卡助手：每个 IP 十分钟最多问 20 次（每次都是一次模型调用）
    copilot_limit = RateLimiter(limit=20, window=600)

    @r.post("/{book_id}/copilot")
    def copilot(book_id: str, body: CopilotQuestion, request: Request) -> CopilotAnswer:
        if not copilot_limit.hit(ip(request)):
            raise HTTPException(status_code=429, detail={"code": "rate.copilot"})
        return sheetform.ask_copilot(s.copilot, e.book_pack(book_id), body, None)

    # ---- 角色库 ----

    @r.post("/{book_id}/characters/{char_id}/open")
    def open_character(
        book_id: str, char_id: str, body: LibraryOpenIn, request: Request
    ) -> LibraryCharacterFull:
        guard(request)
        return e.open_library_character(book_id, char_id, body.password)

    @r.post("/{book_id}/characters")
    def new_character(book_id: str, body: LibrarySaveIn) -> LibraryCharacter:
        return e.save_to_library(
            book_id,
            body.author,
            body.sheets,
            name=body.name,
            summary=body.summary,
            password=body.password,
        )

    @r.put("/{book_id}/characters/{char_id}")
    def update_character(
        book_id: str, char_id: str, body: LibrarySaveIn, request: Request
    ) -> LibraryCharacter:
        guard(request)
        return e.save_to_library(
            book_id,
            body.author,
            body.sheets,
            name=body.name,
            summary=body.summary,
            char_id=char_id,
            password=body.password,
            new_password=body.new_password,
        )

    @r.post("/{book_id}/characters/{char_id}/delete")
    def delete_character(
        book_id: str, char_id: str, body: LibraryOpenIn, request: Request
    ) -> OkOut:
        guard(request)
        e.delete_library_character(book_id, char_id, body.password)
        return OkOut()

    return r
