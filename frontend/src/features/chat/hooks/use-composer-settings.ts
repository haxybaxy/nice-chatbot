import { useCallback, useState } from "react";

import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { storage } from "@/shared/services/local-storage";

import type { ChatModel, RunMode, RunRequestOptions } from "../types";

/**
 * The composer's remembered choices — a client-only shape persisted in localStorage
 * (`STORAGE_KEYS.CHAT_COMPOSER`), never sent as-is: `toRunRequestOptions` maps it onto
 * `CreateMessageIn`'s `model` / `mode` / `tools`, each toggle ANDed with what the resolved model
 * offers (`effectiveTools`).
 */
export interface ComposerSettings {
  /** A `ModelOut.id`, or `null` for the catalog's default. */
  model: string | null;
  mode: RunMode;
  /** On by default: the model decides when a question needs the web. */
  webSearch: boolean;
  code: boolean;
}

const DEFAULTS: ComposerSettings = { model: null, mode: "chat", webSearch: true, code: false };

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
export function resolveModel(
  settings: Pick<ComposerSettings, "model">,
  models: readonly ChatModel[]
): ChatModel | undefined {
  return (
    models.find((model) => model.id === settings.model) ??
    models.find((model) => model.isDefault) ??
    models[0]
  );
}

/** `CreateMessageIn.tools` with both fields decided. */
type EffectiveTools = Required<NonNullable<RunRequestOptions["tools"]>>;

/**
 * The toggles as they count: a capability the resolved model does not offer (`ModelOut.webSearch`,
 * `ModelOut.code` — the server's catalog decides both) is never sent as `true`, whatever the
 * remembered toggle says. Without a resolved model (the catalog is still loading) the raw
 * settings stand.
 */
export function effectiveTools(
  settings: Pick<ComposerSettings, "webSearch" | "code">,
  model: ChatModel | undefined
): EffectiveTools {
  return {
    webSearch: settings.webSearch && (model?.webSearch ?? true),
    code: settings.code && (model?.code ?? true),
  };
}

/** Exactly the run fields of `CreateMessageIn` (`extra="forbid"` on the backend). */
export function toRunRequestOptions(
  settings: ComposerSettings,
  models: readonly ChatModel[]
): RunRequestOptions {
  const model = resolveModel(settings, models);
  return {
    model: model?.id ?? null,
    mode: settings.mode,
    tools: effectiveTools(settings, model),
  };
}
