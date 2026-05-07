/**
 * Skill-specific tool-call renderers.
 *
 * Every secbot skill emits a structured `summary` payload (and an optional
 * `findings` array). This file maps `tool_name` → React renderer so that
 * scan results show up as semantic UI rather than raw JSON.
 *
 * Skills not registered here fall back to <DefaultToolFallback />.
 */
import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { CmdbQueryRenderer } from "./renderers/cmdb-query";
import { FscanAssetDiscoveryRenderer } from "./renderers/fscan-asset-discovery";
import { FscanVulnScanRenderer } from "./renderers/fscan-vuln-scan";
import { NmapPortScanRenderer } from "./renderers/nmap-port-scan";
import { NucleiTemplateScanRenderer } from "./renderers/nuclei-template-scan";
import { ReportRenderer } from "./renderers/report";
import { ToolCallCard } from "./renderers/tool-call-card";

export type ToolRendererRegistry = Record<string, ToolCallContentPartComponent>;

export const SKILL_RENDERERS: ToolRendererRegistry = {
  "cmdb-query": CmdbQueryRenderer,
  "nmap-port-scan": NmapPortScanRenderer,
  "nuclei-template-scan": NucleiTemplateScanRenderer,
  "fscan-asset-discovery": FscanAssetDiscoveryRenderer,
  "fscan-vuln-scan": FscanVulnScanRenderer,
  "report-markdown": ReportRenderer,
  "report-docx": ReportRenderer,
  "report-pdf": ReportRenderer,
};

export function getToolRenderer(name: string): ToolCallContentPartComponent {
  return SKILL_RENDERERS[name] ?? ToolCallCard;
}
