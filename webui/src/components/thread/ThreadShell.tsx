import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Database } from "lucide-react";

import { AskUserPrompt } from "@/components/thread/AskUserPrompt";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { CumulativeUsageBar } from "@/components/TokenUsageBadge";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { QuickPrompts } from "@/components/QuickPrompts";
import { Switch } from "@/components/ui/switch";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import {
  fetchAssetAutoManagement,
  listSlashCommands,
  setAssetAutoManagement,
} from "@/lib/api";
import type { ChatSummary, SlashCommand, UIMessage } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

interface ThreadShellProps {
  session: ChatSummary | null;
  title: string;
  onToggleSidebar: () => void;
  onGoHome?: () => void;
  onNewChat?: () => void;
  onCreateChat?: () => Promise<string | null>;
  onTurnEnd?: () => void;
  onOpenSettings?: () => void;
  hideSidebarToggleOnDesktop?: boolean;
  onToggleRightRail?: () => void;
  rightRailOpen?: boolean;
}

function toModelBadgeLabel(modelName: string | null): string | null {
  if (!modelName) return null;
  const trimmed = modelName.trim();
  if (!trimmed) return null;
  const leaf = trimmed.split("/").pop() ?? trimmed;
  return leaf || trimmed;
}

// Quick-action definitions removed — no longer rendered by this
// shell. Re-introduce alongside the UI if/when hero actions come back.

