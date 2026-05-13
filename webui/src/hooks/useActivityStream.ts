import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, fetchActivityEvents } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import type {
  ActivityCategory,
  ActivityEvent,
  ActivityEventFrame,
  ActivityLevel,
  ActivitySource,
} from "@/lib/types";

/** Cap the in-memory ring at this size so a long-running session doesn't
 * grow the array without bound. Ring-buffer semantics: oldest-first drop. */
export const ACTIVITY_STREAM_LIMIT = 100;

/** Default REST ``limit`` for the seed fetch. Matches the backend default. */
const DEFAULT_SEED_LIMIT = 50;

/** Valid :type:`ActivitySource` values — kept in sync with the type. */
const KNOWN_SOURCES: ReadonlySet<string> = new Set<string>([
  "weak_password",
  "port_scan",
  "asset_discovery",
  "report",
  "orchestrator",
]);

export type UseActivityStreamLoadState = "loading" | "ready" | "error";

export interface UseActivityStreamResult {
  events: ActivityEvent[];
  state: UseActivityStreamLoadState;
  errorCode: string | null;
  /** Refetch the REST seed (e.g. on retry). Leaves the WS subscription alone. */
  refresh: () => Promise<void>;
}

export interface UseActivityStreamOptions {
  seedLimit?: number;
  /** Inject an alternative ``now()`` — used by tests to stabilise the
   * WS-derived event id (falls back to the frame's ``timestamp``). */
  now?: () => number;
  /** Right-Rail Trace scope: when set, the HTTP seed uses
   * ``?chat_id=<id>`` and every incoming WS frame is dropped unless
   * ``frame.chat_id === chatId``. Omitting this keeps the dashboard's
   * pre-existing global feed behaviour (D1 in the PRD: hook shape is
   * additive; callers that don't pass ``chatId`` are unaffected). */
  chatId?: string;
  /** Right-Rail Trace scope: category inclusion filter. Applied on
   * both the HTTP seed (as ``?category=a,b``) and the live WS stream. */
  categories?: ReadonlyArray<ActivityCategory>;
}

/**
 * Infer a UI ``level`` for a WS frame from its category, since the WS
 * broadcast doesn't include a severity. Tool results are treated as
 * ``ok`` / thoughts as ``info`` / calls as ``info`` by default. This
 * matches the PRD rule "WS 帧落地时不降级 REST 严重级别" — REST rows
 * carry their own ``level`` and overwrite on dedupe.
 */
function inferLevel(category: ActivityCategory | string): ActivityLevel {
  switch (category) {
    case "tool_result":
      return "ok";
    case "thought":
    case "tool_call":
    default:
      return "info";
  }
}

/** Narrow a free-form WS ``agent`` string into an :type:`ActivitySource`
 * when possible. Unknown agents fall back to ``"orchestrator"`` so the
 * row still renders (F5). */
function normaliseSource(agent: string | undefined): ActivitySource {
  if (agent && KNOWN_SOURCES.has(agent)) {
    return agent as ActivitySource;
  }
  return "orchestrator";
}

/** Build a stable id for a WS-originated row.
 *
 * Format: ``ws|chat_id|timestamp|step`` — deterministic so the same
 * event later surfacing via REST (with its own id) dedupes when the
 * hook merges the two streams. */
function deriveWsId(frame: ActivityEventFrame): string {
  return `ws|${frame.chat_id}|${frame.timestamp}|${frame.step ?? ""}`;
}

function messageFromFrame(frame: ActivityEventFrame): string {
  const bits = [frame.agent, frame.step, frame.category].filter(Boolean);
  if (bits.length === 0) return "";
  return bits.join(" · ");
}

function frameToEvent(frame: ActivityEventFrame): ActivityEvent {
  const category = (frame.category as ActivityCategory) ?? "tool_call";
  return {
    id: deriveWsId(frame),
    timestamp: frame.timestamp,
    level: inferLevel(category),
    source: normaliseSource(frame.agent),
    message: messageFromFrame(frame),
    task_id: null,
    chat_id: frame.chat_id,
    agent: frame.agent ?? null,
    step: frame.step ?? null,
    category: (category as ActivityCategory) ?? null,
    duration_ms: frame.duration_ms ?? null,
  };
}

