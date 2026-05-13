import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { AskUserPrompt } from "@/components/thread/AskUserPrompt";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import { listSlashCommands } from "@/lib/api";
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


  const composer = (
    <>
      {streamError ? (
        <StreamErrorNotice
          error={streamError}
          onDismiss={dismissStreamError}
        />
      ) : null}
      {pendingAsk ? (
        <AskUserPrompt
          question={pendingAsk.question}
          buttons={pendingAsk.buttons}
          onAnswer={send}
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
    <div className="flex flex-col items-center justify-center">
      <img
        src="/brand/text-logo.png"
        alt="VAPT"
        className="h-10 w-auto opacity-90"
        draggable={false}
      />
    </div>
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
