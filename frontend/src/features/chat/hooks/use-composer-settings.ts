import { useCallback, useState } from "react";

import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

import type { ChatModel, RunMode, RunRequestOptions } from "../types";

/**
 * The composer's remembered choices — a client-only shape persisted in localStorage
 * (`STORAGE_KEYS.CHAT_COMPOSER`), never sent as-is: `toRunRequestOptions` maps it onto
 * `CreateMessageIn`'s `model` / `mode` / `tools`.
 */
export interface ComposerSettings {
  /** A `ModelOut.id`, or `null` for the catalog's default. */
  model: string | null;
  mode: RunMode;
  webSearch: boolean;
  code: boolean;
}

const DEFAULTS: ComposerSettings = { model: null, mode: "chat", webSearch: false, code: false };

/** Merge what storage holds over the defaults, field by field, ignoring anything malformed. */
function readStoredSettings(): ComposerSettings {
  const stored = storage.get<Partial<Record<keyof ComposerSettings, unknown>>>(
    STORAGE_KEYS.CHAT_COMPOSER
  );
  if (!stored) {
    return DEFAULTS;
  }
  return {
    model: typeof stored.model === "string" ? stored.model : DEFAULTS.model,
    mode: stored.mode === "deep_research" ? "deep_research" : DEFAULTS.mode,
    webSearch: typeof stored.webSearch === "boolean" ? stored.webSearch : DEFAULTS.webSearch,
    code: typeof stored.code === "boolean" ? stored.code : DEFAULTS.code,
  };
}

export function useComposerSettings(): [
  ComposerSettings,
  (patch: Partial<ComposerSettings>) => void,
] {
  const [settings, setSettings] = useState<ComposerSettings>(readStoredSettings);
  const update = useCallback((patch: Partial<ComposerSettings>) => {
    setSettings((previous) => {
      const next = { ...previous, ...patch };
      storage.set(STORAGE_KEYS.CHAT_COMPOSER, next);
      return next;
    });
  }, []);
  return [settings, update];
}

/** The chosen model while the catalog still lists it, else the catalog's default, else its first entry. */
export function resolveModelId(
  settings: Pick<ComposerSettings, "model">,
  models: readonly ChatModel[]
): string | null {
  return (
    models.find((model) => model.id === settings.model)?.id ??
    models.find((model) => model.isDefault)?.id ??
    models[0]?.id ??
    null
  );
}

/** Exactly the run fields of `CreateMessageIn` (`extra="forbid"` on the backend). */
export function toRunRequestOptions(
  settings: ComposerSettings,
  models: readonly ChatModel[]
): RunRequestOptions {
  return {
    model: resolveModelId(settings, models),
    mode: settings.mode,
    tools: { webSearch: settings.webSearch, code: settings.code },
  };
}
