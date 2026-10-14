import { createFormHookContexts } from "@tanstack/react-form";

/**
 * The contexts `createFormHook` (index.ts) binds the field and form components to:
 * `useFieldContext` / `useFormContext` are what those components read their state from.
 */
export const { fieldContext, formContext, useFieldContext, useFormContext } =
  createFormHookContexts();
