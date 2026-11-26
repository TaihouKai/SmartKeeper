"""角色卡导出 PDF：只印人读得懂的东西（不印技能设置、脚本、加成这些代码），没填完的卡也能导出。"""

from __future__ import annotations

import copy
from typing import Any

from smartkeeper.rules import RulesService
from smartkeeper.web import sheetpdf
from smartkeeper.web.messages import load_messages
from tests.fixtures import load_pack
from tests.web.conftest import Site
from tests.web.test_books import import_pack
from tests.web.test_library import sample

WORDS = sheetpdf.words_for(load_messages(), "zh")


def sheets_with_code() -> list[dict[str, Any]]:
    s: list[dict[str, Any]] = copy.deepcopy(sample())  # type: ignore[assignment]
    s[0]["sheet"]["groups"]["skills"] = [
        {
            "name": "first aid",
            "fields": {"level": 30},
            "description": "Patch someone up. See [[Healing]].",
            "config": 'target = "single"\nrange = 2',
            "script": "target.add(hp, 3)",
            "bonus": "self.str += 1",
        }
    ]
    return s


def test_cards_hold_what_a_person_reads_and_no_code() -> None:
    pack = load_pack("single")
    s = sheets_with_code()
    [card] = sheetpdf.build_cards(
        RulesService(), pack, [(x["template"], x["sheet"]) for x in s], {}, WORDS
    )
    assert card.name == "Sample A"
    assert "50" in dict(card.numbers).values()
    [sec] = [x for x in card.sections if x.own]
    [e] = sec.own
    assert e.name == "first aid" and e.text == "Patch someone up. See Healing."
    assert any("30" in t for t in e.tags)
    printed = repr(card)
    for code in ("range = 2", "target.add", "self.str += 1"):
        assert code not in printed


def test_unfinished_sheets_still_export() -> None:
    pack = load_pack("single")
    cards = sheetpdf.build_cards(
        RulesService(), pack, [("person", {"name": "", "fields": {}})], {}, WORDS
    )
    assert cards[0].name == WORDS["pdf.unnamed"]
    data = sheetpdf.render(cards, WORDS, "book")
    assert data.startswith(b"%PDF")


def test_pdf_from_a_rulebook_page(site: Site) -> None:
    book = import_pack(site, "tests/fixtures/rulepack_single.json")
    r = site.client().post(
        f"/api/books/{book}/pdf", json={"sheets": sheets_with_code(), "lang": "en"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
