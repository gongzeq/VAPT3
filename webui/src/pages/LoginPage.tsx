import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { Loader2, ShieldCheck, Sparkles, Waves } from "lucide-react";
import { AuthForm } from "@/components/AuthForm";
import type { BootStatus } from "@/components/ProtectedRoute";

export interface LoginPageProps {
  state: BootStatus;
  onSecret: (secret: string) => void;
}

/**
 * Resolve the post-login destination from `?next=` while honoring template
 * §7.1 redirect-protection rule: only relative paths are allowed, never
 * protocol-relative URLs (`//evil.com`) or absolute origins. Returns "/" by
 * default.
 */
function resolveNext(search: string): string {
  const next = new URLSearchParams(search).get("next");
  if (!next) return "/";
  if (!next.startsWith("/")) return "/";
  if (next.startsWith("//")) return "/";
  return next;
}

/**
 * /login — template §7.1 two-column hero.
 *
 * Left:  decorative banner (banner.jpg) + brand strap, hidden on small
 *        screens so the form never gets squeezed off-viewport.
 * Right: centered card with <AuthForm/> (bootstrap secret).
 *
 * The form itself lives in <AuthForm/> so PR3's wiring is preserved
 * byte-for-byte; PR4 only swaps the surrounding shell.
 */
export function LoginPage({ state, onSecret }: LoginPageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  // When auth completes, bounce to the requested target (or "/" by default).
  useEffect(() => {
    if (state.status !== "ready") return;
    navigate(resolveNext(location.search), { replace: true });
  }, [state, location.search, navigate]);

  const failed = state.status === "auth" && !!state.failed;
  const loading = state.status === "loading";

  return (
    <div className="relative flex min-h-screen w-full bg-background">
      {/* Left hero — hidden on small screens (lg breakpoint matches template). */}
      <aside
        className="relative hidden w-1/2 flex-col justify-between overflow-hidden p-10 lg:flex"
        aria-hidden="true"
      >
        {/* Background image + dark overlay so the foreground copy stays readable. */}
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: "url(/brand/banner.jpg)" }}
        />
        <div className="absolute inset-0 bg-gradient-to-br from-background/90 via-background/60 to-background/85" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,hsl(var(--ocean-500)/0.25),transparent_55%)]" />

        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/15 text-primary border border-primary/30">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-foreground">
              {t("app.brand", { defaultValue: "海盾智能体管控台" })}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("app.brandTagline", {
                defaultValue: "secbot · vulnerability orchestration",
              })}
            </p>
          </div>
        </div>

        <div className="relative space-y-4">
          <h1 className="text-3xl font-semibold leading-tight text-foreground">
            {t("login.hero.title", {
              defaultValue: "对话式驱动的漏洞检测协作平台",
            })}
          </h1>
          <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
            {t("login.hero.subtitle", {
              defaultValue:
                "通过自然语言下达任务，主智能体自动编排资产发现、端口扫描、漏洞验证与修复建议，全流程透明可追溯。",
            })}
          </p>
          <ul className="grid grid-cols-1 gap-3 pt-2 sm:grid-cols-2">
            <li className="flex items-start gap-2 text-xs text-muted-foreground">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                {t("login.hero.bullet1", {
                  defaultValue: "多智能体黑板协作，任务进度实时可见",
                })}
              </span>
            </li>
            <li className="flex items-start gap-2 text-xs text-muted-foreground">
              <Waves className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                {t("login.hero.bullet2", {
                  defaultValue: "海蓝设计令牌 + 玻璃拟态，长时凝视零疲劳",
                })}
              </span>
            </li>
            <li className="flex items-start gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                {t("login.hero.bullet3", {
                  defaultValue: "扫描动作显式审计，敏感操作二次确认",
                })}
              </span>
            </li>
            <li className="flex items-start gap-2 text-xs text-muted-foreground">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                {t("login.hero.bullet4", {
                  defaultValue: "结果聚合为 Finding，配套 PoC 与修复建议",
                })}
              </span>
            </li>
          </ul>
        </div>

        <p className="relative text-[11px] text-muted-foreground/70">
          © {new Date().getFullYear()} secbot ·{" "}
          {t("login.hero.legal", { defaultValue: "海盾自研，遵循内部安全审批" })}
        </p>
      </aside>

      {/* Right — centered card. */}
      <main className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm space-y-5 rounded-lg border border-border bg-card p-8 shadow-sm">
          <header className="space-y-1">
            <h2 className="text-xl font-semibold text-foreground">
              {t("login.card.title", { defaultValue: "登录控制台" })}
            </h2>
            <p className="text-sm text-muted-foreground">
              {t("login.card.subtitle", {
                defaultValue: "使用 secbot 引导密钥访问海盾管控台。",
              })}
            </p>
          </header>

          {failed && (
            <div
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
            >
              {t("app.auth.invalid", { defaultValue: "密钥校验失败，请重试。" })}
            </div>
          )}

          {loading ? (
            <div
              className="flex items-center justify-center gap-2 rounded-md border border-border/40 bg-background/40 py-4 text-sm text-muted-foreground"
              role="status"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>
                {t("login.card.loading", { defaultValue: "正在校验会话…" })}
              </span>
            </div>
          ) : (
            <AuthForm
              failed={failed}
              onSecret={onSecret}
              hideHeader
              hideFailedNotice
            />
          )}
        </div>
      </main>
    </div>
  );
}

export default LoginPage;
