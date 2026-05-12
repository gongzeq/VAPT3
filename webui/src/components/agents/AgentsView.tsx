import { useState } from "react";
import { ChevronLeft } from "lucide-react";

import { AgentList } from "./AgentList";
import { AgentEditor } from "./AgentEditor";
import { SkillList } from "./SkillList";
import { SkillEditor } from "./SkillEditor";
import { cn } from "@/lib/utils";

type Tab = "agents" | "skills";
type EditorState =
  | { mode: "none" }
  | { mode: "agent-edit"; name: string }
  | { mode: "agent-create" }
  | { mode: "skill-edit"; name: string }
  | { mode: "skill-create" };

interface AgentsViewProps {
  onBackToChat: () => void;
}

export function AgentsView({ onBackToChat }: AgentsViewProps) {
  const [tab, setTab] = useState<Tab>("agents");
  const [editor, setEditor] = useState<EditorState>({ mode: "none" });

  if (editor.mode === "agent-edit") {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto bg-background">
        <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
          <AgentEditor
            name={editor.name}
            onClose={() => setEditor({ mode: "none" })}
          />
        </main>
      </div>
    );
  }

  if (editor.mode === "agent-create") {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto bg-background">
        <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
          <AgentEditor
            onClose={() => setEditor({ mode: "none" })}
          />
        </main>
      </div>
    );
  }

  if (editor.mode === "skill-edit") {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto bg-background">
        <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
          <SkillEditor
            name={editor.name}
            onClose={() => setEditor({ mode: "none" })}
          />
        </main>
      </div>
    );
  }

  if (editor.mode === "skill-create") {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto bg-background">
        <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
          <SkillEditor
            onClose={() => setEditor({ mode: "none" })}
          />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-background">
      <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
        <button
          type="button"
          onClick={onBackToChat}
          className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Back to chat
        </button>

        <h1 className="mb-4 text-base font-semibold tracking-tight">
          Agent & Skill Management
        </h1>

        {/* Tab bar */}
        <div className="mb-5 flex gap-1 rounded-lg border border-border/60 bg-card/80 p-1">
          <button
            type="button"
            onClick={() => setTab("agents")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              tab === "agents"
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Agents
          </button>
          <button
            type="button"
            onClick={() => setTab("skills")}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              tab === "skills"
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Skills
          </button>
        </div>

        {/* Content */}
        {tab === "agents" ? (
          <AgentList
            onEdit={(name) => setEditor({ mode: "agent-edit", name })}
            onCreate={() => setEditor({ mode: "agent-create" })}
          />
        ) : (
          <SkillList
            onEdit={(name) => setEditor({ mode: "skill-edit", name })}
            onCreate={() => setEditor({ mode: "skill-create" })}
          />
        )}
      </main>
    </div>
  );
}
