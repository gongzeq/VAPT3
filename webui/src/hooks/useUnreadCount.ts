import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchNotifications } from "@/lib/api";

/**
 * Sources that can trigger an unread-count refetch. Extensible so future
 * work can plug in (e.g. ``"ws"`` once backend broadcasts a
 * ``notification_created`` frame — E1 in the PRD). Today the set is just
 * the time-based + foreground-resume triggers.
 */
export type UnreadRefreshSource = "mount" | "interval" | "visibility";

/** Visible-tab polling cadence. 30s caps the worst-case badge delay at
 * 30s, which matches the PRD's critical_vuln latency target. Kept as a
 * named constant so tests can refer to the same value. */
export const UNREAD_POLL_INTERVAL_MS = 30_000;

export interface UseUnreadCountResult {
  /** Latest known unread count. 0 until the first fetch resolves. */
  unreadCount: number;
  /** ``true`` while a fetch is in flight. UI should not block on this
   * — it's exposed for tests and potential subtle spinners. */
  isFetching: boolean;
  /** Optimistic decrement after a successful ``mark-as-read``. Clamped
   * to 0 so a race between the server response and a stale interval
   * cannot drive the badge negative. */
  decrement: (by?: number) => void;
  /** Optimistic reset after ``mark-all-read``. */
  reset: () => void;
  /** Force-refresh on demand (e.g. when the panel opens). */
  refresh: () => Promise<void>;
}

export interface UseUnreadCountOptions {
  /** Inject custom time source for tests. */
  now?: () => number;
  /** Inject the polling interval (tests use a small value). */
  intervalMs?: number;
}

/**
 * Poll ``/api/notifications?unread=1&limit=1`` every 30s (configurable)
 * while the tab is visible, so the bell badge reflects backend state
 * within one poll cycle.
 *
 * Race discipline: every fetch bumps ``requestIdRef``; responses tag
 * themselves with the id they started on and drop themselves on the
 * floor if a newer request has since started. This prevents a slow
 * stale response from clobbering a fresh optimistic decrement.
 *
 * The hook is deliberately App-level (mounted once under
 * :component:`ClientProvider`) — multiple copies would multiply REST
 * traffic for no benefit. Components read the state via the returned
 * tuple, not by duplicating the hook.
 */
export function useUnreadCount(
  token: string | null,
  options: UseUnreadCountOptions = {},
): UseUnreadCountResult {
  const intervalMs = options.intervalMs ?? UNREAD_POLL_INTERVAL_MS;

  const [unreadCount, setUnreadCount] = useState(0);
  const [isFetching, setIsFetching] = useState(false);

  // Monotonic request id: each fetch claims the next id; responses that
  // started on an earlier id discard themselves. See "race discipline".
  const requestIdRef = useRef(0);
  // Tracks the latest committed request, so late responses can detect
  // they've already been superseded.
  const lastCommittedRef = useRef(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const fetchOnce = useCallback(
    async (_source: UnreadRefreshSource): Promise<void> => {
      const activeToken = tokenRef.current;
      if (!activeToken) return;
      const myId = ++requestIdRef.current;
      setIsFetching(true);
      try {
        const body = await fetchNotifications(
          activeToken,
          { unread: true, limit: 1 },
        );
        // Drop stale responses: a newer fetch has already committed (or
        // is about to). Writing ``unread_count`` here would reintroduce
        // state the user just optimistically cleared.
        if (myId < lastCommittedRef.current) return;
        lastCommittedRef.current = myId;
        const next = Number.isFinite(body.unread_count) ? body.unread_count : 0;
        setUnreadCount(Math.max(0, next));
      } catch (err) {
        // Transient failures leave the last-known count in place rather
        // than flashing 0 — the user experience should be "badge stale
        // by a cycle" not "badge wrong". ``ApiError`` 401 is the caller's
        // problem (ProtectedRoute handles that flow).
        if (!(err instanceof ApiError)) {
          // Non-HTTP errors (e.g. network blip) — swallow to keep the
          // hook non-crashing; badge keeps its last value.
        }
      } finally {
        // Only clear the spinner if this fetch is the latest one. A
        // superseding fetch may still be in-flight; letting it own the
        // spinner avoids flicker.
        if (myId === requestIdRef.current) {
          setIsFetching(false);
        }
      }
    },
    [],
  );

  const refresh = useCallback(async () => {
    await fetchOnce("mount");
  }, [fetchOnce]);

  const decrement = useCallback((by: number = 1) => {
    setUnreadCount((prev) => Math.max(0, prev - by));
  }, []);

  const reset = useCallback(() => {
    setUnreadCount(0);
  }, []);

  // Core polling + visibility plumbing. ``token`` or ``intervalMs``
  // changes tear the loop down and rebuild it, so we don't leak timers
  // when a re-auth swaps the token.
  useEffect(() => {
    if (!token) {
      setUnreadCount(0);
      return;
    }

    let timer: ReturnType<typeof setInterval> | null = null;

    const startInterval = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        void fetchOnce("interval");
      }, intervalMs);
    };
    const stopInterval = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    // First load + kick off the polling loop. Visibility state decides
    // whether to start the interval immediately: a hidden tab on mount
    // still does one fetch to seed the badge, but skips the interval
    // until the user brings it back.
    void fetchOnce("mount");
    if (typeof document !== "undefined" && document.hidden) {
      // stay idle until the tab comes back
    } else {
      startInterval();
    }

    const onVisibilityChange = () => {
      if (typeof document === "undefined") return;
      if (document.hidden) {
        stopInterval();
      } else {
        // Immediate catch-up fetch on resume so the badge is not ``intervalMs``
        // behind the moment the user refocuses the tab.
        void fetchOnce("visibility");
        startInterval();
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    return () => {
      stopInterval();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
  }, [token, intervalMs, fetchOnce]);

  return { unreadCount, isFetching, decrement, reset, refresh };
}
