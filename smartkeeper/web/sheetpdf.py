# pyright: reportUnknownMemberType=false
# （reportlab 的类型标注不全：参数是 Unknown 的方法一律报错，这个文件里关掉这一项）
"""角色卡导出成 PDF：给人读的，一张卡一页起（长了自动换页）。

只放人读得懂的东西：名字、身份信息、数值（带单位、可选值的名字）、各段文字、各分组的条目（名字、列、说明、用法的说明）。
技能设置、脚本、常驻加成、公式这些代码一律不放。界面文字取自前端的翻译表（web/messages.py）。

分两步：build_cards 把角色卡整理成要印的内容（纯数据，好测），render 用 reportlab 排版成 PDF。
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from xml.sax.saxutils import escape

from pydantic import JsonValue

from smartkeeper.contracts import IntelValue, RulePack, Rules, ValidationFailed

# ---------------- 要印的内容 ----------------


@dataclass
class Use:
    name: str
    text: str = ""
    effects: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])


@dataclass
class Entry:
    name: str
    tags: list[str] = field(default_factory=list[str])  # 列的值，例如“等级 A”“＋ 1”
    text: str = ""
    # 技能设置、脚本、常驻加成写成的句子（缩进层级, 句子）：自己写的和改过的条目才有
    effects: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    uses: list[Use] = field(default_factory=list[Use])


@dataclass
class Section:
    title: str
    own: list[Entry] = field(default_factory=list[Entry])  # 自己写的
    auto: list[Entry] = field(default_factory=list[Entry])  # 规则书按卡上填的自动给的


@dataclass
class Card:
    name: str
    kind: str  # 模板的显示名，例如“调查员”
    facts: list[tuple[str, str]] = field(
        default_factory=list[tuple[str, str]]
    )  # 短的：出身、是否……
    numbers: list[tuple[str, str]] = field(
        default_factory=list[tuple[str, str]]
    )  # 数值和算出来的数
    texts: list[tuple[str, str]] = field(
        default_factory=list[tuple[str, str]]
    )  # 长的：外观、来历……
    sections: list[Section] = field(default_factory=list[Section])


_REF = re.compile(r"\[\[([^\[\]]+)\]\]")
_SHORT = 24  # 不超过这么多字、没有换行的文字算“短的”，放进身份信息表


def plain(text: str) -> str:
    """说明里的标记去掉：[[规则书的一节]] 只留名字，**加粗**、`代码` 的符号去掉。"""
    text = _REF.sub(lambda m: m.group(1), text)
    return text.replace("**", "").replace("`", "").strip()


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _shown(v: IntelValue, unit: str | None, words: Mapping[str, str]) -> str:
    if v.shown:
        return v.shown
    if isinstance(v.value, bool):
        return words["pdf.yes"] if v.value else words["pdf.no"]
    if isinstance(v.value, int | float):
        return _num(v.value) + (f" {unit}" if unit else "")
    return "" if v.value is None else str(v.value)


def _choice(choices: Sequence[str], v: float) -> str | None:
    """可选值里这个数的名字（例如 A=5 里的 A）；没有名字是 None。"""
    for c in choices:
        name, sep, num = c.partition("=")
        if not sep:
            continue
        try:
            if abs(float(num) - v) < 1e-9:
                return name.strip()
        except ValueError:
            continue
    return None


def _zero(v: Any) -> bool:
    return v is None or v is False or v == 0 or v == ""


def _constant(formula: str) -> float | None:
    try:
        return float(formula.strip())
    except ValueError:
        return None


def _obj(v: Any) -> dict[str, Any]:
    return cast(dict[str, Any], v) if isinstance(v, dict) else {}


def _list(v: Any) -> list[Any]:
    return cast(list[Any], v) if isinstance(v, list) else []


def _explain(
    rules: Rules,
    pack: RulePack,
    template: str,
    group: str,
    entry: dict[str, Any],
    words: Mapping[str, str],
    on: bool,
) -> list[tuple[int, str]]:
    if not on:
        return []
    lines = rules.explain(pack, template, group, cast(JsonValue, entry), words)
    return [(ln.depth, ln.text) for ln in lines]


def build_cards(
    rules: Rules,
    pack: RulePack,
    subs: Sequence[tuple[str, JsonValue]],
    clock: Mapping[str, JsonValue | None],
    words: Mapping[str, str],
) -> list[Card]:
    """subs：(模板名, 角色卡)。没填完的卡也照样印：算不出来的数不印。
    字段印的是卡上填的值；算出来的数印的是现在的值（含常驻加成）。"""
    cards: list[Card] = []
    for template, raw in subs:
        tpl = pack.template(template)
        if tpl is None:
            continue
        peers = dict(clock)
        try:
            sheet = rules.init_sheet(pack, template, raw, peers)
        except ValidationFailed:
            sheet = raw
        full = _obj(rules.full_sheet(pack, template, sheet, peers))
        fields = _obj(full.get("fields"))
        card = Card(
            name=str(full.get("name") or "") or words["pdf.unnamed"], kind=tpl.label or tpl.name
        )
        for f in tpl.fields:
            raw_v = fields.get(f.name)
            # 选填、没填（或是 0、否）的不印
            if f.cls != "player" or f.hidden or (not f.required and _zero(raw_v)):
                continue
            label = f.label or f.name
            if f.kind == "text":
                text = plain(str(raw_v or ""))
                if not text:
                    continue
                if f.choices or (len(text) <= _SHORT and chr(10) not in text):
                    card.facts.append((label, text))
                else:
                    card.texts.append((label, text))
            elif f.kind == "boolean":
                card.facts.append((label, words["pdf.yes"] if raw_v is True else words["pdf.no"]))
            elif f.kind == "number" and isinstance(raw_v, int | float):
                unit = f" {f.unit}" if f.unit else ""
                card.numbers.append((label, _choice(f.choices, raw_v) or _num(raw_v) + unit))
        # 算出来的数：写死的系数（公式就是一个数、也没被改过）不印
        derived = [d for d in tpl.derived if not d.hidden]
        try:
            values = {
                v.name: v
                for v in rules.describe(
                    pack, template, sheet, tuple(d.name for d in derived), peers
                )
            }
        except ValidationFailed:
            values = {}
        for d in derived:
            v = values.get(d.name)
            if v is None:
                continue
            const = _constant(d.formula)
            if (
                const is not None
                and isinstance(v.value, int | float)
                and abs(v.value - const) < 1e-9
            ):
                continue
            card.numbers.append((d.label or d.name, _shown(v, d.unit, words)))

        groups = _obj(full.get("groups"))
        edited = _obj(_obj(raw).get("preset_edits"))
        own_names = {
            str(_obj(e).get("name"))
            for es in _obj(_obj(raw).get("groups")).values()
            for e in _list(es)
        }
        for g in tpl.groups:
            if g.hidden:
                continue
            entries = [_obj(e) for e in _list(groups.get(g.name)) if str(_obj(e).get("name") or "")]
            if not entries:
                continue
            optional = {c.name for c in g.fields if not c.required}
            try:
                tags = {
                    name: [
                        f"{v.label} {_shown(v, None, words)}"
                        for v in vals
                        if not (v.name in optional and _zero(v.value))
                    ]
                    for name, vals in rules.describe_entries(pack, template, sheet, g.name, peers)
                }
            except ValidationFailed:
                tags = {}
            sec = Section(title=g.label or g.name)
            for e in entries:
                name = str(e.get("name"))
                # 自己写的、改过的条目：把设置和脚本写成句子（规则书原样给的条目，说明已经写清楚了）
                explained = name in own_names or name in _obj(edited.get(g.name))
                uses = [
                    Use(
                        name=str(_obj(u).get("name")),
                        text=plain(str(_obj(u).get("description") or "")),
                        effects=_explain(rules, pack, template, g.name, u, words, explained),
                    )
                    for u in _list(e.get("uses"))
                    if str(_obj(u).get("name") or "")
                ]
                item = Entry(
                    name=name,
                    tags=tags.get(name, []),
                    text=plain(str(e.get("description") or "")),
                    effects=_explain(rules, pack, template, g.name, e, words, explained),
                    uses=uses,
                )
                (sec.own if name in own_names else sec.auto).append(item)
            card.sections.append(sec)
        cards.append(card)
    return cards


# ---------------- 排版 ----------------

# 找得到就嵌入的中文字体（regular, bold）；都没有时用 PDF 阅读器自带的宋体（不嵌入）
_FONT_FILES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
    (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ),
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
)
_fonts: tuple[str, str] | None = None


def _register_fonts() -> tuple[str, str]:
    global _fonts
    if _fonts is not None:
        return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    env = os.environ.get("SMARTKEEPER_PDF_FONT")
    candidates = ([(env, env)] if env else []) + list(_FONT_FILES)
    for regular, bold in candidates:
        if not (Path(regular).is_file() and Path(bold).is_file()):
            continue
        try:
            pdfmetrics.registerFont(TTFont("SK", regular, subfontIndex=0))
            pdfmetrics.registerFont(TTFont("SK-Bold", bold, subfontIndex=0))
        except Exception:  # 字体格式 reportlab 读不了（例如 PostScript 轮廓）：试下一个
            continue
        pdfmetrics.registerFontFamily(
            "SK", normal="SK", bold="SK-Bold", italic="SK", boldItalic="SK-Bold"
        )
        _fonts = ("SK", "SK-Bold")
        return _fonts
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _fonts = ("STSong-Light", "STSong-Light")
    return _fonts


INK = "#1d1d1f"
MUTED = "#6b6b70"
ACCENT = "#1f5fbf"
LINE = "#d9d4c7"
PANEL = "#f4f1ea"


def _p(text: str) -> str:
    return escape(text).replace("\n", "<br/>")


def render(cards: Sequence[Card], words: Mapping[str, str], book: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import (
        CondPageBreak,
        Flowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    regular, bold = _register_fonts()

    def style(name: str, **kw: Any) -> ParagraphStyle:
        base: dict[str, Any] = {
            "fontName": regular,
            "fontSize": 9.5,
            "leading": 14,
            "textColor": colors.HexColor(INK),
            "wordWrap": "CJK",
        }
        return ParagraphStyle(name, **(base | kw))

    title = style("title", fontName=bold, fontSize=20, leading=26)
    sub = style("sub", fontSize=9, textColor=colors.HexColor(MUTED), spaceAfter=8)
    h2 = style("h2", fontName=bold, fontSize=12, leading=16, textColor=colors.HexColor(ACCENT))
    label = style("label", fontSize=7.5, leading=10, textColor=colors.HexColor(MUTED))
    value = style("value", fontName=bold, fontSize=10.5, leading=14)
    body = style("body")
    name_s = style("name", fontName=bold, fontSize=10.5, leading=15)
    small = style("small", fontSize=8.5, leading=12)
    use_s = style("use", fontSize=9, leading=13, leftIndent=10)
    effect_s = style("effect", fontSize=8.5, leading=12, textColor=colors.HexColor(MUTED))

    page_w, _page_h = A4
    margin = 16 * mm
    width = page_w - 2 * margin

    def heading(text: str) -> list[Flowable]:
        rule = Table([[""]], colWidths=[width], rowHeights=[2])
        rule.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, colors.HexColor(ACCENT))]))
        return [CondPageBreak(30 * mm), Spacer(1, 8), Paragraph(_p(text), h2), rule, Spacer(1, 5)]

    def grid(pairs: Sequence[tuple[str, str]], cols: int) -> Table:
        """一格一个数：上面小字是名字，下面是值。"""
        cells: list[list[Any]] = []
        row: list[Any] = []
        for k, v in pairs:
            row.append([Paragraph(_p(k), label), Paragraph(_p(v), value)])
            if len(row) == cols:
                cells.append(row)
                row = []
        if row:
            cells.append(row + [""] * (cols - len(row)))
        t = Table(cells, colWidths=[width / cols] * cols)
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
                    ("INNERGRID", (0, 0), (-1, -1), 2, colors.white),
                    ("BOX", (0, 0), (-1, -1), 2, colors.white),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return t

    def facts_table(pairs: Sequence[tuple[str, str]]) -> Table:
        """短的身份信息：两组一行，名字灰色在左。"""
        rows: list[list[Any]] = []
        for i in range(0, len(pairs), 2):
            row: list[Any] = []
            for k, v in pairs[i : i + 2]:
                row += [Paragraph(_p(k), label), Paragraph(_p(v), body)]
            rows.append(row + [""] * (4 - len(row)))
        t = Table(rows, colWidths=[width * 0.14, width * 0.36] * 2)
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return t

    def effect_lines(lines: Sequence[tuple[int, str]], base: int) -> list[Flowable]:
        """效果：小一号的灰字，前面一个“效果”小标签；如果……下面的缩进。"""
        out: list[Flowable] = []
        for i, (depth, text) in enumerate(lines):
            tag = f'<font color="{ACCENT}">{_p(words["pdf.effects"])}</font>　' if i == 0 else ""
            indent = 10 * (base + 1) + 12 * depth
            st = ParagraphStyle(f"eff{indent}", parent=effect_s, leftIndent=indent)
            out.append(Paragraph(tag + _p(text), st))
        return out

    def entry(e: Entry) -> Flowable:
        head = f"<b>{_p(e.name)}</b>"
        if e.tags:
            head += f'  <font size="8.5" color="{MUTED}">{_p(" · ".join(e.tags))}</font>'
        parts: list[Flowable] = [Paragraph(head, name_s)]
        if e.text:
            parts.append(Paragraph(_p(e.text), body))
        parts += effect_lines(e.effects, 0)
        for u in e.uses:
            line = f"• <b>{_p(u.name)}</b>" + (f"：{_p(u.text)}" if u.text else "")
            parts.append(Paragraph(line, use_s))
            parts += effect_lines(u.effects, 1)
        parts.append(Spacer(1, 7))
        return KeepTogether(parts)

    def auto_entry(e: Entry) -> Flowable:
        line = f"<b>{_p(e.name)}</b>"
        if e.tags:
            line += f'  <font color="{MUTED}">{_p(" · ".join(e.tags))}</font>'
        if e.text:
            line += f"　{_p(e.text)}"
        return Paragraph(line, small)

    story: list[Flowable] = []
    for i, c in enumerate(cards):
        if i:
            story.append(PageBreak())
        story.append(Paragraph(_p(c.name), title))
        story.append(Paragraph(_p(f"{c.kind} · {book}" if book else c.kind), sub))
        if c.facts:
            story.append(facts_table(c.facts))
        if c.numbers:
            story += heading(words["pdf.numbers"])
            story.append(grid(c.numbers, 5))
        for k, v in c.texts:
            story += heading(k)
            story.append(Paragraph(_p(v), body))
        for sec in c.sections:
            story += heading(sec.title)
            story += [entry(e) for e in sec.own]
            if sec.auto:
                if sec.own:
                    story.append(Spacer(1, 2))
                # 小标题和第一条放在一起，别把小标题留在上一页的最底下
                first = [Paragraph(_p(words["pdf.auto"]), label), Spacer(1, 2)]
                story.append(KeepTogether([*first, auto_entry(sec.auto[0])]))
                story += [auto_entry(e) for e in sec.auto[1:]]
                story.append(Spacer(1, 4))

    def footer(canvas: Canvas, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor(MUTED))
        text = words["pdf.page"].replace("{n}", str(doc.page))
        canvas.drawCentredString(page_w / 2, 9 * mm, f"{book} · {text}" if book else text)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=" / ".join(c.name for c in cards),
        author=book,
    )
    doc.build(story or [Spacer(1, 1)], onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def words_for(messages: Mapping[str, Mapping[str, str]], lang: str) -> dict[str, str]:
    """PDF 上用到的界面文字（翻译表找不到时用键本身）。"""
    table = messages.get(lang) or messages.get("zh") or {}
    keys = (
        "pdf.yes",
        "pdf.no",
        "pdf.numbers",
        "pdf.auto",
        "pdf.page",
        "pdf.unnamed",
        "pdf.effects",
    )
    # 技能效果的字句（ex.*）也在里面，一起交给 rules.explain
    return {k: table.get(k, k) for k in keys} | {
        k: v for k, v in table.items() if k.startswith("ex.")
    }


def export(
    rules: Rules,
    pack: RulePack,
    subs: Sequence[tuple[str, JsonValue]],
    clock: Mapping[str, JsonValue | None],
    messages: Mapping[str, Mapping[str, str]],
    lang: str,
) -> bytes:
    words = words_for(messages, lang)
    return render(build_cards(rules, pack, subs, clock, words), words, pack.world.name)
