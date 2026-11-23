"""Tests for NIB event publication, filtering, and isolation of callbacks."""

from nib.api import NIB
from nib.events import EventType


def test_entity_created_events():
    nib = NIB()
    received = []
    nib.subscribe(received.append, event_type=EventType.ENTITY_CREATED)

    s = nib.create_switch()
    p = nib.create_port(s.entity_id)
    types = [e.entity_type for e in received]
    ids = [e.entity_id for e in received]
    assert types == ["switch", "port"]
    assert ids == [s.entity_id, p.entity_id]


def test_attribute_changed_event():
    nib = NIB()
    link_events = []
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1.entity_id, p2.entity_id, attributes={"status": "UP"})
    nib.subscribe(link_events.append, event_type=EventType.ATTRIBUTE_CHANGED)

    nib.set_attr(link.entity_id, "status", "DOWN")
    assert len(link_events) == 1
    event = link_events[0]
    assert event.entity_id == link.entity_id
    assert event.info["key"] == "status"
    assert event.info["old_value"] == "UP"
    assert event.info["new_value"] == "DOWN"


def test_entity_deleted_event():
    nib = NIB()
    deleted = []
    s = nib.create_switch()
    nib.subscribe(deleted.append, event_type=EventType.ENTITY_DELETED)
    nib.delete(s.entity_id)
    assert len(deleted) == 1
    assert deleted[0].entity_id == s.entity_id
    assert deleted[0].entity_type == "switch"


def test_event_filtering_by_entity_type_and_id():
    nib = NIB()
    port_events = []
    one_entity = []
    s = nib.create_switch()
    p = nib.create_port(s.entity_id)
    nib.subscribe(port_events.append, entity_type="port")
    nib.subscribe(one_entity.append, entity_id=s.entity_id)

    nib.set_attr(p.entity_id, "speed", "1G")
    nib.set_attr(s.entity_id, "name", "core")

    assert len(port_events) == 1
    assert port_events[0].entity_id == p.entity_id
    assert len(one_entity) == 1
    assert one_entity[0].entity_id == s.entity_id
    assert one_entity[0].info["key"] == "name"


def test_unsubscribe_stops_delivery():
    nib = NIB()
    received = []
    sub_id = nib.subscribe(received.append)
    s = nib.create_switch()
    assert len(received) == 1
    assert nib.unsubscribe(sub_id) is True
    nib.delete(s.entity_id)
    assert len(received) == 1
    assert nib.unsubscribe(sub_id) is False


def test_cascade_deletion_emits_event_per_entity():
    nib = NIB()
    s1 = nib.create_switch()
    s2 = nib.create_switch()
    p1 = nib.create_port(s1.entity_id)
    p2 = nib.create_port(s2.entity_id)
    link = nib.create_link(p1.entity_id, p2.entity_id)

    deleted = []
    nib.subscribe(deleted.append, event_type=EventType.ENTITY_DELETED)
    nib.delete(s1.entity_id)

    deleted_ids = {e.entity_id for e in deleted}
    assert deleted_ids == {link.entity_id, p1.entity_id, s1.entity_id}
    # Link first, then port, then switch.
    assert [e.entity_type for e in deleted] == ["link", "port", "switch"]


def test_callback_exception_does_not_stop_others():
    nib = NIB()
    seen = []

    def boom(_event):
        raise RuntimeError("subscriber failed")

    def ok(event):
        seen.append(event.entity_id)

    nib.subscribe(boom)
    nib.subscribe(ok)
    switch = nib.create_switch()
    assert seen == [switch.entity_id]


def test_callbacks_see_committed_state():
    """Callbacks must run after the store mutation is visible."""
    nib = NIB()
    observed = {}

    def on_create(event):
        observed["snap"] = nib.get(event.entity_id)

    nib.subscribe(on_create, event_type=EventType.ENTITY_CREATED)
    s = nib.create_switch(attributes={"ok": True})
    assert observed["snap"]["id"] == s.entity_id
    assert observed["snap"]["attributes"]["ok"] is True
