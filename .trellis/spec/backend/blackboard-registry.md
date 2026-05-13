# Blackboard Registry

> Authoritative contract for `BlackboardRegistry`, the `GET /api/blackboard` endpoint, and the `BlackboardEntry.kind` auto-extraction rule.
> Implementation: `secbot/agent/blackboard.py`, `secbot/agent/tools/blackboard.py`, `secbot/api/blackboard.py`, wired from `secbot/api/server.py`.

---

## 1. Scope / Trigger

The Blackboard is a per-`chat_id` scratchpad where the orchestrator and expert agents leave structured, free-form notes ("[milestone] phase 1 done", "[blocker] host down", etc.). This spec fixes:

1. **Instance lifecycle** — who owns which `Blackboard`, and how the HTTP layer finds it after page refresh.
2. **Kind taxonomy** — the four canonical tags auto-extracted from the leading `[tag]` prefix.
3. **Wire shape** — `BlackboardEntry` serialisation across REST + WS must be byte-identical.

Triggered by [`.trellis/tasks/05-12-multi-agent-obs-blackboard/prd.md`](../../tasks/05-12-multi-agent-obs-blackboard/prd.md).

---

## 2. Signatures

### 2.1 Python API

```python
# secbot/agent/blackboard.py

KNOWN_KINDS: frozenset[str] = frozenset(
    {"milestone", "blocker", "finding", "progress"}
)

@dataclass(slots=True)
class BlackboardEntry:
    id: str                  # monotonic per-Blackboard ("1", "2", …)
    agent_name: str
    text: str
    timestamp: float         # epoch seconds, UTC
    kind: str | None         # one of KNOWN_KINDS, or None

    def to_dict(self) -> dict[str, Any]: ...


class Blackboard:
    def __init__(self, *, chat_id: str | None = None) -> None: ...

    def write(self, agent_name: str, text: str) -> BlackboardEntry:
        """Append a new entry. Auto-extracts ``kind`` from ``^\\s*\\[<tag>\\]``.
        Unknown tags → ``kind=None``.  Emits ``agent_event.blackboard_entry``
        if the owning ``AgentLoop`` has a channel attached."""

    def read(self, *, limit: int | None = None) -> list[BlackboardEntry]: ...


class BlackboardRegistry:
    """Per-process index of live Blackboards keyed by ``chat_id``.

    Registered by :class:`AgentLoop` on chat start; the entry is **retained**
    after the loop exits so HTTP replays can still read the history until the
    server restarts (no disk persistence; D3 in the task PRD).
    """

    def register(self, chat_id: str, board: Blackboard) -> None: ...
    def get(self, chat_id: str) -> Blackboard | None: ...
    def entries_for(self, chat_id: str) -> list[BlackboardEntry]: ...
```

### 2.2 HTTP

```
GET /api/blackboard?chat_id=<chat_id>
Authorization: Bearer <token>
```

Response (200):

```json
{
  "chat_id": "0e1b…c8",
  "entries": [
    {
      "id": "1",
      "agent_name": "orchestrator",
      "text": "[milestone] phase 1 done",
      "timestamp": 1715600000.123,
      "kind": "milestone"
    }
  ]
}
```

---

## 3. Contracts

### 3.1 Request validation

| Rule | Error |
|------|-------|
| `chat_id` query param missing / empty | `400 {"error": "chat_id required"}` |
| `chat_id` not in registry | `200` with `entries: []` (never `404` — refresh-on-empty-chat UX) |
| Bearer token invalid | `401` per global auth middleware |

### 3.2 Response shape invariants

- `entries` is ordered by write time (oldest → newest). Consumers that render "latest N" MUST slice from the tail, not re-sort.
- `timestamp` is **epoch seconds as float** (UTC). This is **distinct** from the ISO-8601 timestamps used by `agent_event.agent_status` (`last_heartbeat_at`). The frontend renders via `new Date(ts * 1000)`.
- `kind` is either one of `KNOWN_KINDS` or `null`. **Unknown tags regress to `null`** — never invent new kind values server-side.
- Field order in the JSON object is NOT contractual (consumers MUST key by name).

### 3.3 Kind extraction regex

Canonical implementation:

```python
_KIND_RE = re.compile(r"^\s*\[(milestone|blocker|finding|progress)\]", re.IGNORECASE)

def _extract_kind(text: str) -> str | None:
    m = _KIND_RE.match(text)
    return m.group(1).lower() if m else None
```

Rules:
- **Case-insensitive match** on the tag; stored value is **lowercase**.
- Matches only at the very start (allowing leading whitespace). Mid-text `[milestone]` does NOT trigger.
- Unknown tags (e.g. `[wip]`, `[todo]`) → `kind=None`. The frontend applies the same regex as a fallback (see `webui/src/components/BlackboardPanel.tsx::KIND_REGEX`), so the render is defensive even when the agent forgets or typos the prefix.

