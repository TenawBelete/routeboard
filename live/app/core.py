"""The parts of the live service that do not touch the network: turning a raw
routing message into a small event, counting per second, and fanning out to
browsers without letting a slow one hold the others back."""

import asyncio
import json
import time
from collections import defaultdict, deque

MAX_PATH = 8             # networks kept per path in an event sent to the browser
SAMPLES_PER_SECOND = 6   # individual route changes shown per second (the counters cover the rest)
HISTORY_SECONDS = 90     # ticks replayed to a browser when it connects
FLUSHES_PER_SECOND = 4   # how often route paths are pushed for the map animations
PATHS_PER_FLUSH = 30     # at most this many paths per push (120 a second) to each browser
RECENT_PER_COUNTRY = 60  # last real route changes kept per country, replayed when a country is quiet


def flatten_path(path) -> list[int]:
    """RIS paths are numbers, with an occasional nested list (an AS set). -> plain numbers, repeats removed."""
    out: list[int] = []
    for hop in path or []:
        for asn in (hop if isinstance(hop, list) else [hop]):
            if isinstance(asn, int) and (not out or out[-1] != asn):
                out.append(asn)
    return out


def to_events(raw: bytes | str, names: dict[int, tuple[str | None, str | None]]) -> list[dict]:
    """One raw RIS message -> zero, one or two compact events (routes opened, routes closed)."""
    try:
        d = json.loads(raw).get("data") or {}
    except (ValueError, AttributeError):
        return []
    if not isinstance(d, dict):
        return []
    peer = d.get("peer_asn")
    try:
        peer = int(peer)
    except (TypeError, ValueError):
        return []
    who = lambda asn: names.get(asn, (None, None))
    out = []
    prefixes = [p for a in (d.get("announcements") or []) for p in (a.get("prefixes") or [])]
    path = flatten_path(d.get("path"))
    if prefixes and path:
        origin = path[-1]
        shown = path[-MAX_PATH:]
        out.append({"k": "open", "n": len(prefixes), "p": prefixes[0], "o": origin, "on": who(origin)[0], "oc": who(origin)[1],
                    "path": shown, "pc": [who(a)[1] for a in shown], "peer": peer})
    closed = d.get("withdrawals") or []
    if closed:
        out.append({"k": "close", "n": len(closed), "p": closed[0], "o": None, "on": None, "oc": None,
                    "path": [peer], "pc": [who(peer)[1]], "peer": peer, "pn": who(peer)[0]})
    return out


def matches(event: dict, country: str | None) -> bool:
    return country is None or country in event["pc"]


def sse(kind: str, payload) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class Hub:
    """Collects events, closes a 'tick' every second and hands both to every connected browser."""

    def __init__(self, max_clients: int = 300, clock=time.time):
        self.clients: dict[asyncio.Queue, str | None] = {}
        self.max_clients = max_clients
        self.history: deque[dict] = deque(maxlen=HISTORY_SECONDS)
        self.clock = clock
        self._opened = self._closed = self._messages = 0
        self._samples: list[dict] = []
        self.total_messages = 0
        self._paths: list[dict] = []
        self.recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=RECENT_PER_COUNTRY))
        self.feed_up = False          # set by the Kafka reader; lets browsers say "reconnecting" instead of showing zeros

    # -- producer side ---------------------------------------------------
    def add(self, events: list[dict]) -> None:
        self._messages += 1
        self.total_messages += 1
        for e in events:
            if e["k"] == "open":
                self._opened += e["n"]
            else:
                self._closed += e["n"]
            self._samples.append(e)
            if e["k"] == "open" and len(e["path"]) >= 2:
                self._paths.append(e)
                item = {"t": int(self.clock()), "path": e["path"], "pc": e["pc"]}
                for cc in {c for c in e["pc"] if c}:
                    self.recent[cc].append(item)

    def remember(self, events: list[dict], t: int) -> None:
        """Keep a past route change in the per-country memory without touching any counter.

        Used at start-up to warm the memory from what Kafka still holds, so a quiet country
        has real, time-stamped changes to show right away instead of waiting for the next one.
        """
        for e in events:
            if e["k"] == "open" and len(e["path"]) >= 2:
                item = {"t": int(t), "path": e["path"], "pc": e["pc"]}
                for cc in {c for c in e["pc"] if c}:
                    self.recent[cc].append(item)

    def sort_recent(self) -> None:
        """Oldest first in every country's memory (warm-up and live arrivals may interleave)."""
        for cc, dq in self.recent.items():
            items = sorted(dq, key=lambda i: i["t"])[-RECENT_PER_COUNTRY:]
            dq.clear(); dq.extend(items)

    def tick(self) -> dict:
        """Call once per second: publish the second that just ended."""
        t = {"t": int(self.clock()), "opened": self._opened, "closed": self._closed, "messages": self._messages, "up": self.feed_up}
        samples, self._samples = self._samples, []
        self._opened = self._closed = self._messages = 0
        self.history.append(t)
        for q, country in list(self.clients.items()):
            mine = [e for e in samples if matches(e, country)]
            # Spread the few we show across the second's messages rather than taking the first ones.
            step = max(1, len(mine) // SAMPLES_PER_SECOND)
            self._offer(q, ("tick", t))
            for e in mine[::step][:SAMPLES_PER_SECOND]:
                self._offer(q, ("msg", e))
        return t

    def flush(self) -> int:
        """Call a few times a second: push the paths of the route changes that just arrived.

        These drive the map animations, so far more are sent than the handful shown in words.
        Only the path is sent (network numbers and their countries), not the full event.
        """
        paths, self._paths = self._paths, []
        if not paths:
            return 0
        for q, country in list(self.clients.items()):
            mine = [e for e in paths if matches(e, country)]
            if not mine:
                continue
            step = max(1, -(-len(mine) // PATHS_PER_FLUSH))        # ceil: spread the sample across what arrived
            self._offer(q, ("paths", [[e["path"], e["pc"]] for e in mine[::step][:PATHS_PER_FLUSH]]))
        return len(paths)

    @staticmethod
    def _offer(q: asyncio.Queue, item) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:      # a slow browser loses messages; it never slows the others
            pass

    # -- consumer side ---------------------------------------------------
    def connect(self, country: str | None) -> asyncio.Queue | None:
        if len(self.clients) >= self.max_clients:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=120)
        self.clients[q] = country
        return q

    def disconnect(self, q: asyncio.Queue) -> None:
        self.clients.pop(q, None)
