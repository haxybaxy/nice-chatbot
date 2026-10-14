import { useSelector } from "@tanstack/react-form";
import type * as React from "react";

import { Button } from "@/shared/components/ui/button";

import { useFormContext } from "./contexts";

interface SubmitButtonProps {
  children: React.ReactNode;
  /** Shown instead of the children while the form's `onSubmit` is running. */
  pendingLabel: string;
}

/** The form's submit button, rendered inside `form.AppForm`; disabled while submitting. */
export function SubmitButton({ children, pendingLabel }: SubmitButtonProps) {
  const form = useFormContext();
  const isSubmitting = useSelector(form.store, (state) => state.isSubmitting);

  return (
    <Button type="submit" disabled={isSubmitting}>
      {isSubmitting ? pendingLabel : children}
    </Button>
  );
}
