import { Separator } from "@/shared/components/ui/separator";
import { SidebarTrigger } from "@/shared/components/ui/sidebar";

/** The thin bar above a thread: the sidebar toggle (the only way in on mobile) and the title. */
export function ChatHeader({ title }: { title: string }) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger />
      <Separator orientation="vertical" className="h-4" />
      <h1 className="truncate text-sm font-medium">{title}</h1>
    </header>
  );
}
