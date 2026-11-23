"""Runnable demo of the simplified Onix NIB.

From the project root:

    python examples/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running the demo without installing the package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nib import EventType, NIB  # noqa: E402


def on_attribute_changed(event) -> None:
    print(
        f"  [event] {event.event_type.value} "
        f"{event.entity_type} {event.entity_id}: "
        f"{event.info['key']} {event.info['old_value']!r} -> {event.info['new_value']!r}"
    )


def on_deleted(event) -> None:
    print(
        f"  [event] {event.event_type.value} "
        f"{event.entity_type} {event.entity_id} "
        f"({event.info.get('reason')})"
    )


def main() -> None:
    print("1. Create an NIB instance")
    nib = NIB()

    print("2. Create two switches")
    s1 = nib.create_switch(attributes={"name": "switch-A"})
    s2 = nib.create_switch(attributes={"name": "switch-B"})
    print(f"   {s1.entity_id} name={nib.get_attr(s1.entity_id, 'name')}")
    print(f"   {s2.entity_id} name={nib.get_attr(s2.entity_id, 'name')}")

    print("3. Create one port on each switch")
    p1 = nib.create_port(s1.entity_id, attributes={"name": "A-eth0"})
    p2 = nib.create_port(s2.entity_id, attributes={"name": "B-eth0"})
    print(f"   port {p1.entity_id} on switch-A")
    print(f"   port {p2.entity_id} on switch-B")

    print("4. Connect the ports with a link")
    link = nib.create_link(p1.entity_id, p2.entity_id, attributes={"status": "UP"})
    print(f"   link {link.entity_id} status={nib.get_attr(link.entity_id, 'status')}")

    print("5. Query topology")
    topo = nib.query_topology()
    print(f"   switches: {len(topo['switches'])}")
    print(f"   ports:    {len(topo['ports'])}")
    print(f"   links:    {len(topo['links'])}")
    print(f"   adjacency: {topo['adjacency']}")

    print("6. Subscribe to attribute-change events")
    nib.subscribe(on_attribute_changed, event_type=EventType.ATTRIBUTE_CHANGED)

    print("7. Change the link status from UP to DOWN")
    nib.set_attr(link.entity_id, "status", "DOWN")

    print("8. Event callback output is printed above")
    print(f"   stored status is now {nib.get_attr(link.entity_id, 'status')!r}")

    print("9. Delete switch-A (cascade: its port and the link)")
    nib.subscribe(on_deleted, event_type=EventType.ENTITY_DELETED)
    nib.delete(s1.entity_id)

    remaining = nib.query_topology()
    print(f"   remaining switches: {[s['attributes'].get('name') for s in remaining['switches']]}")
    print(f"   remaining ports: {len(remaining['ports'])}")
    print(f"   remaining links: {len(remaining['links'])}")
    print("Done.")


if __name__ == "__main__":
    main()