function dedupeAndSort(events: ActivityEvent[]): ActivityEvent[] {
  // Dedup by id with "last write wins" so REST rows (arriving later with
  // a stable level/source) overwrite a WS-inferred placeholder.
  const byId = new Map<string, ActivityEvent>();
  for (const ev of events) {
    byId.set(ev.id, ev);
  }
  return Array.from(byId.values())
    .sort((a, b) => {
      const at = Date.parse(a.timestamp);
      const bt = Date.parse(b.timestamp);
      if (Number.isNaN(at) || Number.isNaN(bt)) return 0;
      return bt - at; // newest first
    })
    .slice(0, ACTIVITY_STREAM_LIMIT);
}

/**
 * Live activity stream for the dashboard panel.
 *
 * Data flow:
 *   1. On mount, REST-seed up to ``seedLimit`` rows from ``/api/events``.
 *   2. Subscribe to WS ``activity_event`` frames via
 *      :func:`SecbotClient.onActivityEvent`; new frames are normalised
 *      into :type:`ActivityEvent` and prepended.
 *   3. Every mutation re-sorts by timestamp (newest first) and caps at
 *      :const:`ACTIVITY_STREAM_LIMIT`.
 *
 * WS-before-REST race: if a WS frame lands before the REST seed resolves,
 * it's still kept; the seed merge goes through the same dedupe path so
 * the WS row is preserved unless REST returns the same id (which it
 * won't: WS ids use the ``ws|...`` prefix, REST ids are server-assigned).
 */
export function useActivityStream(
  options: UseActivityStreamOptions = {},
): UseActivityStreamResult {
  const { seedLimit = DEFAULT_SEED_LIMIT, chatId, categories } = options;
  const { client, token } = useClient();

  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [state, setState] = useState<UseActivityStreamLoadState>("loading");
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const requestIdRef = useRef(0);
  const lastCommittedRef = useRef(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  // Freeze the categories list into a stable reference so effects don't
  // re-fire on every parent render. A joined string is cheaper than
  // array reference equality in deps.
  const categoriesKey = useMemo(
    () => (categories ? categories.join(",") : ""),
    [categories],
  );
  const categoriesRef = useRef<ReadonlyArray<ActivityCategory> | undefined>(
    categories,
  );
  categoriesRef.current = categories;

  const refresh = useCallback(async () => {
    const activeToken = tokenRef.current;
    if (!activeToken) {
      setEvents([]);
      setState("ready");
      setErrorCode(null);
      return;
    }
    const myId = ++requestIdRef.current;
    setState((prev) => (prev === "ready" ? prev : "loading"));
    setErrorCode(null);
    try {
      const body = await fetchActivityEvents(activeToken, {
        limit: seedLimit,
        chatId: chatId || undefined,
        categories: categoriesRef.current,
      });
      if (myId < lastCommittedRef.current) return;
      lastCommittedRef.current = myId;
      const seed = Array.isArray(body.items) ? body.items : [];
      setEvents((prev) => dedupeAndSort([...seed, ...prev]));
      setState("ready");
    } catch (err) {
      if (myId < lastCommittedRef.current) return;
      lastCommittedRef.current = myId;
      setErrorCode(err instanceof ApiError ? String(err.status) : "network");
      setState("error");
    }
  }, [seedLimit, chatId, categoriesKey]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Category set is rebuilt only when the joined key changes — cheap
  // lookup inside the (potentially hot) WS handler.
  const categorySet = useMemo(() => {
    if (!categories || categories.length === 0) return null;
    return new Set<string>(categories as unknown as string[]);
  }, [categoriesKey]);

  // WS subscription — independent of REST seed lifecycle. Keep it mounted
  // for the life of the component; unsubscribe on unmount.
  useEffect(() => {
    const unsubscribe = client.onActivityEvent((frame) => {
      if (chatId && frame.chat_id !== chatId) return;
      if (categorySet && !categorySet.has(String(frame.category))) return;
      setEvents((prev) => dedupeAndSort([frameToEvent(frame), ...prev]));
    });
    return unsubscribe;
  }, [client, chatId, categorySet]);

  return useMemo(
    () => ({ events, state, errorCode, refresh }),
    [events, state, errorCode, refresh],
  );
}
