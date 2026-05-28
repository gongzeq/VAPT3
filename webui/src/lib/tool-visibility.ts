const HIDDEN_FRONTEND_TOOL_NAMES = new Set(["asset_push"]);

export function isHiddenFrontendToolName(toolName: unknown): boolean {
  return typeof toolName === "string" && HIDDEN_FRONTEND_TOOL_NAMES.has(toolName);
}

export function hasOnlyHiddenToolEvents(toolEvents: unknown[] | undefined): boolean {
  if (!Array.isArray(toolEvents) || toolEvents.length === 0) return false;
  return toolEvents.every((event) => {
    if (!event || typeof event !== "object") return false;
    return isHiddenFrontendToolName((event as Record<string, unknown>).name);
  });
}

export function isHiddenToolHintText(text: string | undefined): boolean {
  const normalized = String(text ?? "").trim();
  if (!normalized) return false;
  return /^asset_push(?:\([^)]*\))?(?:\s*[x×]\s*\d+)?$/.test(normalized);
}
