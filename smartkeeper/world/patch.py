"""RFC 6902 JSON Patch。纯函数：输入不变，返回新文档。"""

from __future__ import annotations

import copy
from collections.abc import Sequence

from pydantic import JsonValue

from smartkeeper.contracts import PatchOp


class PatchError(Exception):
    def __init__(self, code: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


def parse_pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError("patch.bad_pointer", path)
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def _index(container: list[JsonValue], token: str, path: str, *, allow_end: bool) -> int:
    if token == "-" and allow_end:
        return len(container)
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        raise PatchError("patch.bad_index", path)
    i = int(token)
    if i > len(container) or (i == len(container) and not allow_end):
        raise PatchError("patch.index_out_of_range", path)
    return i


def _parent(doc: JsonValue, tokens: list[str], path: str) -> tuple[JsonValue, str]:
    if not tokens:
        raise PatchError("patch.root_not_allowed", path)
    cur = doc
    for t in tokens[:-1]:
        if isinstance(cur, dict):
            if t not in cur:
                raise PatchError("patch.path_not_found", path)
            cur = cur[t]
        elif isinstance(cur, list):
            cur = cur[_index(cur, t, path, allow_end=False)]
        else:
            raise PatchError("patch.path_not_found", path)
    return cur, tokens[-1]


def get(doc: JsonValue, path: str) -> JsonValue:
    cur = doc
    for t in parse_pointer(path):
        if isinstance(cur, dict):
            if t not in cur:
                raise PatchError("patch.path_not_found", path)
            cur = cur[t]
        elif isinstance(cur, list):
            cur = cur[_index(cur, t, path, allow_end=False)]
        else:
            raise PatchError("patch.path_not_found", path)
    return cur


def _add(doc: JsonValue, path: str, value: JsonValue) -> None:
    parent, last = _parent(doc, parse_pointer(path), path)
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list):
        parent.insert(_index(parent, last, path, allow_end=True), value)
    else:
        raise PatchError("patch.path_not_found", path)


def _remove(doc: JsonValue, path: str) -> JsonValue:
    parent, last = _parent(doc, parse_pointer(path), path)
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError("patch.path_not_found", path)
        return parent.pop(last)
    if isinstance(parent, list):
        return parent.pop(_index(parent, last, path, allow_end=False))
    raise PatchError("patch.path_not_found", path)


def apply_patch(doc: JsonValue, ops: Sequence[PatchOp]) -> JsonValue:
    out = copy.deepcopy(doc)
    for op in ops:
        value = copy.deepcopy(op.value)
        if op.op == "add":
            _add(out, op.path, value)
        elif op.op == "remove":
            _remove(out, op.path)
        elif op.op == "replace":
            _remove(out, op.path)
            _add(out, op.path, value)
        elif op.op in ("move", "copy"):
            if op.from_ is None:
                raise PatchError("patch.missing_from", op.path)
            if op.op == "move":
                if op.path.startswith(op.from_ + "/"):
                    raise PatchError("patch.move_into_child", op.path)
                moved = _remove(out, op.from_)
            else:
                moved = copy.deepcopy(get(out, op.from_))
            _add(out, op.path, moved)
        else:  # test
            if get(out, op.path) != value:
                raise PatchError("patch.test_failed", op.path)
    return out
