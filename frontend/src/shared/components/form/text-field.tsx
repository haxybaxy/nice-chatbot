import { useSelector } from "@tanstack/react-form";
import type * as React from "react";

import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";

import { useFieldContext } from "./contexts";

interface TextFieldProps extends Omit<
  React.ComponentProps<"input">,
  "id" | "name" | "value" | "onChange" | "onBlur"
> {
  label: string;
  /** Defaults to the field's name. */
  id?: string;
}

/**
 * The message of a validation error entry, whatever the validator produced: a Standard Schema
 * issue (zod) or a bare string. A named structural probe on a foreign object — the sanctioned
 * kind of hand-written shape (CLAUDE.md → Conventions → Generated API types).
 */
function errorMessage(error: unknown): string | undefined {
  if (typeof error === "string") {
    return error;
  }
  if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message;
  }
  return undefined;
}

/**
 * A labelled input bound to the enclosing `form.AppField`: value, change/blur handlers, the
 * first validation message (wired up through `aria-invalid` / `aria-describedby`) and a disabled
 * state while the form submits. The one field shape the app's forms use.
 */
export function TextField({ label, id, disabled, ...inputProps }: TextFieldProps) {
  const field = useFieldContext<string>();
  const isSubmitting = useSelector(field.form.store, (state) => state.isSubmitting);
  const inputId = id ?? field.name;
  const errorId = `${inputId}-error`;
  const error = field.state.meta.errors.map(errorMessage).find((message) => message !== undefined);

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      <Input
        id={inputId}
        name={field.name}
        value={field.state.value}
        onChange={(event) => field.handleChange(event.target.value)}
        onBlur={field.handleBlur}
        disabled={disabled || isSubmitting}
        aria-invalid={error !== undefined}
        aria-describedby={error ? errorId : undefined}
        {...inputProps}
      />
      {error && (
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
