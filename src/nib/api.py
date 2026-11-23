"""Public façade for the simplified Onix NIB.

Applications talk to one ``NIB`` object instead of wiring the store,
event bus, and topology helper themselves.
"""

from __future__ import annotations

from typing import Any

from nib.entity import Link, Port, Switch
from nib.events import EventBus, EventCallback, EventType
from nib.store import NIBStore
from nib.topology import TopologyQuery


class NIB:
    """In-memory Network Information Base.

    Example:
        nib = NIB()
        s1 = nib.create_switch(attributes={"name": "s1"})
        p1 = nib.create_port(s1.entity_id)
    """

    def __init__(self) -> None:
        self._events = EventBus()
        self._store = NIBStore(self._events)
        self._topology = TopologyQuery(self._store)

    def create_switch(
        self,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Switch:
        """Create a switch. ``entity_id`` is generated if omitted."""
        return self._store.create_switch(entity_id=entity_id, attributes=attributes)

    def create_port(
        self,
        switch_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Port:
        """Create a port owned by ``switch_id``."""
        return self._store.create_port(
            switch_id=switch_id, entity_id=entity_id, attributes=attributes
        )

    def create_link(
        self,
        port_a_id: str,
        port_b_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Link:
        """Connect two distinct ports that are not already linked."""
        return self._store.create_link(
            port_a_id=port_a_id,
            port_b_id=port_b_id,
            entity_id=entity_id,
            attributes=attributes,
        )

    def get(self, entity_id: str) -> dict[str, Any]:
        """Return a snapshot of one entity."""
        return self._store.get(entity_id)

    def list_by_type(self, entity_type: str) -> list[dict[str, Any]]:
        """List snapshots of ``switch``, ``port``, or ``link`` entities."""
        return self._store.list_by_type(entity_type)

    def set_attr(self, entity_id: str, key: str, value: Any) -> None:
        """Set an attribute and notify ``ATTRIBUTE_CHANGED`` subscribers."""
        self._store.set_attr(entity_id, key, value)

    def get_attr(self, entity_id: str, key: str) -> Any:
        """Return one attribute value."""
        return self._store.get_attr(entity_id, key)

    def get_attrs(self, entity_id: str) -> dict[str, Any]:
        """Return a copy of all attributes on an entity."""
        return self._store.get_attrs(entity_id)

    def delete(self, entity_id: str) -> None:
        """Delete an entity, cascading from switches and ports as needed."""
        self._store.delete(entity_id)

    def query_topology(self) -> dict[str, Any]:
        """Return switches, ports, links, and switch adjacency."""
        return self._topology.query_topology()

    def neighbors(self, switch_id: str) -> list[str]:
        """Return IDs of switches one hop from ``switch_id``."""
        return self._topology.neighbors(switch_id)

    def are_connected(self, switch_a_id: str, switch_b_id: str) -> bool:
        """Return True if the switches are directly linked."""
        return self._topology.are_connected(switch_a_id, switch_b_id)

    def subscribe(
        self,
        callback: EventCallback,
        event_type: EventType | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> str:
        """Subscribe to NIB events. Returns an ID for ``unsubscribe``."""
        return self._events.subscribe(
            callback,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription. Returns True if it existed."""
        return self._events.unsubscribe(subscription_id)
