import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "./api";
import {
  mergeConversations,
  normalizeConversations,
  type Conversation,
} from "./conversations";

export type ConversationSyncState = "syncing" | "synced" | "local";

export function useConversationSync(
  userId: string,
  conversations: Conversation[],
  setConversations: Dispatch<SetStateAction<Conversation[]>>,
) {
  const [syncState, setSyncState] = useState<ConversationSyncState>("syncing");
  const hydratedRef = useRef(false);
  const pendingDeletesRef = useRef(new Set<string>());
  const saveTimerRef = useRef<number | null>(null);

  const retryDeletes = useCallback(async () => {
    const ids = [...pendingDeletesRef.current];
    await Promise.all(ids.map(async (id) => {
      await api.conversations.delete(id);
      pendingDeletesRef.current.delete(id);
    }));
  }, []);

  const refresh = useCallback(async () => {
    setSyncState("syncing");
    try {
      await retryDeletes();
      const remote = normalizeConversations(await api.conversations.list())
        .filter((conversation) => !pendingDeletesRef.current.has(conversation.id));
      setConversations((current) => {
        const meaningfulLocal = current.filter(
          (conversation) => conversation.turns.length > 0 || remote.length === 0,
        );
        return mergeConversations(meaningfulLocal, remote);
      });
      hydratedRef.current = true;
      setSyncState("synced");
    } catch {
      hydratedRef.current = true;
      setSyncState("local");
    }
  }, [retryDeletes, setConversations]);

  const deleteRemote = useCallback(async (conversationId: string) => {
    pendingDeletesRef.current.add(conversationId);
    try {
      await api.conversations.delete(conversationId);
      pendingDeletesRef.current.delete(conversationId);
      setSyncState("synced");
    } catch {
      setSyncState("local");
    }
  }, []);

  useEffect(() => {
    hydratedRef.current = false;
    pendingDeletesRef.current.clear();
    void refresh();
  }, [refresh, userId]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(async () => {
      const meaningful = conversations.filter(
        (conversation) => conversation.turns.length > 0
          && !pendingDeletesRef.current.has(conversation.id),
      );
      if (meaningful.length === 0) return;
      setSyncState("syncing");
      try {
        await Promise.all(meaningful.map(api.conversations.save));
        setSyncState("synced");
      } catch {
        setSyncState("local");
      }
    }, 400);
    return () => {
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, [conversations]);

  useEffect(() => {
    function refreshWhenActive() {
      if (document.visibilityState === "visible") void refresh();
    }
    window.addEventListener("focus", refreshWhenActive);
    window.addEventListener("online", refreshWhenActive);
    document.addEventListener("visibilitychange", refreshWhenActive);
    return () => {
      window.removeEventListener("focus", refreshWhenActive);
      window.removeEventListener("online", refreshWhenActive);
      document.removeEventListener("visibilitychange", refreshWhenActive);
    };
  }, [refresh]);

  return { syncState, refresh, deleteRemote };
}
