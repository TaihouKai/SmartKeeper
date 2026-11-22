from __future__ import annotations

import sqlalchemy as sa
from hypothesis import given, settings
from hypothesis import strategies as st

from smartkeeper.contracts import KP, PUBLIC, NewEvent, Visibility
from smartkeeper.eventlog import SqlEventLog

PLAYERS = [f"p{i}" for i in range(1, 6)] + ["p1_x", "p%"]

visibility = st.one_of(
    st.just(Visibility.public()),
    st.just(Visibility.kp_only()),
    st.lists(st.sampled_from(PLAYERS), min_size=1, max_size=3).map(lambda ps: Visibility.to(*ps)),
)
new_event = st.builds(
    lambda vis, anon: NewEvent(
        type="broadcast" if anon is not None else "pm_kp",
        actor="p1",
        visibility=vis,
        payload={"anonymous": anon} if anon is not None else {},
    ),
    visibility,
    st.one_of(st.none(), st.booleans()),
)


def log() -> SqlEventLog:
    return SqlEventLog(sa.create_engine("sqlite://"))


@settings(max_examples=60, deadline=None)
@given(st.lists(new_event, max_size=40), st.sampled_from(PLAYERS))
def test_visibility_property(events: list[NewEvent], player: str) -> None:
    lg = log()
    lg.append("g", 1, events)
    lg.append("other", 1, [NewEvent(type="pm_kp", actor=None, visibility=Visibility.public())])
    seen = lg.view_for("g", player)
    for e in seen:
        assert e.visibility.kind == "public" or (
            e.visibility.kind == "players" and player in e.visibility.players
        )
    expected = [
        ev for ev in events if ev.visibility.kind == "public" or player in ev.visibility.players
    ]
    assert len(seen) == len(expected)
    pub = lg.view_for("g", PUBLIC)
    assert all(e.visibility.kind == "public" for e in pub)
    assert len(lg.view_for("g", KP)) == len(events)


def test_seq_strictly_increasing_across_batches() -> None:
    lg = log()
    ev = NewEvent(type="pm_kp", actor=None, visibility=Visibility.kp_only())
    a = lg.append("g", 1, [ev, ev])
    b = lg.append("g", 2, [ev])
    c = lg.append("h", 1, [ev])
    assert [e.seq for e in a + b] == [1, 2, 3]
    assert c[0].seq == 1
    assert [e.seq for e in lg.view_for("g", KP, since_seq=1)] == [2, 3]
    assert [e.round_no for e in lg.view_for("g", KP, round_no=2)] == [2]


def test_anonymous_broadcast() -> None:
    lg = log()
    lg.append(
        "g",
        1,
        [
            NewEvent(
                type="broadcast",
                actor="p1",
                visibility=Visibility.public(),
                payload={"text": "hi", "anonymous": True},
            )
        ],
    )
    assert lg.view_for("g", "p2")[0].actor is None
    assert lg.view_for("g", "p1")[0].actor is None
    assert lg.view_for("g", PUBLIC)[0].actor is None
    assert lg.view_for("g", KP)[0].actor == "p1"


def test_like_wildcards_do_not_leak() -> None:
    lg = log()
    lg.append("g", 1, [NewEvent(type="pm_kp", actor=None, visibility=Visibility.to("p1"))])
    assert lg.view_for("g", "p_") == []
    assert lg.view_for("g", "%") == []
