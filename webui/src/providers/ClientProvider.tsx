import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { SecbotClient } from "@/lib/secbot-client";
import {
  useUnreadCount,
  type UseUnreadCountResult,
} from "@/hooks/useUnreadCount";

interface ClientContextValue {
  client: SecbotClient;
  token: string;
  modelName: string | null;
  /**
   * Absolute base URL (``http://host:port``) of the workflow REST
   * sub-service advertised by the gateway's bootstrap payload. Empty
   * string means "fall back to same-origin" (test env / legacy build
   * without the sub-service).
   */
  workflowApiBase: string;
  /**
   * App-level unread-notifications badge state. Mounted once here so the
   * 30s REST poll is singleton (multiple copies would multiply traffic);
   * consumers like the Navbar bell read from context rather than calling
   * :func:`useUnreadCount` themselves. See PRD D3 + useUnreadCount docstring.
   */
  unread: UseUnreadCountResult;
}

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  modelName = null,
  workflowApiBase = "",
  children,
}: {
  client: SecbotClient;
  token: string;
  modelName?: string | null;
  workflowApiBase?: string;
  children: ReactNode;
}) {
  const unread = useUnreadCount(token);
  const value = useMemo<ClientContextValue>(
    () => ({ client, token, modelName, workflowApiBase, unread }),
    [client, token, modelName, workflowApiBase, unread],
  );
  return (
    <ClientContext.Provider value={value}>{children}</ClientContext.Provider>
  );
}

export function useClient(): ClientContextValue {
  const ctx = useContext(ClientContext);
  if (!ctx) {
    throw new Error("useClient must be used within a ClientProvider");
  }
  return ctx;
}

/** Narrow accessor for components that only care about the unread badge
 * (avoids re-rendering on unrelated context changes). */
export function useUnread(): UseUnreadCountResult {
  return useClient().unread;
}
