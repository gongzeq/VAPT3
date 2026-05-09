import { useNavigate } from "react-router-dom";
import { PromptSuggestions } from "@/components/PromptSuggestions";
import { Shell } from "@/components/Shell";

export interface HomePageProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
}

/**
 * /  — Chat HomePage (template §7.2).
 *
 * Mounts the existing Shell (sidebar + ThreadShell) with the new
 * `rightRail` prop so that on xl: screens the PromptSuggestions panel +
 * Quick-stats card appears in a collapsible 320px rail on the right side.
 * On smaller screens the rail is hidden and the UX degrades gracefully to
 * the full-width chat surface from PR3.
 *
 * The prompt chips use a CustomEvent (`secbot:composer-prefill`) to inject
 * the suggestion text into ThreadComposer's textarea without creating a
 * deep props chain. See PromptSuggestions.tsx / ThreadComposer.tsx for the
 * integration contract.
 */
export function HomePage({ onModelNameChange, onLogout }: HomePageProps) {
  const navigate = useNavigate();
  return (
    <Shell
      onModelNameChange={onModelNameChange}
      onLogout={onLogout}
      onOpenSettingsExternal={() => navigate("/settings")}
      rightRail={<PromptSuggestions />}
    />
  );
}

export default HomePage;
