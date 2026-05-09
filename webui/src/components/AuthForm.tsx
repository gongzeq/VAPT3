import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Shared bootstrap-secret form. Extracted from App.tsx so the same UX can
 * power both the legacy in-place auth screen (when VITE_UIUX_TEMPLATE is
 * disabled) and the new /login route. The form is intentionally headless
 * about layout — the caller (App or LoginPage) wraps it in the appropriate
 * container.
 */
export interface AuthFormProps {
  failed: boolean;
  onSecret: (secret: string) => void;
  /** Optional title override (defaults to i18n `app.auth.title`). */
  title?: React.ReactNode;
  /** Optional hint override (defaults to i18n `app.auth.hint`). */
  hint?: React.ReactNode;
}

export function AuthForm({ failed, onSecret, title, hint }: AuthFormProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) return;
    setSubmitting(true);
    onSecret(secret);
  };

  return (
    <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <p className="text-lg font-semibold">{title ?? t("app.auth.title")}</p>
        <p className="text-sm text-muted-foreground">{hint ?? t("app.auth.hint")}</p>
      </div>
      {failed && (
        <p className="text-center text-sm text-destructive">
          {t("app.auth.invalid")}
        </p>
      )}
      <Input
        type="password"
        placeholder={t("app.auth.placeholder")}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={submitting}
        autoFocus
      />
      <Button
        type="submit"
        className="w-full"
        disabled={!value.trim() || submitting}
      >
        {t("app.auth.submit")}
      </Button>
    </form>
  );
}

export default AuthForm;
