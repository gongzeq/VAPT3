/**
 * PR0 verification test: ensures SecbotThread correctly wires all 6 skill
 * renderers through the v0.10 API (MessagePrimitive.Content components.tools.by_name).
 */
import { describe, it, expect } from "vitest";
import { SKILL_RENDERERS } from "../tool-ui";
import * as SecbotThreadModule from "../SecbotThread";

describe("SecbotThread v0.10 API compliance", () => {
  it("exports SecbotThread component", () => {
    expect(SecbotThreadModule.SecbotThread).toBeDefined();
    expect(typeof SecbotThreadModule.SecbotThread).toBe("function");
  });

  it("exports all 8 skill renderers in SKILL_RENDERERS", () => {
    const expectedSkills = [
      "cmdb-query",
      "nmap-port-scan",
      "nuclei-template-scan",
      "fscan-asset-discovery",
      "fscan-vuln-scan",
      "report-markdown",
      "report-docx",
      "report-pdf",
    ];

    expectedSkills.forEach((skill) => {
      expect(SKILL_RENDERERS[skill]).toBeDefined();
      expect(typeof SKILL_RENDERERS[skill]).toBe("function");
    });

    // Verify the registry has exactly these 8 entries
    expect(Object.keys(SKILL_RENDERERS)).toHaveLength(8);
  });

  it("uses correct v0.10 imports from @assistant-ui/react", () => {
    // Read the source file to verify it uses the correct v0.10 API
    const fs = require("fs");
    const path = require("path");
    const sourceFile = fs.readFileSync(
      path.join(__dirname, "../SecbotThread.tsx"),
      "utf-8"
    );

    // Verify it imports the correct primitives (not the removed styled Thread)
    expect(sourceFile).toContain("ThreadPrimitive");
    expect(sourceFile).toContain("MessagePrimitive");
    expect(sourceFile).toContain("ComposerPrimitive");
    expect(sourceFile).toContain("AssistantRuntimeProvider");

    // Verify it does NOT import the removed styled Thread component
    expect(sourceFile).not.toMatch(/import\s+\{[^}]*\bThread\b[^}]*\}\s+from\s+["']@assistant-ui\/react["']/);

    // Verify it uses MessagePrimitive.Content with tools.by_name
    expect(sourceFile).toContain("MessagePrimitive.Content");
    expect(sourceFile).toContain("tools:");
    expect(sourceFile).toContain("by_name:");
    expect(sourceFile).toContain("SKILL_RENDERERS");
    expect(sourceFile).toContain("Fallback:");
    expect(sourceFile).toContain("ToolCallCard");
  });
});
