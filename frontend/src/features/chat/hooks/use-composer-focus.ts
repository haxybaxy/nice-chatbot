import { useCallback, useEffect, useRef } from "react";

import { useIsMobile } from "@/shared/hooks/use-mobile";

/**
 * The composer textarea's focus, as ChatGPT handles it: taken when the composer mounts — not on
 * a phone, where that would open the keyboard — and given back after a send or a stop, so the
 * next message can be typed straight away instead of the send button keeping it.
 */
export function useComposerFocus() {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    if (!isMobile) {
      textareaRef.current?.focus();
    }
  }, [isMobile]);

  const focus = useCallback(() => textareaRef.current?.focus(), []);

  return { textareaRef, focus };
}
