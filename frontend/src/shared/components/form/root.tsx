import type * as React from "react";

import { useFormContext } from "./contexts";

/**
 * The `<form>` element of an app form, rendered inside `form.AppForm`: native validation off
 * (the schema validates) and submit wired to TanStack's `handleSubmit`.
 */
export function Root({ children }: { children: React.ReactNode }) {
  const form = useFormContext();

  return (
    <form
      noValidate
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        void form.handleSubmit();
      }}
    >
      {children}
    </form>
  );
}
