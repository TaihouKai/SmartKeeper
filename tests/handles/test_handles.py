import pytest
import sqlalchemy as sa

from smartkeeper.contracts import ValidationFailed
from smartkeeper.handles import SqlHandleStore


@pytest.fixture
def store() -> SqlHandleStore:
    return SqlHandleStore(sa.create_engine("sqlite://"))


def test_independent_per_player(store: SqlHandleStore) -> None:
    a = store.ensure("p1", "npc_7")
    b = store.ensure("p2", "npc_7")
    assert a.ref != b.ref
    store.set_label("p1", "npc_7", "Blond man", by_player=False)
    store.set_label("p1", "npc_7", "Bob", by_player=True)
    assert store.get("p1", "npc_7").label == "Bob"  # type: ignore[union-attr]
    assert store.get("p2", "npc_7").label == "#1"  # type: ignore[union-attr]


def test_stable_and_unique(store: SqlHandleStore) -> None:
    h1 = store.ensure("p1", "e1")
    assert store.ensure("p1", "e1") == h1
    store.ensure("p1", "e2")
    store.set_label("p1", "e1", "Short one", by_player=False)
    h2 = store.set_label("p1", "e2", "Short one", by_player=False)
    assert h2.label == "Short one 2"
    with pytest.raises(ValidationFailed):
        store.set_label("p1", "e2", "Short one", by_player=True)
    assert store.by_ref("p1", h1.ref).entity_id == "e1"  # type: ignore[union-attr]
    assert store.by_ref("p2", h1.ref) is None


def test_auto_naming_does_not_override_player(store: SqlHandleStore) -> None:
    store.ensure("p1", "e1")
    store.set_label("p1", "e1", "My friend", by_player=True)
    h = store.set_label("p1", "e1", "Tall woman", by_player=False)
    assert h.label == "My friend"
    assert store.set_note("p1", "e1", "owes me money").note == "owes me money"
    assert [x.entity_id for x in store.list("p1")] == ["e1"]
