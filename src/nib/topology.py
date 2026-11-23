"""Read-only topology queries over the NIB graph.

Onix applications read a consistent view of the network from the NIB.
Here that view is a snapshot copied out of the in-memory store so callers
cannot mutate internal dictionaries.
"""

from __future__ import annotations

from typing import Any

from nib.store import EntityNotFoundError, NIBStore


class TopologyQuery:
    """Build adjacency and neighbor views from store snapshots."""

    def __init__(self, store: NIBStore) -> None:
        self._store = store

    def query_topology(self) -> dict[str, Any]:
        """Return a detached topology snapshot.

        The adjacency list maps each switch ID to a list of neighbor
        switch IDs (undirected: A in B's list iff B is in A's list).
        Isolated switches appear with an empty neighbor list.
        """
        switches, ports, links = self._store.copy_graph()
        adjacency = self._adjacency(switches, ports, links)
        return {
            "switches": switches,
            "ports": ports,
            "links": links,
            "adjacency": adjacency,
        }

    def neighbors(self, switch_id: str) -> list[str]:
        """Return IDs of switches directly linked to ``switch_id``."""
        topo = self.query_topology()
        switch_ids = {s["id"] for s in topo["switches"]}
        if switch_id not in switch_ids:
            raise EntityNotFoundError(f"No switch with ID {switch_id}")
        return list(topo["adjacency"][switch_id])

    def are_connected(self, switch_a_id: str, switch_b_id: str) -> bool:
        """Return True if the two switches share a link (one hop)."""
        return switch_b_id in self.neighbors(switch_a_id)

    def _adjacency(
        self,
        switches: list[dict[str, Any]],
        ports: list[dict[str, Any]],
        links: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        port_by_id = {p["id"]: p for p in ports}
        adjacency: dict[str, set[str]] = {s["id"]: set() for s in switches}

        for link in links:
            port_a = port_by_id.get(link["port_a_id"])
            port_b = port_by_id.get(link["port_b_id"])
            if port_a is None or port_b is None:
                continue
            switch_a = port_a["switch_id"]
            switch_b = port_b["switch_id"]
            if switch_a == switch_b:
                # Loop cable on the same switch: not a neighbor edge.
                continue
            if switch_a in adjacency and switch_b in adjacency:
                adjacency[switch_a].add(switch_b)
                adjacency[switch_b].add(switch_a)

        # Convert sets to sorted lists so snapshots are stable and detached.
        return {switch_id: sorted(neighbors) for switch_id, neighbors in adjacency.items()}
