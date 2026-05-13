import { useEffect, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { fetchAgents } from "@/lib/api";
import type { AgentRegistryRow, AgentRuntimeStatus } from "@/lib/types";

interface UseAgentsOptions {
  /** Active chat id; when provided we subscribe to its WS feed and merge
   * ``agent_event.agent_status`` frames into the registry rows. ``null``
   * disables the subscription (HTTP snapshot only). */
  chatId?: string | null;
}

/**
 * Hook backing the Sidebar "expert agents" group (F6 of
 * ``05-12-multi-agent-obs-blackboard``).
 *
 * Strategy:
 *  - On mount: ``GET /api/agents?include_status=true`` for the registry +
 *    initial runtime snapshot. Backend ensures every row carries a
 *    ``status`` (``offline`` when no runtime is wired).
 *  - When ``chatId`` is set: ``client.onChat`` filters
 *    ``agent_event.agent_status`` and patches the row keyed by ``agent_name``
 *    in-place, so the chip transitions without a refetch.
 */
export function useAgents({ chatId }: UseAgentsOptions = {}): {
  agents: AgentRegistryRow[];
  loading: boolean;
} {
  const { client, token } = useClient();
  const [agents, setAgents] = useState<AgentRegistryRow[]>([]);
  const [loading, setLoading] = useState(false);

  // HTTP snapshot — refresh whenever the token changes.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    fetchAgents(token, { includeStatus: true })
      .then((rows) => {
        if (cancelled) return;
        setAgents(rows);
      })
      .catch((err) => {
        // Degrade-don't-crash: empty registry still renders the header.
        console.warn("fetchAgents failed", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  // WS subscription: patch rows on agent_status frames.
  useEffect(() => {
    if (!chatId) return;
    const off = client.onChat(chatId, (ev) => {
      if (ev.event !== "agent_event") return;
      if (ev.type !== "agent_status") return;
      const p = ev.payload;
      const name = p.agent_name;
      if (!name) return;
      const status = (p.agent_status ?? p.status) as
        | AgentRuntimeStatus
        | undefined;
      if (!status) return;
      setAgents((prev) =>
        prev.map((row) =>
          row.name === name
            ? {
                ...row,
                status,
                current_task_id: p.current_task_id ?? row.current_task_id,
                last_heartbeat_at: p.last_heartbeat_at ?? row.last_heartbeat_at,
              }
            : row,
        ),
      );
    });
    return () => off();
  }, [chatId, client]);

  return { agents, loading };
}

export default useAgents;
