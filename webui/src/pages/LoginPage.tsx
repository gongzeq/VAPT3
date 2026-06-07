import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  Bug,
  Eye,
  EyeOff,
  FileCheck2,
  KeyRound,
  Loader2,
  LogIn,
  Radar,
  Shield,
  ShieldCheck,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BootStatus } from "@/components/ProtectedRoute";

/** @description Props for the login page component. */
export interface LoginPageProps {
  state: BootStatus;
  onSecret: (secret: string) => void;
}

/**
 * Resolve the post-login destination from `?next=` while honoring template
 * §7.1 redirect-protection rule: only relative paths are allowed.
 */
function resolveNext(search: string): string {
  const next = new URLSearchParams(search).get("next");
  if (!next) return "/";
  if (!next.startsWith("/")) return "/";
  if (next.startsWith("//")) return "/";
  return next;
}

/**
 * /login — 粤海智盾登录页。严格对齐 prototypes/01-login.html 双栏设计：
 *   - 左栏（lg+）：banner 装饰 + 网格叠加 + 品牌标语 + 4 特性卡；底部空位
 *     （prototype 明确注释「公司名称已移除」）。
 *   - 右栏：居中单卡片，gradient-card + border-glow，shield-glow 图标徽章，
 *     带眼睛切换的密钥输入、"记住 7 天"勾选、"忘记密钥?"链接、登录按钮。
 *   - 移动端（<lg）：左栏隐藏，右栏顶部浮动 mobile brand 小 logo。
 */