/** @description Main chat shell with message list, composer, and sidebar toggle. */
export function ThreadShell({
  session,
  title,
  onToggleSidebar,
  onCreateChat,
  onTurnEnd,
  onOpenSettings = () => {},
  hideSidebarToggleOnDesktop = false,
  onToggleRightRail,
  rightRailOpen,
}: ThreadShellProps) {
  // Props kept for backwards-compat with callers; not yet consumed by
  // this shell. Silence ``noUnusedParameters`` without altering the
  // public interface.
  void title;
  void onToggleSidebar;
  void onOpenSettings;
  void hideSidebarToggleOnDesktop;
  void onToggleRightRail;
  void rightRailOpen;
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
  const historyKey = session?.key ?? null;
  const { messages: historical, loading } = useSessionHistory(historyKey);
  const { client, modelName, token } = useClient();
  const [booting, setBooting] = useState(false);
  const [assetAutoManagement, setAssetAutoManagementState] = useState(false);
  const [assetAutoManagementBusy, setAssetAutoManagementBusy] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const pendingFirstRef = useRef<string | null>(null);
  const messageCacheRef = useRef<Map<string, UIMessage[]>>(new Map());
  const lastCachedChatIdRef = useRef<string | null>(null);

  const initial = useMemo(() => {
    if (!chatId) return historical;
    return messageCacheRef.current.get(chatId) ?? historical;
  }, [chatId, historical]);
  const {
    messages,
    isStreaming,
    send,
    setMessages,
    streamError,
    dismissStreamError,
    cumulativeUsage,
  } = useNanobotStream(chatId, initial, onTurnEnd);
  const showHeroComposer = messages.length === 0 && !loading;
  const pendingAsk = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.kind === "trace") continue;
      if (message.role === "user") return null;
      if (message.role === "assistant" && message.buttons?.some((row) => row.length > 0)) {
        return {
          question: message.content,
          buttons: message.buttons,
          variant: (message.promptKind === "approval" ? "approval" : "question") as "question" | "approval",
          detail: message.approvalDetail as string | undefined,
          askId: message.askId as string | undefined,
        };
      }
      if (message.role === "assistant") return null;
    }
    return null;
  }, [messages]);

  useEffect(() => {
    if (!chatId || loading) return;
    const cached = messageCacheRef.current.get(chatId);
    // When the user switches away and back, keep the local in-memory thread
    // state (including not-yet-persisted messages) instead of replacing it with
    // whatever the history endpoint currently knows about.
    setMessages(cached && cached.length > 0 ? cached : historical);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, chatId, historical]);

  useEffect(() => {
    if (chatId) return;
    setMessages(historical);
  }, [chatId, historical, setMessages]);

  useLayoutEffect(() => {
    if (!chatId) {
      lastCachedChatIdRef.current = null;
      return;
    }
    if (loading) return;
    // Skip the first cache write after a chat switch. During that render,
    // `messages` can still belong to the previous chat until the stream hook
    // resets its local state for the new session.
    if (lastCachedChatIdRef.current !== chatId) {
      lastCachedChatIdRef.current = chatId;
      if (messages.length > 0) {
        messageCacheRef.current.set(chatId, messages);
      }
      return;
    }
    messageCacheRef.current.set(chatId, messages);
  }, [chatId, loading, messages]);

  useEffect(() => {
    if (!chatId) return;
    const pending = pendingFirstRef.current;
    if (!pending) return;
    pendingFirstRef.current = null;
    // Route through ``send`` (instead of calling ``client.sendMessage``
    // directly) so it pushes the user bubble AND flips ``isStreaming`` to
    // ``true`` — without that flip the composer's Stop button stays hidden
    // until the first ``delta`` arrives, which is never for turns whose
    // opening action is a tool call.
    send(pending);
    setBooting(false);
  }, [chatId, send]);

  useEffect(() => {
    if (!historyKey) {
      setAssetAutoManagementState(false);
      return;
    }
    let cancelled = false;
    fetchAssetAutoManagement(token, historyKey)
      .then((state) => {
        if (!cancelled) {
          setAssetAutoManagementState(Boolean(state.asset_auto_management));
        }
      })
      .catch(() => {
        if (!cancelled) setAssetAutoManagementState(false);
      });
    return () => {
      cancelled = true;
    };
  }, [historyKey, token]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const commands = await listSlashCommands(token);
        if (!cancelled) setSlashCommands(commands);
      } catch {
        if (!cancelled) setSlashCommands([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleWelcomeSend = useCallback(
    async (content: string) => {
      if (booting) return;
      setBooting(true);
      pendingFirstRef.current = content;
      const newId = await onCreateChat?.();
      if (!newId) {
        pendingFirstRef.current = null;
        setBooting(false);
      }
    },
    [booting, onCreateChat],
  );

  const handleAssetAutoManagementChange = useCallback(
    (enabled: boolean) => {
      if (!historyKey || assetAutoManagementBusy) return;
      const previous = assetAutoManagement;
      setAssetAutoManagementState(enabled);
      setAssetAutoManagementBusy(true);
      setAssetAutoManagement(token, historyKey, enabled)
        .then((state) => {
          setAssetAutoManagementState(Boolean(state.asset_auto_management));
        })
        .catch(() => {
          setAssetAutoManagementState(previous);
        })
        .finally(() => {
          setAssetAutoManagementBusy(false);
        });
    },
    [assetAutoManagement, assetAutoManagementBusy, historyKey, token],
  );


  const composer = (
    <>
      {streamError ? (
        <StreamErrorNotice
          error={streamError}
          onDismiss={dismissStreamError}
        />
      ) : null}
      <CumulativeUsageBar usage={cumulativeUsage} />
      {session ? (
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between rounded-lg border border-border/70 bg-card/55 px-3 py-2 text-sm">
          <div className="flex min-w-0 items-center gap-2">
            <Database className="h-4 w-4 shrink-0 text-primary" />
            <span className="truncate text-foreground">纳管资产</span>
            <span className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
              {assetAutoManagement ? "开启" : "关闭"}
            </span>
          </div>
          <Switch
            checked={assetAutoManagement}
            disabled={assetAutoManagementBusy}
            onCheckedChange={handleAssetAutoManagementChange}
            aria-label="纳管资产"
          />
        </div>
      ) : null}
      {pendingAsk ? (
        <AskUserPrompt
          question={pendingAsk.question}
          buttons={pendingAsk.buttons}
          variant={pendingAsk.variant}
          detail={pendingAsk.detail}
          onAnswer={(answer: string) => {
            // Route approval decisions through scan.user_reply so the
            // backend's surface_confirm Future resolves. Regular question
            // answers still go through the normal message path.
            if (pendingAsk.askId && pendingAsk.variant === "approval") {
              const decision = answer.toLowerCase().includes("approve")
                ? "approve"
                : answer.toLowerCase().includes("deny")
                  ? "deny"
                  : answer;
              if (decision === "approve" || decision === "deny") {
                client.sendUserReply(pendingAsk.askId, decision);
                return;
              }
            }
            send(answer);
          }}
        />
      ) : null}
      {session ? (
        <ThreadComposer
          onSend={send}
          onStop={chatId ? () => client.stopChat(chatId) : undefined}
          disabled={!chatId}
          isStreaming={isStreaming}
          placeholder={
            showHeroComposer
              ? t("thread.composer.placeholderHero")
              : t("thread.composer.placeholderThread")
          }
          modelLabel={toModelBadgeLabel(modelName)}
          variant={showHeroComposer ? "hero" : "thread"}
          slashCommands={slashCommands}
        />
      ) : (
        <ThreadComposer
          onSend={handleWelcomeSend}
          disabled={booting}
          isStreaming={isStreaming}
          placeholder={
            booting
              ? t("thread.composer.placeholderOpening")
              : t("thread.composer.placeholderHero")
          }
          modelLabel={toModelBadgeLabel(modelName)}
          variant="hero"
        />
      )}
    </>
  );

  const emptyState = loading ? (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      {t("thread.loadingConversation")}
    </div>
  ) : (
    <>
      <div className="flex flex-col items-center justify-center gap-4 pt-2 animate-fade-in-up">
        {/* 品牌 logo — 与左上角 Navbar 一致 */}
        <div className="relative">
          <span
            aria-hidden
            className="absolute inset-0 -z-10 rounded-3xl bg-primary/25 blur-2xl"
          />
          <img
            src="/brand/logo.png"
            alt=""
            className="relative h-20 w-20 rounded-3xl ring-1 ring-primary/25 shadow-glow"
          />
        </div>
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="brand-zh brand-zh-hero text-3xl">粤海智盾</span>
          <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
            {t("home.hero.tagline", {
              defaultValue: "AI 驱动的智能安全运营平台 · 资产·漏洞·合规一体化",
            })}
          </p>
        </div>
      </div>
      <QuickPrompts className="w-full" />
    </>
  );

  return (
    <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <ThreadViewport
        messages={messages}
        isStreaming={isStreaming}
        emptyState={emptyState}
        composer={composer}
        resetKey={chatId}
      />
    </section>
  );
}
