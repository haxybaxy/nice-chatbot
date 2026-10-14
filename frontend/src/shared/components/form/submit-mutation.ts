/**
 * Adapt a mutation to TanStack Form's `onSubmit`. Awaiting it keeps `isSubmitting` true for the
 * request's duration, so the fields and the submit button disable themselves. Its rejection is
 * swallowed here on purpose: the mutation already exposes it (`mutation.error` → `FormAlert`),
 * and `form.handleSubmit()` would otherwise surface it as an unhandled rejection.
 */
export function submitMutation<TValue>(run: (value: TValue) => Promise<unknown>) {
  return async ({ value }: { value: TValue }): Promise<void> => {
    try {
      await run(value);
    } catch {
      // Reported through the mutation's `error`.
    }
  };
}
