"""Tests for NIBStore entity management, attributes, and cascade deletes."""

import pytest

from nib.api import NIB
from nib.store import DuplicateEntityError, EntityNotFoundError, ValidationError


def test_create_and_retrieve_switch():
    nib = NIB()
    switch = nib.create_switch(attributes={"name": "core-1"})
    got = nib.get(switch.entity_id)
    assert got["type"] == "switch"
    assert got["id"] == switch.entity_id
    assert got["attributes"]["name"] == "core-1"
    assert nib.list_by_type("switch")[0]["id"] == switch.entity_id


def test_create_port_on_switch():
    nib = NIB()
    switch = nib.create_switch()
    port = nib.create_port(switch.entity_id, attributes={"name": "eth0"})
    assert port.switch_id == switch.entity_id
    assert port.link_id is None
    switch_snap = nib.get(switch.entity_id)
    assert port.entity_id in switch_snap["port_ids"]


def test_create_link_between_ports():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1.entity_id, p2.entity_id, attributes={"status": "UP"})
    assert nib.get(p1.entity_id)["link_id"] == link.entity_id
    assert nib.get(p2.entity_id)["link_id"] == link.entity_id
    assert nib.get_attr(link.entity_id, "status") == "UP"


def test_attribute_set_and_get():
    nib = NIB()
    switch = nib.create_switch(attributes={"role": "edge"})
    nib.set_attr(switch.entity_id, "role", "core")
    nib.set_attr(switch.entity_id, "asn", 65000)
    assert nib.get_attr(switch.entity_id, "role") == "core"
    attrs = nib.get_attrs(switch.entity_id)
    assert attrs == {"role": "core", "asn": 65000}
    attrs["role"] = "mutated"
    assert nib.get_attr(switch.entity_id, "role") == "core"


def test_get_missing_attribute_raises():
    nib = NIB()
    switch = nib.create_switch()
    with pytest.raises(KeyError):
        nib.get_attr(switch.entity_id, "missing")


def test_duplicate_id_rejected():
    nib = NIB()
    nib.create_switch(entity_id="sw1")
    with pytest.raises(DuplicateEntityError):
        nib.create_switch(entity_id="sw1")
    nib.create_port("sw1", entity_id="p1")
    with pytest.raises(DuplicateEntityError):
        nib.create_port("sw1", entity_id="p1")


def test_create_port_for_nonexistent_switch():
    nib = NIB()
    with pytest.raises(EntityNotFoundError):
        nib.create_port("no-such-switch")


def test_create_link_for_nonexistent_ports():
    nib = NIB()
    s = nib.create_switch()
    p = nib.create_port(s.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.create_link(p.entity_id, "missing-port")
    with pytest.raises(EntityNotFoundError):
        nib.create_link("missing-a", "missing-b")


def test_self_link_rejected():
    nib = NIB()
    s = nib.create_switch()
    p = nib.create_port(s.entity_id)
    with pytest.raises(ValidationError, match="itself"):
        nib.create_link(p.entity_id, p.entity_id)


def test_port_cannot_have_two_links():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    s3 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    p3 = nib.create_port(s3.entity_id)
    nib.create_link(p1.entity_id, p2.entity_id)
    with pytest.raises(ValidationError, match="already connected"):
        nib.create_link(p1.entity_id, p3.entity_id)


def test_get_unknown_entity():
    nib = NIB()
    with pytest.raises(EntityNotFoundError):
        nib.get("ghost")


def test_delete_link_clears_ports():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1.entity_id, p2.entity_id)
    nib.delete(link.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(link.entity_id)
    assert nib.get(p1.entity_id)["link_id"] is None
    assert nib.get(p2.entity_id)["link_id"] is None


def test_delete_port_deletes_its_link():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1.entity_id, p2.entity_id)
    nib.delete(p1.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(p1.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(link.entity_id)
    assert nib.get(p2.entity_id)["link_id"] is None
    assert p1.entity_id not in nib.get(s1.entity_id)["port_ids"]


def test_delete_switch_cascades_ports_and_links():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1a = nib.create_port(s1.entity_id)
    p1b = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1a.entity_id, p2.entity_id)

    nib.delete(s1.entity_id)

    with pytest.raises(EntityNotFoundError):
        nib.get(s1.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(p1a.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(p1b.entity_id)
    with pytest.raises(EntityNotFoundError):
        nib.get(link.entity_id)
    assert nib.get(s2.entity_id)["type"] == "switch"
    assert nib.get(p2.entity_id)["link_id"] is None
