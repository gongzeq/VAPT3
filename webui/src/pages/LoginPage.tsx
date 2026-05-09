import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { AuthForm } from "@/components/AuthForm";
import type { BootStatus } from "@/components/ProtectedRoute";

export interface LoginPageProps {
  state: BootStatus;
  onSecret: (secret: string) => void;
}

/**
 * Template-mode /login route. Honors `?next=` so the user is bounced back to
 * the originally requested protected URL once bootstrap succeeds.
 *
 * The page intentionally stays minimal in PR3 — PR4 (R4.1) will replace this
 * with the two-column hero layout (banner + centered card). The form itself
 * already lives in <AuthForm/> so the upgrade only swaps the surrounding
 * layout, not the auth wiring.
 */
export function LoginPage({ state, onSecret }: LoginPageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  // When auth completes, bounce to the requested target (or "/" by default).
  useEffect(() => {
    if (state.status !== "ready") return;
    const params = new URLSearchParams(location.search);
    const next = params.get("next");
    const target = next && next.startsWith("/") ? next : "/";
    navigate(target, { replace: true });
  }, [state, location.search, navigate]);

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <AuthForm
        failed={state.status === "auth" && !!state.failed}
        onSecret={onSecret}
        title={t("app.brand", { defaultValue: "海盾智能体管控台" })}
      />
    </div>
  );
}

export default LoginPage;
