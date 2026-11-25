"""Browser UI for the simplified Onix NIB.

From the project root:

    python examples/ui_demo.py            # opens http://127.0.0.1:8765
    python examples/ui_demo.py --port 9000 --no-browser

Uses only the standard library. Every change goes through the public ``NIB``
API, and the notification log shows only what real subscriptions delivered.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Allow running the demo without installing the package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nib import Event, EventType, NIB, NIBError, ValidationError  # noqa: E402

PAGE = Path(__file__).resolve().parent / "ui" / "index.html"
MAX_LOG = 200
MAX_BODY = 64 * 1024
ENTITY_TYPES = ("switch", "port", "link")

# The same nine steps as examples/demo.py.
STEPS = [
    ("Create an NIB instance", "The NIB starts as an empty graph."),
    ("Create two switches", "Each switch becomes an entity with its own ID."),
    ("Create one port on each switch", "A port belongs to exactly one switch."),
    ("Connect the ports with a link", "A link joins two distinct, unused ports."),
    ("Query topology", "Adjacency is computed from a snapshot of the graph."),
    ("Subscribe to attribute changes", "Until now nothing was listening, so no events were delivered."),
    ("Change the link from UP to DOWN", "The subscriber is notified of the change."),
    ("Read the stored status", "The new value is in the NIB."),
    ("Subscribe to deletions, then delete switch-A", "Its port and link are deleted with it."),
]


class DemoSession:
    """One NIB plus the bookkeeping the page needs.

    Every operation runs under ``_cond``, so the events in the log appear in
    the same order as the changes that caused them.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.RLock())
        self.version = 0
        self._clear()
        self._subscribe(None, None)

    # -- state --------------------------------------------------------------

    def _clear(self) -> None:
        self.nib = NIB()
        self.subs: dict[str, dict[str, Any]] = {}
        self.log: list[dict[str, Any]] = []
        self.labels: dict[str, str] = {}
        self.step = 0
        self._walk: dict[str, str] = {}
        self._entry_no = 0
        self._received: list[Event] = []

    def state(self) -> dict[str, Any]:
        with self._cond:
            return {
                "version": self.version,
                "topology": self.nib.query_topology(),
                "labels": dict(self.labels),
                "subscriptions": list(self.subs.values()),
                "log": self.log[-MAX_LOG:],
                "step": self.step,
                "steps": [{"title": t, "detail": d} for t, d in STEPS],
            }

    def wait_for_change(self, seen: int, timeout: float) -> dict[str, Any] | None:
        with self._cond:
            if self._cond.wait_for(lambda: self.version != seen, timeout):
                return self.state()
            return None

    # -- running and recording calls ----------------------------------------

    def _on_event(self, event: Event) -> None:
        # Overlapping subscriptions deliver the same Event more than once.
        if not any(event is seen for seen in self._received):
            self._received.append(event)

    def _call(
        self,
        text: str,
        fn: Callable[[], Any],
        describe: Callable[[Any], str] | None = None,
    ) -> Any:
        """Run one NIB call and log it with the events it delivered."""
        self._received = []
        result = fn()
        self._entry_no += 1
        self.log.append(
            {
                "n": self._entry_no,
                "call": text,
                "result": describe(result) if describe else None,
                "events": [self._event_json(e) for e in self._received],
            }
        )
        return result

    def _event_json(self, event: Event) -> dict[str, Any]:
        info = {k: v for k, v in event.info.items() if k != "entity"}
        return {
            "type": event.event_type.value,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "label": self._label_of(event.entity_id, event.info.get("entity")),
            "time": event.timestamp.isoformat(),
            "info": info,
        }

    def _label_of(self, entity_id: str, snap: dict[str, Any] | None = None) -> str:
        """Readable name; remembered so deleted entities keep theirs."""
        if entity_id not in self.labels and snap is not None:
            if snap["type"] == "link":
                a = self._label_of(snap["port_a_id"])
                b = self._label_of(snap["port_b_id"])
                self.labels[entity_id] = f"{a} to {b}"
            else:
                self.labels[entity_id] = str(snap["attributes"].get("name") or entity_id[:8])
        return self.labels.get(entity_id, entity_id[:8])

    def _remember(self, entity_id: str) -> None:
        self._label_of(entity_id, self.nib.get(entity_id))

    def _var(self, entity_id: str) -> str:
        return re.sub(r"\W+", "_", self._label_of(entity_id))

    # -- NIB operations -----------------------------------------------------

    def _create_switch(self, name: str) -> str:
        switch = self._call(
            f"nib.create_switch(attributes={{'name': {name!r}}})",
            lambda: self.nib.create_switch(attributes={"name": name}),
        )
        self._remember(switch.entity_id)
        return switch.entity_id

    def _create_port(self, switch_id: str) -> str:
        snap = self.nib.get(switch_id)
        if snap["type"] != "switch":
            raise ValidationError("Ports can only be added to a switch")
        prefix = self._label_of(switch_id).removeprefix("switch-")
        used = {
            self.nib.get(p)["attributes"].get("name") for p in snap["port_ids"]
        }
        i = 0
        while f"{prefix}-eth{i}" in used:
            i += 1
        name = f"{prefix}-eth{i}"
        port = self._call(
            f"nib.create_port({self._var(switch_id)}, attributes={{'name': {name!r}}})",
            lambda: self.nib.create_port(switch_id, attributes={"name": name}),
        )
        self._remember(port.entity_id)
        return port.entity_id

    def _create_link(self, port_a: str, port_b: str) -> str:
        link = self._call(
            f"nib.create_link({self._var(port_a)}, {self._var(port_b)}, "
            "attributes={'status': 'UP'})",
            lambda: self.nib.create_link(port_a, port_b, attributes={"status": "UP"}),
        )
        self._remember(link.entity_id)
        return link.entity_id

    def _set_attr(self, entity_id: str, key: str, value: str) -> None:
        self._call(
            f"nib.set_attr({self._var(entity_id)}, {key!r}, {value!r})",
            lambda: self.nib.set_attr(entity_id, key, value),
        )
        if key == "name" and self.nib.get(entity_id)["type"] != "link":
            self.labels[entity_id] = value or entity_id[:8]

    def _delete(self, entity_id: str) -> None:
        self._call(
            f"nib.delete({self._var(entity_id)})", lambda: self.nib.delete(entity_id)
        )

    def _subscribe(self, event_type: EventType | None, entity_type: str | None) -> None:
        for sub in self.subs.values():
            if (sub["event_type"], sub["entity_type"]) == (
                event_type.value if event_type else None,
                entity_type,
            ):
                raise ValidationError("That subscription already exists")
        args = ["on_event"]
        if event_type:
            args.append(f"event_type=EventType.{event_type.name}")
        if entity_type:
            args.append(f"entity_type={entity_type!r}")
        sub_id = self._call(
            f"nib.subscribe({', '.join(args)})",
            lambda: self.nib.subscribe(
                self._on_event, event_type=event_type, entity_type=entity_type
            ),
        )
        self.subs[sub_id] = {
            "id": sub_id,
            "event_type": event_type.value if event_type else None,
            "entity_type": entity_type,
        }

    def _unsubscribe(self, sub_id: str) -> None:
        if sub_id not in self.subs:
            raise ValidationError("That subscription no longer exists")
        self._call("nib.unsubscribe(subscription_id)", lambda: self.nib.unsubscribe(sub_id))
        del self.subs[sub_id]

    def _next_switch_name(self) -> str:
        used = {s["attributes"].get("name") for s in self.nib.list_by_type("switch")}
        i = 0
        while True:
            suffix = chr(65 + i % 26) + (str(i // 26) if i >= 26 else "")
            if f"switch-{suffix}" not in used:
                return f"switch-{suffix}"
            i += 1

    # -- actions the page can request ---------------------------------------

    def perform(self, action: str, body: dict[str, Any]) -> None:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            raise ValidationError(f"Unknown action: {action}")
        with self._cond:
            try:
                handler(body)
            finally:
                self.version += 1
                self._cond.notify_all()

    def _do_add_switch(self, body: dict[str, Any]) -> None:
        name = _text(body, "name", required=False) or self._next_switch_name()
        self._create_switch(name)

    def _do_add_port(self, body: dict[str, Any]) -> None:
        self._create_port(_text(body, "switch_id"))

    def _do_connect(self, body: dict[str, Any]) -> None:
        self._create_link(_text(body, "port_a"), _text(body, "port_b"))

    def _do_set_attr(self, body: dict[str, Any]) -> None:
        self._set_attr(
            _text(body, "entity_id"),
            _text(body, "key"),
            _text(body, "value", required=False),
        )

    def _do_delete(self, body: dict[str, Any]) -> None:
        self._delete(_text(body, "entity_id"))

    def _do_subscribe(self, body: dict[str, Any]) -> None:
        raw_event = _text(body, "event_type", required=False)
        entity_type = _text(body, "entity_type", required=False) or None
        try:
            event_type = EventType(raw_event) if raw_event else None
        except ValueError:
            raise ValidationError(f"Unknown event type: {raw_event}") from None
        if entity_type is not None and entity_type not in ENTITY_TYPES:
            raise ValidationError(f"Unknown entity type: {entity_type}")
        self._subscribe(event_type, entity_type)

    def _do_unsubscribe(self, body: dict[str, Any]) -> None:
        self._unsubscribe(_text(body, "id"))

    def _do_clear(self, body: dict[str, Any]) -> None:
        self._clear()
        self._subscribe(None, None)

    def _do_sample(self, body: dict[str, Any]) -> None:
        """Four switches in a ring."""
        self._clear()
        self._subscribe(None, None)
        ids = [self._create_switch(f"switch-{c}") for c in "ABCD"]
        for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
            self._create_link(self._create_port(ids[a]), self._create_port(ids[b]))

    def _do_next_step(self, body: dict[str, Any]) -> None:
        if body.get("restart") or self.step >= len(STEPS):
            self.step = 0
        upcoming = self.step + 1
        if upcoming == 1:
            self._clear()
            self._call("nib = NIB()", lambda: None)
        else:
            try:
                self._walk_step(upcoming)
            except (NIBError, KeyError):
                raise ValidationError(
                    "The network changed, so this step no longer applies. "
                    "Restart the walkthrough."
                ) from None
        self.step = upcoming

    def _walk_step(self, number: int) -> None:
        w = self._walk
        if number == 2:
            w["s1"] = self._create_switch("switch-A")
            w["s2"] = self._create_switch("switch-B")
        elif number == 3:
            w["p1"] = self._create_port(w["s1"])
            w["p2"] = self._create_port(w["s2"])
        elif number == 4:
            w["link"] = self._create_link(w["p1"], w["p2"])
        elif number == 5:
            self._call(
                "nib.query_topology()",
                self.nib.query_topology,
                lambda t: ", ".join(
                    f"{len(t[many])} {one if len(t[many]) == 1 else many}"
                    for one, many in (
                        ("switch", "switches"), ("port", "ports"), ("link", "links")
                    )
                ),
            )
        elif number == 6:
            if not self._has_sub(EventType.ATTRIBUTE_CHANGED):
                self._subscribe(EventType.ATTRIBUTE_CHANGED, None)
        elif number == 7:
            self._set_attr(w["link"], "status", "DOWN")
        elif number == 8:
            self._call(
                f"nib.get_attr({self._var(w['link'])}, 'status')",
                lambda: self.nib.get_attr(w["link"], "status"),
                repr,
            )
        elif number == 9:
            self.nib.get(w["s1"])  # Fail before subscribing if it is gone.
            if not self._has_sub(EventType.ENTITY_DELETED):
                self._subscribe(EventType.ENTITY_DELETED, None)
            self._delete(w["s1"])

    def _has_sub(self, event_type: EventType) -> bool:
        return any(
            s["event_type"] == event_type.value and s["entity_type"] is None
            for s in self.subs.values()
        )


def _text(body: dict[str, Any], key: str, required: bool = True) -> str:
    value = body.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be text")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"Enter a value for {key.replace('_', ' ')}")
    if len(value) > 200:
        raise ValidationError(f"{key} is longer than 200 characters")
    return value


class Handler(BaseHTTPRequestHandler):
    """Serves the page, the action endpoint, and a live state stream."""

    session: DemoSession
    allowed_hosts: set[str]

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _host_ok(self) -> bool:
        # Keeps other web pages from reaching this server via DNS tricks.
        if self.headers.get("Host") in self.allowed_hosts:
            return True
        self._json(403, {"error": "Unexpected Host header"})
        return False

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        if self.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(200, self.session.state())
        elif self.path == "/api/stream":
            self._stream()
        else:
            self._json(404, {"error": "Not found"})

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        state: dict[str, Any] | None = self.session.state()
        seen = -1
        try:
            while True:
                if state is None:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    seen = state["version"]
                    self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
                self.wfile.flush()
                state = self.session.wait_for_change(seen, timeout=15)
        except OSError:
            pass  # The browser tab closed.

    def do_POST(self) -> None:
        if not self._host_ok():
            return
        # A JSON content type cannot be sent cross-site without a preflight.
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Send application/json"})
            return
        if not self.path.startswith("/api/do/"):
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY:
                raise ValueError("body too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
        except ValueError as exc:
            self._json(400, {"error": f"Bad request: {exc}"})
            return
        try:
            self.session.perform(self.path.removeprefix("/api/do/"), body)
        except NIBError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(200, {"ok": True})


def make_server(port: int) -> ThreadingHTTPServer:
    """Build a server bound to this machine only."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    actual = server.server_address[1]
    Handler.session = DemoSession()
    Handler.allowed_hosts = {f"127.0.0.1:{actual}", f"localhost:{actual}"}
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser UI for the NIB demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError as exc:
        sys.exit(f"Cannot use port {args.port} ({exc}). Try --port with another number.")
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"NIB demo running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
