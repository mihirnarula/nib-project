"""Event notification for NIB state changes.

Onix applications register interest in NIB updates rather than polling.
This module is a small in-process observer (EventBus): subscribers receive
copies of events after the store has finished mutating state.

Design notes:
- Subscriptions can be filtered by event type, entity type, and entity ID.
- ``publish`` copies the subscriber list, then invokes callbacks *outside*
  any lock. The store must also release its lock before publishing.
- A failing callback is logged and skipped so other listeners still run.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Kinds of NIB change notifications."""

    ENTITY_CREATED = "ENTITY_CREATED"
    ENTITY_UPDATED = "ENTITY_UPDATED"
    ATTRIBUTE_CHANGED = "ATTRIBUTE_CHANGED"
    ENTITY_DELETED = "ENTITY_DELETED"


@dataclass(frozen=True)
class Event:
    """Immutable record of a single NIB change.

    Attributes:
        event_type: What happened.
        entity_id: ID of the affected entity.
        entity_type: ``switch``, ``port``, or ``link``.
        timestamp: UTC time the event was created.
        info: Extra details (attribute key/value, cascade reason, etc.).
    """

    event_type: EventType
    entity_id: str
    entity_type: str
    timestamp: datetime
    info: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[Event], None]


@dataclass
class Subscription:
    """A registered listener plus optional filters."""

    subscription_id: str
    callback: EventCallback
    event_type: EventType | None = None
    entity_type: str | None = None
    entity_id: str | None = None

    def matches(self, event: Event) -> bool:
        """Return True if this subscription should receive ``event``."""
        if self.event_type is not None and event.event_type != self.event_type:
            return False
        if self.entity_type is not None and event.entity_type != self.entity_type:
            return False
        if self.entity_id is not None and event.entity_id != self.entity_id:
            return False
        return True


def utc_now() -> datetime:
    """Current UTC timestamp used on events."""
    return datetime.now(timezone.utc)


class EventBus:
    """Simple observer bus with optional event filters."""

    def __init__(self) -> None:
        # Protects only the subscription map. Callbacks are never run
        # while this lock is held.
        self._lock = threading.Lock()
        self._subscriptions: dict[str, Subscription] = {}

    def subscribe(
        self,
        callback: EventCallback,
        event_type: EventType | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> str:
        """Register ``callback`` and return a subscription ID.

        Any filter left as ``None`` matches all values for that field.
        """
        sub_id = str(uuid4())
        subscription = Subscription(
            subscription_id=sub_id,
            callback=callback,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        with self._lock:
            self._subscriptions[sub_id] = subscription
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription. Returns True if it existed."""
        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def publish(self, event: Event) -> None:
        """Deliver ``event`` to matching subscribers.

        Callbacks run after the subscription lock is released. Exceptions
        in one callback do not stop the remaining callbacks.
        """
        with self._lock:
            listeners = list(self._subscriptions.values())

        for subscription in listeners:
            if not subscription.matches(event):
                continue
            try:
                subscription.callback(event)
            except Exception:
                logger.exception(
                    "NIB event callback failed for subscription %s",
                    subscription.subscription_id,
                )

    def publish_all(self, events: list[Event]) -> None:
        """Publish a batch of events in order."""
        for event in events:
            self.publish(event)
