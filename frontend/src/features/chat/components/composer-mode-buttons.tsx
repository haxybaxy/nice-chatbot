import { CodeIcon, GlobeIcon, MessageSquareIcon, TelescopeIcon } from "lucide-react";

import { PromptInputButton } from "@/shared/components/ai-elements/prompt-input";

import type { ComposerSettings } from "../hooks/use-composer-settings";
import type { RunMode } from "../types";

const MODES: readonly { mode: RunMode; label: string; icon: typeof MessageSquareIcon }[] = [
  { mode: "chat", label: "Chat", icon: MessageSquareIcon },
  { mode: "deep_research", label: "Deep research", icon: TelescopeIcon },
];

interface ComposerModeButtonsProps {
  settings: ComposerSettings;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
}

/** Chat / Deep research, then the Search and Code toggles (Chat mode only). */
export function ComposerModeButtons({ settings, onSettingsChange }: ComposerModeButtonsProps) {
  return (
    <>
      <div role="group" aria-label="Mode" className="flex items-center">
        {MODES.map(({ mode, label, icon: Icon }) => (
          <PromptInputButton
            key={mode}
            type="button"
            aria-pressed={settings.mode === mode}
            variant={settings.mode === mode ? "secondary" : "ghost"}
            onClick={() => onSettingsChange({ mode })}
          >
            <Icon />
            {label}
          </PromptInputButton>
        ))}
      </div>
      {settings.mode === "chat" && (
        <>
          <PromptInputButton
            type="button"
            aria-pressed={settings.webSearch}
            variant={settings.webSearch ? "secondary" : "ghost"}
            onClick={() => onSettingsChange({ webSearch: !settings.webSearch })}
          >
            <GlobeIcon />
            Search
          </PromptInputButton>
          <PromptInputButton
            type="button"
            aria-pressed={settings.code}
            variant={settings.code ? "secondary" : "ghost"}
            onClick={() => onSettingsChange({ code: !settings.code })}
          >
            <CodeIcon />
            Code
          </PromptInputButton>
        </>
      )}
    </>
  );
}
