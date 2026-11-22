import pytest
import sqlalchemy as sa

from smartkeeper.chat import SqlChatStore
from smartkeeper.contracts import ValidationFailed


def test_pairwise_conversations() -> None:
    s = SqlChatStore(sa.create_engine("sqlite://"))
    s.post("g", "p1", "p2", "hi")
    s.post("g", "p2", "p1", "yo")
    s.post("g", "p1", "p3", "secret")
    assert [m.text for m in s.conversation("g", "p1", "p2")] == ["hi", "yo"]
    assert [m.text for m in s.for_player("g", "p2")] == ["hi", "yo"]
    assert [m.text for m in s.for_player("g", "p3")] == ["secret"]
    with pytest.raises(ValidationFailed):
        s.post("g", "p1", "p1", "me")
