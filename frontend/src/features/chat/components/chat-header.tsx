import type { ReactNode } from "react";
import { useEffect } from "react";

import { SidebarTrigger } from "@/shared/components/ui/sidebar";
import { APP_NAME } from "@/shared/constants/app";

interface ChatHeaderProps {
  /** The conversation's title: the browser tab's, and the page heading for assistive tech. */
  title: string;
  /** What sits next to the sidebar toggle — the model picker. */
  children?: ReactNode;
}

/**
 * The bar above a thread, laid out like ChatGPT's: the sidebar toggle (the only way in on
 * mobile) and the model picker. The title is not displayed in it — it is the browser tab's
 * title and the sidebar's highlighted row — but stays the page's heading for screen readers.
 */
export function ChatHeader({ title, children }: ChatHeaderProps) {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
    return () => {
      document.title = APP_NAME;
    };
  }, [title]);

  return (
    <header className="flex h-13 shrink-0 items-center gap-1 px-3">
      <SidebarTrigger />
      {children}
      <h1 className="sr-only">{title}</h1>
    </header>
  );
}
