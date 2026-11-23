"""In-memory entity store for the simplified Onix NIB.

The original Onix NIB is a distributed, strongly consistent data store.
This class is the educational subset: one process, dictionaries, and a
mutex. All graph mutations happen here so topology and the public API
stay thin.

Locking rule: mutate under ``_lock``, collect ``Event`` objects, then
publish *after* the lock is released. That matches the paper's idea that
applications observe committed NIB state, not in-progress writes.
"""

from __future__ import annotations

import threading
from typing import Any

from nib.entity import Entity, Link, Port, Switch
from nib.events import Event, EventBus, EventType, utc_now


class NIBError(Exception):
    """Base class for NIB store errors."""


class EntityNotFoundError(NIBError):
    """Raised when an entity ID is not in the store."""


class DuplicateEntityError(NIBError):
    """Raised when creating an entity with an ID that already exists."""


class ValidationError(NIBError):
    """Raised when a create/update/delete would break graph invariants."""


class NIBStore:
    """Dictionary-backed store for switches, ports, and links."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or EventBus()
        self._lock = threading.RLock()
        self._switches: dict[str, Switch] = {}
        self._ports: dict[str, Port] = {}
        self._links: dict[str, Link] = {}

    @property
    def event_bus(self) -> EventBus:
        """Event bus used by this store."""
        return self._event_bus

    def _all_ids(self) -> set[str]:
        return set(self._switches) | set(self._ports) | set(self._links)

    def _require_unique_id(self, entity_id: str) -> None:
        if entity_id in self._all_ids():
            raise DuplicateEntityError(f"Entity ID already exists: {entity_id}")

    def _get_locked(self, entity_id: str) -> Entity:
        if entity_id in self._switches:
            return self._switches[entity_id]
        if entity_id in self._ports:
            return self._ports[entity_id]
        if entity_id in self._links:
            return self._links[entity_id]
        raise EntityNotFoundError(f"No entity with ID {entity_id}")

    def create_switch(
        self,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Switch:
        """Create a switch and emit ``ENTITY_CREATED``."""
        events: list[Event] = []
        with self._lock:
            switch = Switch(entity_id=entity_id, attributes=attributes)
            self._require_unique_id(switch.entity_id)
            self._switches[switch.entity_id] = switch
            events.append(
                Event(
                    event_type=EventType.ENTITY_CREATED,
                    entity_id=switch.entity_id,
                    entity_type=switch.entity_type,
                    timestamp=utc_now(),
                    info={"entity": switch.snapshot()},
                )
            )
            snapshot = switch.snapshot()
        self._event_bus.publish_all(events)
        return Switch(
            entity_id=snapshot["id"],
            attributes=snapshot["attributes"],
            port_ids=snapshot["port_ids"],
        )

    def create_port(
        self,
        switch_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Port:
        """Create a port on an existing switch and emit ``ENTITY_CREATED``."""
        events: list[Event] = []
        with self._lock:
            if switch_id not in self._switches:
                raise EntityNotFoundError(
                    f"Cannot create port: switch {switch_id} does not exist"
                )
            port = Port(switch_id=switch_id, entity_id=entity_id, attributes=attributes)
            self._require_unique_id(port.entity_id)
            self._ports[port.entity_id] = port
            self._switches[switch_id].port_ids.append(port.entity_id)
            events.append(
                Event(
                    event_type=EventType.ENTITY_CREATED,
                    entity_id=port.entity_id,
                    entity_type=port.entity_type,
                    timestamp=utc_now(),
                    info={"entity": port.snapshot()},
                )
            )
            snapshot = port.snapshot()
        self._event_bus.publish_all(events)
        return Port(
            switch_id=snapshot["switch_id"],
            entity_id=snapshot["id"],
            attributes=snapshot["attributes"],
            link_id=snapshot["link_id"],
        )

    def create_link(
        self,
        port_a_id: str,
        port_b_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Link:
        """Connect two distinct unused ports with a link."""
        events: list[Event] = []
        with self._lock:
            if port_a_id == port_b_id:
                raise ValidationError("A link cannot connect a port to itself")
            if port_a_id not in self._ports:
                raise EntityNotFoundError(
                    f"Cannot create link: port {port_a_id} does not exist"
                )
            if port_b_id not in self._ports:
                raise EntityNotFoundError(
                    f"Cannot create link: port {port_b_id} does not exist"
                )
            port_a = self._ports[port_a_id]
            port_b = self._ports[port_b_id]
            if port_a.link_id is not None:
                raise ValidationError(
                    f"Port {port_a_id} is already connected to link {port_a.link_id}"
                )
            if port_b.link_id is not None:
                raise ValidationError(
                    f"Port {port_b_id} is already connected to link {port_b.link_id}"
                )
            link = Link(
                port_a_id=port_a_id,
                port_b_id=port_b_id,
                entity_id=entity_id,
                attributes=attributes,
            )
            self._require_unique_id(link.entity_id)
            self._links[link.entity_id] = link
            port_a.link_id = link.entity_id
            port_b.link_id = link.entity_id
            events.append(
                Event(
                    event_type=EventType.ENTITY_CREATED,
                    entity_id=link.entity_id,
                    entity_type=link.entity_type,
                    timestamp=utc_now(),
                    info={"entity": link.snapshot()},
                )
            )
            snapshot = link.snapshot()
        self._event_bus.publish_all(events)
        return Link(
            port_a_id=snapshot["port_a_id"],
            port_b_id=snapshot["port_b_id"],
            entity_id=snapshot["id"],
            attributes=snapshot["attributes"],
        )

    def get(self, entity_id: str) -> dict[str, Any]:
        """Return a detached snapshot of an entity by ID."""
        with self._lock:
            return self._get_locked(entity_id).snapshot()

    def list_by_type(self, entity_type: str) -> list[dict[str, Any]]:
        """List detached snapshots of all entities of ``entity_type``."""
        with self._lock:
            if entity_type == "switch":
                return [s.snapshot() for s in self._switches.values()]
            if entity_type == "port":
                return [p.snapshot() for p in self._ports.values()]
            if entity_type == "link":
                return [link.snapshot() for link in self._links.values()]
            raise ValidationError(f"Unknown entity type: {entity_type}")

    def set_attr(self, entity_id: str, key: str, value: Any) -> None:
        """Set one attribute and emit ``ATTRIBUTE_CHANGED``."""
        events: list[Event] = []
        with self._lock:
            entity = self._get_locked(entity_id)
            old_value = entity.attributes.get(key)
            entity.attributes[key] = value
            events.append(
                Event(
                    event_type=EventType.ATTRIBUTE_CHANGED,
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    timestamp=utc_now(),
                    info={"key": key, "old_value": old_value, "new_value": value},
                )
            )
        self._event_bus.publish_all(events)

    def get_attr(self, entity_id: str, key: str) -> Any:
        """Return one attribute value, or raise ``KeyError`` if missing."""
        with self._lock:
            entity = self._get_locked(entity_id)
            if key not in entity.attributes:
                raise KeyError(f"Attribute {key!r} not set on entity {entity_id}")
            return entity.attributes[key]

    def get_attrs(self, entity_id: str) -> dict[str, Any]:
        """Return a copy of all attributes for an entity."""
        with self._lock:
            return dict(self._get_locked(entity_id).attributes)

    def delete(self, entity_id: str) -> None:
        """Delete an entity. Switches and ports cascade as documented."""
        events: list[Event] = []
        with self._lock:
            if entity_id in self._switches:
                events.extend(self._delete_switch_locked(entity_id))
            elif entity_id in self._ports:
                events.extend(self._delete_port_locked(entity_id))
            elif entity_id in self._links:
                events.extend(self._delete_link_locked(entity_id))
            else:
                raise EntityNotFoundError(f"No entity with ID {entity_id}")
        self._event_bus.publish_all(events)

    def _deleted_event(self, entity: Entity, reason: str) -> Event:
        return Event(
            event_type=EventType.ENTITY_DELETED,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            timestamp=utc_now(),
            info={"reason": reason, "entity": entity.snapshot()},
        )

    def _delete_link_locked(self, link_id: str, reason: str = "deleted") -> list[Event]:
        link = self._links.get(link_id)
        if link is None:
            return []
        for port_id in (link.port_a_id, link.port_b_id):
            port = self._ports.get(port_id)
            if port is not None and port.link_id == link_id:
                port.link_id = None
        del self._links[link_id]
        return [self._deleted_event(link, reason)]

    def _delete_port_locked(self, port_id: str, reason: str = "deleted") -> list[Event]:
        port = self._ports.get(port_id)
        if port is None:
            return []
        events: list[Event] = []
        if port.link_id is not None:
            events.extend(
                self._delete_link_locked(port.link_id, reason="cascade: port deleted")
            )
        switch = self._switches.get(port.switch_id)
        if switch is not None and port_id in switch.port_ids:
            switch.port_ids.remove(port_id)
        del self._ports[port_id]
        events.append(self._deleted_event(port, reason))
        return events

    def _delete_switch_locked(self, switch_id: str) -> list[Event]:
        switch = self._switches[switch_id]
        events: list[Event] = []
        # Copy because _delete_port_locked mutates switch.port_ids.
        for port_id in list(switch.port_ids):
            events.extend(
                self._delete_port_locked(port_id, reason="cascade: switch deleted")
            )
        del self._switches[switch_id]
        events.append(self._deleted_event(switch, "deleted"))
        return events

    def copy_graph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Return detached snapshots of all switches, ports, and links."""
        with self._lock:
            switches = [s.snapshot() for s in self._switches.values()]
            ports = [p.snapshot() for p in self._ports.values()]
            links = [link.snapshot() for link in self._links.values()]
        return switches, ports, links