### 3.4 WebSocket mirror

Every `Blackboard.write()` that succeeds AND whose owning `AgentLoop` has a channel attached MUST emit:

```json
{
  "event": "agent_event",
  "chat_id": "<chat_id>",
  "type": "blackboard_entry",
  "payload": {
    "type": "blackboard_entry",
    "id": "…",
    "agent_name": "…",
    "text": "…",
    "timestamp": 1715600000.123,
    "kind": "milestone"
  },
  "timestamp": "2026-05-10T04:38:00+00:00"
}
```

Constraint: `payload.kind` MUST equal the stored `BlackboardEntry.kind` on the same entry. A consumer that replays HTTP first and then subscribes to WS MAY see both surfaces report the entry — dedupe by `payload.id`.

---

## 4. Validation & Error Matrix

| Scenario | HTTP | WS |
|----------|------|----|
| Valid `chat_id` with entries | 200 + full list | live frames continue streaming |
| Valid `chat_id` with no entries yet | 200 + `entries: []` | — |
| Unknown `chat_id` (never written) | 200 + `entries: []` | — (no subscription target) |
| `chat_id` missing / empty | 400 | n/a |
| AgentLoop writes before `register()` | write still succeeds on the local `Blackboard`, but HTTP lookup returns empty until `register()` runs. **Implementation MUST call `register()` in `AgentLoop.__init__`** so the window is zero-length in practice. |
| Text has mid-string `[blocker]` | entry stored with `kind=None` | same |
| Text `"[BLOCKER] X"` | stored with `kind="blocker"` (lowercase normalised) | same |

---

## 5. Good / Base / Bad Cases

### Good
```python
board = registry.get("chat-a") or Blackboard(chat_id="chat-a")
registry.register("chat-a", board)
board.write("port_scan", "[finding] 22/tcp open")   # kind="finding"
board.write("port_scan", "progress: 30%")           # kind=None (no prefix)
```

### Base (defensive rehydrate)
```python
entries = registry.entries_for(chat_id)  # safe even when chat_id unknown → []
for e in entries:
    render(e.kind or _extract_kind_fallback(e.text))
```

### Bad
```python
# BAD — inventing kind values that diverge from KNOWN_KINDS.
board.write("agent", "[urgent] fire!")  # kind=None, not "urgent"

# BAD — assuming entries are sorted newest-first.
entries = registry.entries_for(chat_id)[:10]  # These are OLDEST 10, not latest.

# BAD — relying on WS alone. Page refresh drops the stream; HTTP is the
# authoritative backfill source.
```

---

## 6. Tests Required

`tests/agent/test_blackboard.py` (existing) MUST cover:
- `Blackboard.write()` extracts kind for each of `milestone / blocker / finding / progress` (case-insensitive).
- Mid-string `[kind]` does NOT trigger extraction.
- Unknown tag → `kind=None`.

`tests/api/test_blackboard_route.py` (existing) MUST cover:
- Missing `chat_id` → 400.
- Unknown `chat_id` → 200 + empty list.
- Known `chat_id` → entries in write order with all five fields.
- Response schema **byte-equal** to WS `agent_event.blackboard_entry` for the same entry's `id / agent_name / text / timestamp / kind` subset.

`tests/agent/test_loop.py` (or similar) MUST cover:
- `AgentLoop.__init__` registers its Blackboard on the registry exposed via `app["blackboard_registry"]`.
- Multiple chats produce isolated boards (write on A invisible from B's HTTP read).

---

## 7. Wrong vs Correct

**Wrong** — HTTP handler emits fresh timestamps:
```python
# BAD: discards the original write time
return {"entries": [{"id": e.id, "text": e.text, "timestamp": time.time()}
                    for e in board.read()]}
```

**Correct** — preserve the stored timestamp so refresh shows the same clock as live:
```python
return {"entries": [e.to_dict() for e in board.read()]}
```

**Wrong** — inferring kind in the HTTP layer:
```python
# BAD: double source of truth
entry_out = e.to_dict()
entry_out["kind"] = my_regex(e.text)   # drift risk
```

**Correct** — `Blackboard.write()` is the single extraction point; `to_dict()` serves the canonical kind.

---

## Origin

- `.trellis/tasks/05-12-multi-agent-obs-blackboard/prd.md` (D1 / D2 / D3 / D6 / D7)
- `secbot/agent/blackboard.py` — registry + entry + `_extract_kind`
- `secbot/api/blackboard.py` — HTTP handler
- `webui/src/components/BlackboardPanel.tsx` — frontend consumer (F8)