export function LoginPage({ state, onSecret }: LoginPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (state.status === "ready") {
      navigate(resolveNext(location.search), { replace: true });
    }
  }, [state.status, location.search, navigate]);

  const loading = state.status === "loading";
  const failed = state.status === "auth" && Boolean(state.failed);

  useEffect(() => {
    if (failed) setSubmitting(false);
  }, [failed]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) return;
    setSubmitting(true);
    onSecret(secret);
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading…</span>
        </div>
      </div>
    );
  }

  return (
    <main className="grid min-h-screen overflow-hidden lg:grid-cols-[1.3fr_1fr]">
      {/* ── 左栏：纯 CSS 海蓝科技背景 + 平台介绍 ─────────────────── */}
      <section
        className="relative hidden flex-col justify-between overflow-hidden p-12 lg:flex"
        style={{
          backgroundColor: "hsl(222 47% 6%)",
          backgroundImage: [
            "radial-gradient(120% 90% at 12% -10%, hsl(210 100% 30% / 0.50) 0%, transparent 55%)",
            "radial-gradient(100% 80% at 88% 110%, hsl(189 94% 56% / 0.22) 0%, transparent 52%)",
            "radial-gradient(90% 70% at 50% 130%, hsl(210 92% 38% / 0.42) 0%, transparent 60%)",
            "linear-gradient(135deg, hsl(222 47% 6%) 0%, hsl(214 58% 9%) 55%, hsl(210 70% 12%) 100%)",
          ].join(", "),
        }}
      >
        {/* 网格叠加 */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "linear-gradient(hsl(210 100% 56% / 0.08) 1px, transparent 1px), linear-gradient(90deg, hsl(210 100% 56% / 0.08) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
            maskImage:
              "radial-gradient(120% 100% at 30% 20%, black 30%, transparent 80%)",
            WebkitMaskImage:
              "radial-gradient(120% 100% at 30% 20%, black 30%, transparent 80%)",
          }}
        />

        {/* 柔光球点缀 — 科技感氛围层 */}
        <div
          aria-hidden
          className="pointer-events-none absolute -left-20 -top-24 h-72 w-72 rounded-full blur-3xl"
          style={{ background: "radial-gradient(circle, hsl(210 100% 56% / 0.35), transparent 70%)" }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-28 right-[-10%] h-80 w-80 rounded-full blur-3xl"
          style={{ background: "radial-gradient(circle, hsl(189 94% 56% / 0.22), transparent 70%)" }}
        />

        {/* 顶部品牌 */}
        <div className="relative z-10 animate-fade-in-up space-y-4">
          <div className="flex items-center gap-3">
            <img
              src="/brand/logo.png"
              alt="logo"
              className="h-11 w-11 rounded-xl shadow-[0_0_0_4px_hsl(var(--primary)/0.18)]"
            />
            <span className="brand-zh brand-zh-hero leading-tight text-[26px]">粤海智盾</span>
          </div>
          <p className="text-sm text-white/60">多智能体网络安全协作系统</p>
          <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-1.5 text-xs font-medium text-white/85 backdrop-blur">
            <ShieldCheck className="h-3.5 w-3.5" />
            全栈漏洞检测 · AI 智能体协同
          </span>
        </div>

        {/* 中部主标语 */}
        <div className="relative z-10 max-w-lg animate-fade-in-up space-y-6">
          <h1 className="whitespace-nowrap text-5xl font-bold leading-tight text-white">
            以<span className="text-gradient">智能驱动</span>守护资产安全
          </h1>
          <p className="text-lg leading-relaxed text-white/75">
            资产发现 · 端口扫描 · 漏洞检测 · 报告生成 全流程贯通<br />黑板共享 + 高危确认 + 审计留痕   安全能力开箱即用
          </p>

          {/* 4 个特性卡 */}
          <div className="grid grid-cols-2 gap-3 pt-2">
            {[
              { icon: Radar, title: "实时资产发现", sub: "CMDB + 子网爬取并行调度" },
              { icon: Bug, title: "智能漏洞检测", sub: "CVE 知识库 + 规则引擎" },
              { icon: Users, title: "多智能体协作", sub: "Orchestrator + 6 类专家" },
              { icon: FileCheck2, title: "一键合规报告", sub: "PDF / Markdown / JSON 多格式" },
            ].map(({ icon: Icon, title, sub }) => (
              <div
                key={title}
                className="bg-glass card-hover-glow rounded-xl border border-white/8 p-4"
              >
                <div className="flex items-center gap-2.5 text-sm font-semibold text-white">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-primary/15">
                    <Icon className="h-3.5 w-3.5 text-primary" />
                  </span>
                  {title}
                </div>
                <p className="mt-1 pl-[2.125rem] text-xs text-white/55">{sub}</p>
              </div>
            ))}
          </div>
        </div>

        {/* 底部预留位（公司名称已移除） */}
        <div className="relative z-10" />
      </section>

      {/* ── 右栏：登录表单 ────────────────────────────────────── */}
      <section className="relative flex items-center justify-center bg-background p-6 lg:p-12">
        {/* 移动端品牌 */}
        <div className="absolute left-6 top-6 flex items-center gap-2 lg:hidden">
          <img src="/brand/logo.png" alt="logo" className="h-9 w-9 rounded-lg" />
        </div>

        <div className="w-full max-w-md animate-slide-in-right space-y-8">
          {/* 标题 */}
          <div className="space-y-3 text-center">
            <div className="animate-pulse-glow mx-auto flex h-14 w-14 items-center justify-center rounded-2xl shadow-glow bg-[image:var(--gradient-primary)]">
              <Shield className="h-7 w-7 text-white" />
            </div>
            <h2 className="text-3xl font-bold">欢迎回来</h2>
            <p className="text-sm text-muted-foreground">
              使用平台共享密钥 (shared secret) 登录
            </p>
          </div>

          {/* 表单卡片 */}
          <form
            onSubmit={handleSubmit}
            className="border-glow space-y-5 rounded-2xl p-7 bg-[image:var(--gradient-card)]"
          >
            {failed && (
              <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm">
                <AlertCircle className="mt-0.5 h-4 w-4 text-destructive" />
                <div>
                  <p className="font-medium text-destructive">密钥校验失败</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    请确认密钥拼写正确，或联系平台管理员重新签发。
                  </p>
                </div>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">
                共享密钥 <span className="text-destructive">*</span>
              </label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <input
                  type={visible ? "text" : "password"}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  disabled={submitting}
                  autoFocus
                  placeholder="请输入共享密钥"
                  className="focus-ring-primary w-full rounded-lg border border-border/60 bg-muted/40 py-2.5 pl-9 pr-10 font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => setVisible((v) => !v)}
                  className="absolute right-3 top-3 text-muted-foreground transition hover:text-primary"
                  aria-label={visible ? "隐藏密钥" : "显示密钥"}
                >
                  {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">
                密钥仅在浏览器本地存储，不会上传第三方服务。
              </p>
            </div>

            <label className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-muted-foreground">
                <input
                  type="checkbox"
                  defaultChecked
                  className="rounded border-border bg-muted text-primary focus:ring-primary/40"
                />
                记住此设备 7 天
              </span>
              <a
                href="#"
                onClick={(e) => e.preventDefault()}
                className="text-primary transition hover:text-primary/80"
              >
                忘记密钥？
              </a>
            </label>

            <Button
              type="submit"
              disabled={!value.trim() || submitting}
              className="group w-full gap-2 shadow-[0_4px_20px_hsl(var(--primary)/0.35)] transition-all duration-200 hover:shadow-[0_6px_28px_hsl(var(--primary)/0.5)] hover:scale-[1.01] active:scale-[0.99] bg-[image:var(--gradient-primary)]"
            >
              <LogIn className="h-4 w-4" />
              {submitting ? "验证中…" : "登录控制台"}
              <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}

export default LoginPage;
