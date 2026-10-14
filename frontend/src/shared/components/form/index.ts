import { createFormHook } from "@tanstack/react-form";

import { fieldContext, formContext } from "./contexts";
import { Root } from "./root";
import { SubmitButton } from "./submit-button";
import { TextField } from "./text-field";

/**
 * The app's form hook (TanStack Form's composition API): `form.AppField` renders `TextField`
 * bound to one field; `form.AppForm` gives `Root` (the `<form>` element) and `SubmitButton` the
 * form's state.
 *
 * Every form: `useAppForm({ defaultValues, validationLogic: revalidateLogic(), validators: {
 * onDynamic: <zod schema> }, onSubmit: submitMutation(…) })` — validate on submit, re-validate
 * on change from then on, and let the mutation drive the pending state. The server's rejection
 * is rendered with `FormAlert` (`./form-alert`).
 */
export const { useAppForm } = createFormHook({
  fieldComponents: { TextField },
  formComponents: { Root, SubmitButton },
  fieldContext,
  formContext,
});

export { revalidateLogic } from "@tanstack/react-form";
export { submitMutation } from "./submit-mutation";
