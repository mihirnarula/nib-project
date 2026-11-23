# Simplified Onix Network Information Base (NIB)

An educational, single-process implementation of the **Network Information Base** idea from:

> Koponen, T. et al. *Onix: A Distributed Control Platform for Large-scale Production Networks.* NSDI 2010.

The original Onix platform is a distributed control plane: many controller instances share a network-wide graph (the NIB), replicate it with a DHT / replicated state machine, and drive OpenFlow switches. This project implements **only the NIB concept** — entities, attributes, topology queries, and change notifications — in plain Python, in memory, on one machine.

## Connection to the paper

| Onix paper | This project |
| --- | --- |
| NIB is a graph of network entities with typed attributes | `Switch`, `Port`, and `Link` objects with an attributes dict |
| Control applications read/write the NIB instead of talking to hardware | `NIB` public API (`create_*`, `set_attr`, `query_topology`) |
| Applications register for NIB updates | `EventBus` with typed events and filters |
| Distributed replicas, DHT, Zookeeper/Raft-style coordination | **Not implemented** (single in-memory store + mutex) |
| Import/export modules (OpenFlow, routing protocol I/O) | **Not implemented** |

The goal is a small component you can read, test, and explain: *the NIB is the shared network state that control logic programs against.*

## Architecture

```
Application  -->  NIB (api.py)
                    |
        +-----------+-----------+
        |           |           |
   NIBStore     EventBus   TopologyQuery
   (store.py)  (events.py) (topology.py)
        |
     Entity / Switch / Port / Link
              (entity.py)
```

- **Entities** — UUID identity, type, attributes. A switch owns ports; a link joins two distinct ports; a port has at most one link.
- **Store** — dictionaries plus a lock. Mutations collect events, then publish **after** the lock is released so listeners observe committed state.
- **Events** — `ENTITY_CREATED`, `ENTITY_UPDATED`, `ATTRIBUTE_CHANGED`, `ENTITY_DELETED`. Filters by event type, entity type, and entity ID. One failing callback does not stop the others.
- **Topology** — detached snapshot of switches, ports, links, and switch-level adjacency.
- **API** — one `NIB` object for applications.

## Installation

Python 3.10 or newer. From the `nib-project` directory:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux activate with `source .venv/bin/activate`. The NIB itself uses only the standard library; `pytest` is for tests.

## Run the demo

From `nib-project/`:

```bash
python examples/demo.py
```

The demo creates two switches, a link, prints topology, flips the link to `DOWN` (and prints the attribute event), then deletes a switch and shows cascade deletion.

## Run tests

From `nib-project/`:

```bash
python -m pytest -q
```

## Example API usage

```python
from nib import EventType, NIB

nib = NIB()
s1 = nib.create_switch(attributes={"name": "s1"})
s2 = nib.create_switch(attributes={"name": "s2"})
p1 = nib.create_port(s1.entity_id)
p2 = nib.create_port(s2.entity_id)
link = nib.create_link(p1.entity_id, p2.entity_id, attributes={"status": "UP"})

def on_change(event):
    print(event.info)

nib.subscribe(on_change, event_type=EventType.ATTRIBUTE_CHANGED)
nib.set_attr(link.entity_id, "status", "DOWN")

print(nib.query_topology()["adjacency"])
nib.delete(s1.entity_id)  # also removes p1 and the link
```

## Limitations vs. Onix

- Single instance; no controller cluster, DHT, or consensus.
- State lives in RAM only (no disk or replica log).
- No OpenFlow, no physical switches, no import/export modules.
- No access control, no scaling to “large-scale production networks.”
- Events are in-process Python callbacks, not a distributed pub/sub channel.

Those omissions are intentional: this is a teaching model of the NIB, not a drop-in Onix implementation.
