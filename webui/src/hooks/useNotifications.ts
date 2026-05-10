import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import type { Notification } from "@/lib/types";

/** Cap the panel view at the latest N rows regardless of backend ``limit``
 * — matches the PRD "最近 20 条" display rule. Kept as an exported
 * constant so the panel / tests can reference the same number. */
export const NOTIFICATION_PANEL_LIMIT = 20;

export type UseNotificationsLoadState =
  | "idle"
  | "loading"
  | "ready"
  | "error";

export interface UseNotificationsResult {
  /** Latest rows (server order, newest first). Never longer than
   * :const:`NOTIFICATION_PANEL_LIMIT`. */
  items: Notification[];
  /** Lifecycle of the most recent fetch attempt. */
  state: UseNotificationsLoadState;
  /** Non-null only when ``state === "error"``. Holds a short code the
   * UI maps to a translated message (e.g. ``"network"`` / ``"401"``). */
  errorCode: string | null;
  /** Force-refresh (used when the panel opens or on retry). */
  refresh: () => Promise<void>;
  /** Optimistically mark one row read, server-sync, and bubble the
   * decrement up to the shared unread badge. */
  markRead: (id: string) => Promise<void>;
  /** Optimistically mark all rows read, server-sync, and clear the
   * shared unread badge. */
  markAllRead: () => Promise<void>;
}

export interface UseNotificationsOptions {
  /** Called after a successful single-read to decrement the shared
   * badge (mounted once under :component:`ClientProvider`). */
  onDecrement?: (by: number) => void;
  /** Called after a successful mark-all to zero the shared badge. */
  onReset?: () => void;
  /** Injection hook for tests — lets a harness skip the initial fetch
   * until the caller opts in. */
  autoFetch?: boolean;
}

/**
 * State container for the Navbar notification panel.
 *
 * Lifecycle: cold until the panel mounts; one fetch on mount, plus
 * re-fetch on ``refresh()``. Unlike :func:`useUnreadCount`, this hook
 * does NOT poll — the panel is short-lived (dropdown) and re-opens are
 * cheap enough to refetch.
 *
 * Race discipline: identical to :func:`useUnreadCount`. Every fetch
 * claims a monotonic ``requestId``; late responses drop themselves on
 * the floor if a newer fetch has committed.
 *
 * Optimistic updates: read / read-all flip the local row first, then
 * reconcile on the server response. A failed sync logs via the standard
 * ``console.warn`` path; the panel keeps the optimistic state rather
 * than flashing the previous value — the next refetch (panel re-open)
 * will correct it if the server truly disagreed.
 */
export function useNotifications(
  token: string | null,
  options: UseNotificationsOptions = {},
): UseNotificationsResult {
  const { onDecrement, onReset, autoFetch = true } = options;

  const [items, setItems] = useState<Notification[]>([]);
  const [state, setState] = useState<UseNotificationsLoadState>("idle");
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const requestIdRef = useRef(0);
  const lastCommittedRef = useRef(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  // Keep the latest callbacks without re-firing effects on every render.
  const onDecrementRef = useRef(onDecrement);
  onDecrementRef.current = onDecrement;
  const onResetRef = useRef(onReset);
  onResetRef.current = onReset;

  // Snapshot the latest items so ``markRead`` / ``markAllRead`` can read
  // the current state synchronously without racing React's scheduler
  // (a ``setItems`` functional updater is NOT invoked synchronously, so
  // a post-call ``if (target.read)`` check against a ref captured inside
  // the updater would always see ``undefined``).
  const itemsRef = useRef<Notification[]>(items);
  itemsRef.current = items;

  const refresh = useCallback(async () => {
    const activeToken = tokenRef.current;
    if (!activeToken) {
      setItems([]);
      setState("idle");
      setErrorCode(null);
      return;
    }
    const myId = ++requestIdRef.current;
    setState("loading");
    setErrorCode(null);
    try {
      const body = await fetchNotifications(
        activeToken,
        { limit: NOTIFICATION_PANEL_LIMIT },
      );
      if (myId < lastCommittedRef.current) return;
      lastCommittedRef.current = myId;
      const next = Array.isArray(body.items) ? body.items : [];
      setItems(next.slice(0, NOTIFICATION_PANEL_LIMIT));
      setState("ready");
    } catch (err) {
      if (myId < lastCommittedRef.current) return;
      lastCommittedRef.current = myId;
      if (err instanceof ApiError) {
        setErrorCode(String(err.status));
      } else {
        setErrorCode("network");
      }
      setState("error");
    }
  }, []);

  const markRead = useCallback(async (id: string) => {
    const activeToken = tokenRef.current;
    if (!activeToken) return;
    const target = itemsRef.current.find((n) => n.id === id);
    if (!target || target.read) return;
    setItems((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
    );
    // Optimistic badge decrement happens regardless of server outcome —
    // the panel's next open will reconcile if the server truly didn't
    // flip the row. F5: degrade-don't-crash.
    onDecrementRef.current?.(1);
    try {
      await markNotificationRead(activeToken, id);
    } catch (err) {
      // Keep the optimistic row state but surface the failure via the
      // console; the next refresh will re-read from the server.
      console.warn("notifications.markRead failed", err);
    }
  }, []);

  const markAllRead = useCallback(async () => {
    const activeToken = tokenRef.current;
    if (!activeToken) return;
    const hadUnread = itemsRef.current.some((n) => !n.read);
    if (!hadUnread) return;
    setItems((prev) => prev.map((n) => (n.read ? n : { ...n, read: true })));
    onResetRef.current?.();
    try {
      await markAllNotificationsRead(activeToken);
    } catch (err) {
      console.warn("notifications.markAllRead failed", err);
    }
  }, []);

  // Initial (and token-swap) fetch. Tests can opt out via ``autoFetch: false``.
  useEffect(() => {
    if (!autoFetch) return;
    if (!token) {
      setItems([]);
      setState("idle");
      setErrorCode(null);
      return;
    }
    void refresh();
  }, [token, autoFetch, refresh]);

  return { items, state, errorCode, refresh, markRead, markAllRead };
}
