import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { ROUTES } from "@/shared/constants/routes";

/** What the "New chat" row shows and what the hook listens for: ChatGPT's own shortcut. */
export const NEW_CHAT_SHORTCUT = "⌘⇧O";

/** `⌘⇧O` (`Ctrl+Shift+O` elsewhere) opens a new chat in the current team, as in ChatGPT. */
export function useNewChatShortcut(teamId: string): void {
  const navigate = useNavigate();
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        navigate(ROUTES.app.teamChat(teamId));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, teamId]);
}
