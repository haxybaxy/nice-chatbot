import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import { createTypeScriptImportResolver } from "eslint-import-resolver-typescript";
import importX from "eslint-plugin-import-x";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import unusedImports from "eslint-plugin-unused-imports";
import globals from "globals";
import tseslint from "typescript-eslint";

// ── Contract guard rails (docs/api-contract.md) ──────────────────────────────────────────────
// `no-restricted-imports` options do not merge across config blocks, so every scope below
// restates exactly the bans that apply to it. A new sanctioned file goes in the right scope
// block, never behind an `eslint-disable`.
const BAN_AXIOS = {
  name: "axios",
  message:
    "Only apiClient talks HTTP (src/shared/services/api-client.ts); features call a service, services call apiClient.",
};
const BAN_GENERATED = {
  group: ["**/generated/schema", "**/generated/*"],
  message:
    "Import `Schema`, `ApiPath`, … from `@/shared/api/types` — src/shared/api/types.ts is the only reader of the generated module.",
};
const BAN_SPEC = {
  regex: "openapi\\.json(\\?raw)?$",
  message:
    "The vendored spec is read only by src/test/contract/ and src/test/guards/; app code uses the generated types.",
};
const restrictedImports = ({ paths = [], patterns = [] }) => ["error", { paths, patterns }];

// Two modules talk HTTP: apiClient (JSON, axios) and the SSE client (`text/event-stream`, fetch).
// Everything else calls a service. The globals ban is what keeps a stray `fetch(…)` out of a
// feature; `sse-client.ts` is the one scope where it is turned off.
const HTTP_GLOBALS_MESSAGE =
  "Only apiClient (JSON) and src/shared/services/sse-client.ts (event streams) talk HTTP.";
const BAN_HTTP_GLOBALS = ["fetch", "EventSource", "XMLHttpRequest", "WebSocket"].map((name) => ({
  name,
  message: HTTP_GLOBALS_MESSAGE,
}));
const BAN_HTTP_PROPERTIES = ["globalThis", "window"].map((object) => ({
  object,
  property: "fetch",
  message: HTTP_GLOBALS_MESSAGE,
}));

// Registry code we vendor (shadcn `ui/`, AI Elements, the `use-mobile` hook shadcn writes) is
// kept as shipped so `just ui-add` / `just ai-add` stay diffable against upstream: the size and
// complexity ceilings, the react-refresh export rule and the three React Compiler diagnostics
// upstream does not lint with are off there. The import bans, the HTTP-globals ban and
// `no-explicit-any` stay on — a violation in a registry file is fixed by hand.
const VENDORED_FILES = [
  "src/shared/components/ui/**",
  "src/shared/components/ai-elements/**",
  "src/shared/hooks/use-mobile.ts",
];

export default defineConfig([
  globalIgnores(["dist", "coverage", "node_modules", "claudedocs", "src/shared/api/generated"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    linterOptions: {
      // Every `eslint-disable` must be needed — the analogue of the backend's
      // `reportUnnecessaryTypeIgnoreComment = "error"`.
      reportUnusedDisableDirectives: "error",
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "import-x": importX,
      "unused-imports": unusedImports,
    },
    settings: {
      "import-x/resolver-next": [
        createTypeScriptImportResolver({ alwaysTryTypes: true, project: "./tsconfig.json" }),
      ],
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // unused-imports replaces the import-side of @typescript-eslint/no-unused-vars
      "@typescript-eslint/no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "warn",
        { vars: "all", varsIgnorePattern: "^_", args: "after-used", argsIgnorePattern: "^_" },
      ],

      // A written `any` is a build failure, like the backend's `reportExplicitAny = "error"`.
      "@typescript-eslint/no-explicit-any": "error",

      // Wire types come from the generated spec, through one module, into a path-typed client.
      "no-restricted-imports": restrictedImports({
        paths: [BAN_AXIOS],
        patterns: [BAN_GENERATED, BAN_SPEC],
      }),
      "no-restricted-globals": ["error", ...BAN_HTTP_GLOBALS],
      "no-restricted-properties": ["error", ...BAN_HTTP_PROPERTIES],
      // Inline object casts are how hand-written wire shapes sneak in (MSW bodies, error probes).
      "no-restricted-syntax": [
        "error",
        {
          selector: ":matches(TSAsExpression, TSTypeAssertion) > TSTypeLiteral",
          message:
            'Don\'t cast to an inline object type; alias the wire schema (`Schema<"X">`, `RequestBody<…>`) or name a client-only type.',
        },
      ],

      "import-x/order": [
        "warn",
        {
          groups: ["builtin", "external", "internal", ["parent", "sibling", "index"]],
          pathGroups: [{ pattern: "@/**", group: "internal" }],
          pathGroupsExcludedImportTypes: ["builtin"],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],

      // Complexity guardrails — the rule's job is preventing drift on new code.
      complexity: ["error", 50],
      "max-lines-per-function": [
        "error",
        { max: 350, skipBlankLines: true, skipComments: true, IIFEs: true },
      ],
      "max-lines": ["error", { max: 500, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    // Type-only files routinely exceed the limit (interface bundles).
    files: ["**/types/**", "**/*.types.ts"],
    rules: { "max-lines": "off" },
  },
  {
    // The one reader of the generated module.
    files: ["src/shared/api/types.ts"],
    rules: {
      "no-restricted-imports": restrictedImports({ paths: [BAN_AXIOS], patterns: [BAN_SPEC] }),
    },
  },
  {
    // The HTTP client, and the documented interceptor-bypassing refresh call.
    files: ["src/shared/services/api-client.ts", "src/features/auth/services/auth.service.ts"],
    rules: {
      "no-restricted-imports": restrictedImports({ patterns: [BAN_GENERATED, BAN_SPEC] }),
    },
  },
  {
    // The contract validator and the guard tests read the raw spec.
    files: ["src/test/contract/**", "src/test/guards/**"],
    rules: {
      "no-restricted-imports": restrictedImports({ paths: [BAN_AXIOS], patterns: [BAN_GENERATED] }),
    },
  },
  {
    // The event-stream client: the one sanctioned `fetch`.
    files: ["src/shared/services/sse-client.ts"],
    rules: {
      "no-restricted-globals": "off",
      "no-restricted-properties": "off",
    },
  },
  {
    // Vendored registry components (see VENDORED_FILES).
    files: VENDORED_FILES,
    rules: {
      "max-lines": "off",
      "max-lines-per-function": "off",
      complexity: "off",
      "react-refresh/only-export-components": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/static-components": "off",
    },
  },
]);
