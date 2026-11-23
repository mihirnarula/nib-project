"""Tests for topology snapshots, adjacency, and neighbor queries."""

from nib.api import NIB
from nib.store import EntityNotFoundError
import pytest


def test_empty_topology():
    nib = NIB()
    topo = nib.query_topology()
    assert topo["switches"] == []
    assert topo["ports"] == []
    assert topo["links"] == []
    assert topo["adjacency"] == {}


def test_one_isolated_switch():
    nib = NIB()
    s = nib.create_switch(entity_id="only")
    topo = nib.query_topology()
    assert len(topo["switches"]) == 1
    assert topo["switches"][0]["id"] == "only"
    assert topo["ports"] == []
    assert topo["links"] == []
    assert topo["adjacency"] == {"only": []}
    assert nib.neighbors(s.entity_id) == []


def test_two_connected_switches_adjacency():
    nib = NIB()
    s1 = nib.create_switch(entity_id="s1")
    s2 = nib.create_switch(entity_id="s2")
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    nib.create_link(p1.entity_id, p2.entity_id)

    topo = nib.query_topology()
    assert {s["id"] for s in topo["switches"]} == {"s1", "s2"}
    assert len(topo["ports"]) == 2
    assert len(topo["links"]) == 1
    assert topo["adjacency"]["s1"] == ["s2"]
    assert topo["adjacency"]["s2"] == ["s1"]
    assert nib.neighbors("s1") == ["s2"]
    assert nib.neighbors("s2") == ["s1"]
    assert nib.are_connected("s1", "s2") is True


def test_snapshot_is_detached_from_store():
    nib = NIB()
    nib.create_switch(entity_id="s1", attributes={"name": "a"})
    topo = nib.query_topology()
    topo["switches"][0]["attributes"]["name"] = "changed"
    topo["adjacency"]["s1"].append("fake")
    assert nib.get("s1")["attributes"]["name"] == "a"
    assert nib.neighbors("s1") == []


def test_three_switches_linear_neighbors():
    nib = NIB()
    a = nib.create_switch(entity_id="a")
    b = nib.create_switch(entity_id="b")
    c = nib.create_switch(entity_id="c")
    pa = nib.create_port(a.entity_id)
    pb1 = nib.create_port(b.entity_id)
    pb2 = nib.create_port(b.entity_id)
    pc = nib.create_port(c.entity_id)
    nib.create_link(pa.entity_id, pb1.entity_id)
    nib.create_link(pb2.entity_id, pc.entity_id)

    assert set(nib.neighbors("b")) == {"a", "c"}
    assert nib.are_connected("a", "c") is False
    assert nib.are_connected("a", "b") is True


def test_neighbors_unknown_switch():
    nib = NIB()
    with pytest.raises(EntityNotFoundError):
        nib.neighbors("missing")
