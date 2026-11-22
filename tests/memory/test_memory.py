import sqlalchemy as sa

from smartkeeper.contracts import MemoryEntry
from smartkeeper.memory import SqlMemoryStore


def e(
    ents: tuple[str, ...], feats: tuple[str, ...] = (), text: str = "x", seq: int = 1
) -> MemoryEntry:
    return MemoryEntry(
        game_id="g", round_no=1, entities=ents, features=feats, text=text, source_seq=seq
    )


def test_recall_by_entities_not_keywords() -> None:
    m = SqlMemoryStore(sa.create_engine("sqlite://"))
    m.add(
        [
            e(("a", "b"), text="A slapped B"),
            e(("a",), ("bldg_1",), text="A entered the tower"),
            e(("c", "d"), text="C met D"),
            e(("a",), text="A slept"),
        ]
    )
    got = [x.text for x in m.recall("g", ["a", "b", "x"], ["a"], ["bldg_1"])]
    assert got == ["A slapped B", "A entered the tower"]
    assert m.recall("other", ["a", "b"], [], []) == []
    m.clear("g")
    assert m.all("g") == []
