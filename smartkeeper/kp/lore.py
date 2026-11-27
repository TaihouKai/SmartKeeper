"""资料库：按关键词从规则包的资料库里挑出这次要给 KP 的背景设定。纯函数，由代码决定，不让模型挑。

- 关键词任一出现在扫描的文字里就算命中，再按次关键词的逻辑过滤；`/正则/` 按正则；
  英文和数字的关键词只按整词匹配（“BB”不会命中“BBQ”）；不区分大小写，除非条目要求。
- 常见词不单独触发：在超过 4% 的条目正文里出现的关键词（例如世界观里到处出现的词），只有和这条的另一个关键词一起出现才算。
- 按命中的关键词个数、条目的 order 排序，按字数预算往里放；单条过长截断。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from smartkeeper.contracts import LoreEntry

COMMON_SHARE = 0.04  # 在超过这么多比例的条目正文里出现的关键词算常见词
_LATIN = re.compile(r"[A-Za-z0-9 .'’\-]+")


@dataclass(frozen=True, slots=True)
class LoreHit:
    entry: LoreEntry
    keys: tuple[str, ...]  # 命中的关键词


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _match(key: str, text: str, case_sensitive: bool) -> bool:
    k = key.strip()
    if not k:
        return False
    rx = re.fullmatch(r"/(.+)/([a-z]*)", k, re.S)
    if rx:
        flags = re.I if "i" in rx.group(2) else 0
        try:
            return re.search(rx.group(1), text, flags) is not None
        except re.error:
            return False
    k = _norm(k)
    if _LATIN.fullmatch(k):
        pat = rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])"
        return re.search(pat, text, 0 if case_sensitive else re.I) is not None
    return k in text if case_sensitive else k.lower() in text.lower()


@lru_cache(maxsize=8)
def common_keys(lore: tuple[LoreEntry, ...]) -> frozenset[str]:
    """在超过 COMMON_SHARE 比例的条目正文里出现的关键词（至少 3 条）。"""
    live = [e for e in lore if not e.disabled]
    if not live:
        return frozenset()
    limit = max(3, COMMON_SHARE * len(live))
    bodies = [_norm(e.content).lower() for e in live]
    out: set[str] = set()
    for e in live:
        for k in e.keys:
            kk = _norm(k).lower()
            if not kk.startswith("/") and sum(1 for b in bodies if kk in b) > limit:
                out.add(k)
    return frozenset(out)


def _hit(e: LoreEntry, text: str, common: frozenset[str]) -> tuple[str, ...]:
    keys = tuple(dict.fromkeys(k for k in e.keys if _match(k, text, e.case_sensitive)))
    if not keys or (all(k in common for k in keys) and len(keys) < 2):
        return ()
    sec = [k for k in e.secondary if k.strip()]
    if sec:
        n = sum(1 for k in sec if _match(k, text, e.case_sensitive))
        ok = {
            "any": n > 0,
            "all": n == len(sec),
            "not_any": n == 0,
            "not_all": n < len(sec),
        }[e.logic]
        if not ok:
            return ()
    return keys


def pick(
    lore: Sequence[LoreEntry],
    texts: Iterable[str],
    budget: int,
    entry_chars: int = 900,
    exclude: Iterable[str] = (),
) -> list[LoreHit]:
    """扫描 texts，挑出命中的条目，按命中的关键词个数、order 排序，总字数不超过 budget。exclude 是不要的标题。"""
    pack_lore = tuple(lore)
    if not pack_lore or budget <= 0:
        return []
    text = _norm("\n".join(t for t in texts if t))
    if not text.strip():
        return []
    common = common_keys(pack_lore)
    skip = set(exclude)
    hits: list[tuple[int, int, int, LoreHit]] = []
    for i, e in enumerate(pack_lore):
        if e.disabled or e.title in skip:
            continue
        keys = _hit(e, text, common)
        if keys:
            hits.append((-len(keys), -e.order, i, LoreHit(e, keys)))
    out: list[LoreHit] = []
    used = 0
    for *_, h in sorted(hits):
        n = min(len(h.entry.content), entry_chars) + len(h.entry.title) + 8
        if used + n > budget:
            continue
        out.append(h)
        used += n
    return out


def render(hits: Sequence[LoreHit], entry_chars: int = 900) -> str:
    """挑出的条目写成上下文里的一段：每条一个小标题。"""
    parts: list[str] = []
    for h in hits:
        body = h.entry.content.strip()
        if len(body) > entry_chars:
            body = body[:entry_chars].rstrip() + "……"
        parts.append(f"### {h.entry.title}\n{body}")
    return "\n\n".join(parts)
