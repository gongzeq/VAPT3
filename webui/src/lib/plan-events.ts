import type { AgentEventPayload, OrchestratorPlanStep } from "@/lib/types";

function normalizePlanStep(step: unknown): OrchestratorPlanStep | null {
  if (!step || typeof step !== "object") return null;
  const obj = step as Record<string, unknown>;
  const title = typeof obj.title === "string" ? obj.title.trim() : "";
  if (!title) return null;
  const detail =
    typeof obj.detail === "string" && obj.detail.trim()
      ? obj.detail.trim()
      : undefined;
  return detail ? { title, detail } : { title };
}

export function planFromWritePlanToolCall(
  payload: Pick<AgentEventPayload, "tool_name" | "tool_args" | "agent" | "agent_name">,
): AgentEventPayload | null {
  if (payload.tool_name !== "write_plan") return null;
  const rawSteps = payload.tool_args?.steps;
  if (!Array.isArray(rawSteps)) return null;
  const steps = rawSteps
    .map((step) => normalizePlanStep(step))
    .filter(Boolean) as OrchestratorPlanStep[];
  if (steps.length === 0) return null;
  return {
    type: "orchestrator_plan",
    agent: payload.agent ?? payload.agent_name ?? "orchestrator",
    steps,
  };
}

export function planFromToolEvents(
  toolEvents: unknown[] | undefined,
): AgentEventPayload | null {
  if (!Array.isArray(toolEvents)) return null;
  for (const event of toolEvents) {
    if (!event || typeof event !== "object") continue;
    const obj = event as Record<string, unknown>;
    if (obj.phase !== "start" || obj.name !== "write_plan") continue;
    const args = obj.arguments;
    if (!args || typeof args !== "object" || Array.isArray(args)) continue;
    const plan = planFromWritePlanToolCall({
      tool_name: "write_plan",
      tool_args: args as Record<string, unknown>,
      agent: "orchestrator",
    });
    if (plan) return plan;
  }
  return null;
}
