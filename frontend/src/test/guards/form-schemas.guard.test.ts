/**
 * The zod form schemas are FORMS ONLY (CLAUDE.md) and hand-copy the structural bounds of the
 * `*In` schema they feed (password 8–256, name ≤ 255, …). Nothing generates them, so this guard
 * reads the vendored spec and fails when a bound drifts from the wire: every constraint the
 * wire declares on a field must be identical on the form, every wire-required field must be on
 * the form, and every form field must exist on the wire unless it is listed as form-only.
 */
import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  forgotPasswordSchema,
  resetPasswordSchema,
  signInSchema,
  signUpSchema,
} from "@/features/auth/schemas/auth-form.schemas";
import openapiSpecRaw from "@/test/contract/openapi.json?raw";

/** The JSON Schema keywords a Pydantic `str` field can carry that a zod string mirrors. */
const CONSTRAINTS = ["minLength", "maxLength", "format", "pattern"] as const;

const spec: unknown = JSON.parse(openapiSpecRaw);

function prop(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** Pydantic renders `str | None` as `anyOf: [{type: string, …}, {type: null}]`; the bounds live on the non-null branch. */
function unwrapNullable(schema: unknown): unknown {
  const anyOf = prop(schema, "anyOf");
  if (!Array.isArray(anyOf)) {
    return schema;
  }
  return anyOf.find((branch) => prop(branch, "type") !== "null") ?? schema;
}

function wireSchema(name: string): Record<string, unknown> {
  const schema = prop(prop(prop(spec, "components"), "schemas"), name);
  if (schema === undefined) {
    throw new Error(`openapi.json has no components.schemas.${name}`);
  }
  return record(schema);
}

interface GuardCase {
  /** The `*In` schema the form's submit maps onto. */
  wireSchema: string;
  form: z.ZodType;
  /** Form fields that never reach the wire (`confirmPassword`). */
  formOnly: string[];
  /** `field.constraint` pairs deliberately not mirrored, each with a reason at the call site. */
  exempt: string[];
}

/** One field's constraint mismatches: every wire bound the form does not mirror (unless exempt). */
function constraintDrift(
  field: string,
  wireField: unknown,
  formField: unknown,
  exempt: string[]
): string[] {
  const drift: string[] = [];
  for (const constraint of CONSTRAINTS) {
    const expected = prop(wireField, constraint);
    if (expected === undefined || exempt.includes(`${field}.${constraint}`)) {
      continue;
    }
    const actual = prop(formField, constraint);
    if (actual !== expected) {
      drift.push(
        `${field}.${constraint}: wire ${JSON.stringify(expected)}, form ${JSON.stringify(actual)}`
      );
    }
  }
  return drift;
}

function findDrift({ wireSchema: name, form, formOnly, exempt }: GuardCase): string[] {
  const wire = wireSchema(name);
  const wireProps = record(wire["properties"]);
  const wireRequired: unknown[] = Array.isArray(wire["required"]) ? wire["required"] : [];
  const formProps = record(prop(z.toJSONSchema(form), "properties"));
  const drift: string[] = [];

  for (const [field, formField] of Object.entries(formProps)) {
    if (formOnly.includes(field)) {
      continue;
    }
    if (!(field in wireProps)) {
      drift.push(`${field}: not a ${name} field (list it in formOnly if it never hits the wire)`);
      continue;
    }
    drift.push(
      ...constraintDrift(field, unwrapNullable(wireProps[field]), unwrapNullable(formField), exempt)
    );
  }
  for (const field of wireRequired) {
    if (typeof field === "string" && !(field in formProps)) {
      drift.push(`${field}: required by ${name} but missing from the form`);
    }
  }
  return drift;
}

describe("form schemas mirror the wire schemas they submit to", () => {
  it("signInSchema matches SignInIn", () => {
    expect(
      findDrift({ wireSchema: "SignInIn", form: signInSchema, formOnly: [], exempt: [] })
    ).toEqual([]);
  });

  it("signUpSchema matches SignUpIn", () => {
    expect(
      findDrift({
        wireSchema: "SignUpIn",
        form: signUpSchema,
        formOnly: ["confirmPassword"],
        // The wire's `fullName` min_length=1 is met by mapping "" -> null on submit
        // (sign-up-form.tsx), so the form must NOT add a minimum of its own.
        exempt: ["fullName.minLength"],
      })
    ).toEqual([]);
    const fullName = record(prop(z.toJSONSchema(signUpSchema), "properties"))["fullName"];
    expect(prop(fullName, "minLength")).toBeUndefined();
  });

  it("forgotPasswordSchema matches ForgotPasswordIn", () => {
    expect(
      findDrift({
        wireSchema: "ForgotPasswordIn",
        form: forgotPasswordSchema,
        formOnly: [],
        exempt: [],
      })
    ).toEqual([]);
  });

  it("resetPasswordSchema matches ResetPasswordIn", () => {
    expect(
      findDrift({
        wireSchema: "ResetPasswordIn",
        form: resetPasswordSchema,
        formOnly: ["confirmPassword"],
        exempt: [],
      })
    ).toEqual([]);
  });
});
