"""Entity model for a simplified Onix Network Information Base (NIB).

In the Onix paper, the NIB is a graph of network entities with typed
attributes. This module models the three entity kinds we care about for
an educational, single-instance NIB: switches, ports, and links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def generate_id() -> str:
    """Return a new UUID4 string for entity identifiers."""
    return str(uuid4())


@dataclass
class Entity:
    """Base network entity stored in the NIB.

    Attributes:
        entity_id: Unique identifier (UUID string).
        entity_type: Short type name such as ``switch``, ``port``, or ``link``.
        attributes: Arbitrary key-value metadata (status, capacity, etc.).
    """

    entity_id: str
    entity_type: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """Return a detached copy of this entity's public state.

        Callers must not be able to mutate the store by changing the
        returned dictionary, so attributes are copied.
        """
        return {
            "id": self.entity_id,
            "type": self.entity_type,
            "attributes": dict(self.attributes),
        }


@dataclass
class Switch(Entity):
    """A network switch that can own many ports."""

    port_ids: list[str] = field(default_factory=list)

    def __init__(
        self,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        port_ids: list[str] | None = None,
    ) -> None:
        super().__init__(
            entity_id=entity_id or generate_id(),
            entity_type="switch",
            attributes=dict(attributes or {}),
        )
        self.port_ids = list(port_ids or [])

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data["port_ids"] = list(self.port_ids)
        return data


@dataclass
class Port(Entity):
    """A switch port. Each port belongs to exactly one switch.

    A port may be attached to at most one link (``link_id`` is None
    when the port is unused).
    """

    switch_id: str = ""
    link_id: str | None = None

    def __init__(
        self,
        switch_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        link_id: str | None = None,
    ) -> None:
        super().__init__(
            entity_id=entity_id or generate_id(),
            entity_type="port",
            attributes=dict(attributes or {}),
        )
        self.switch_id = switch_id
        self.link_id = link_id

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data["switch_id"] = self.switch_id
        data["link_id"] = self.link_id
        return data


@dataclass
class Link(Entity):
    """An undirected connection between exactly two distinct ports."""

    port_a_id: str = ""
    port_b_id: str = ""

    def __init__(
        self,
        port_a_id: str,
        port_b_id: str,
        entity_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            entity_id=entity_id or generate_id(),
            entity_type="link",
            attributes=dict(attributes or {}),
        )
        self.port_a_id = port_a_id
        self.port_b_id = port_b_id

    def other_port(self, port_id: str) -> str:
        """Return the port on the opposite end of this link."""
        if port_id == self.port_a_id:
            return self.port_b_id
        if port_id == self.port_b_id:
            return self.port_a_id
        raise ValueError(f"Port {port_id!r} is not an endpoint of link {self.entity_id}")

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data["port_a_id"] = self.port_a_id
        data["port_b_id"] = self.port_b_id
        return data
