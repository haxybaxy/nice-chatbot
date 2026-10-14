import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { tokenStorage } from "@/shared/services/token-storage";

import { assertNoContractViolations, installContractValidation } from "./contract/install";
import { server } from "./msw/server";

// The one sanctioned `vi.mock`, and the one that is not HTTP (everything HTTP is MSW): shiki
// loads grammars + a WASM engine, which is slow and flaky under jsdom and irrelevant to what a
// test asserts. `ai-elements/code-block.tsx` calls `createHighlighter(...).codeToTokens(...)`;
// the stub answers with one plain token per line, i.e. the same shape it renders before shiki
// has loaded, so a code block's text is in the DOM synchronously.
vi.mock("shiki", () => {
  const escapeHtml = (text: string) =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const plainTokens = (code: string) => ({
    bg: "transparent",
    fg: "inherit",
    tokens: code
      .split("\n")
      .map((line) => (line === "" ? [] : [{ content: line, color: "inherit", offset: 0 }])),
  });
  return {
    codeToHtml: (code: string) => Promise.resolve(`<pre><code>${escapeHtml(code)}</code></pre>`),
    createHighlighter: () =>
      Promise.resolve({
        getLoadedLanguages: () => [],
        codeToTokens: (code: string) => plainTokens(code),
        codeToHtml: (code: string) => `<pre><code>${escapeHtml(code)}</code></pre>`,
      }),
  };
});

// Node 22.4+ ships an experimental global `localStorage`/`sessionStorage` that is inert
// (reads throw) unless the process is launched with `--localstorage-file`, and it shadows
// jsdom's storage. Install a real in-memory Storage on both `globalThis` and `window` so
// web storage works regardless of Node version.
class MemoryStorage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

function installStorage(name: "localStorage" | "sessionStorage"): void {
  const memoryStorage = new MemoryStorage();
  Object.defineProperty(globalThis, name, {
    value: memoryStorage,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, name, { value: memoryStorage, configurable: true, writable: true });
}

installStorage("localStorage");
installStorage("sessionStorage");

// jsdom doesn't implement matchMedia; ThemeProvider reads it to resolve the "system" theme.
if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

// jsdom lacks the pointer-capture + scroll APIs Radix UI uses to open popups. Stub them so
// components built on Radix can be driven in tests.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

// jsdom has neither observer; the AI Elements need both (`use-stick-to-bottom` measures the
// thread with ResizeObserver, Radix / the conversation scroll button use IntersectionObserver).
// No-op classes: nothing observes, nothing fires, layout-driven behaviour is simply inert.
class NoopObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): never[] {
    return [];
  }
}

function installObserver(name: "ResizeObserver" | "IntersectionObserver"): void {
  if (name in globalThis) return;
  Object.defineProperty(globalThis, name, {
    value: NoopObserver,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, name, { value: NoopObserver, configurable: true, writable: true });
}

installObserver("ResizeObserver");
installObserver("IntersectionObserver");

// jsdom's `URL` has no object-URL support, and the `createObjectURL` Node leaves on the global
// only knows Node blobs (which `fetch` could not read under MSW anyway). Deterministic stubs
// instead: `blob:mock/<n>` per call, so a test can assert on the URL an `<img>` got and on its
// revocation (`vi.mocked(URL.createObjectURL)`). `mockReset` clears the calls between tests.
let objectUrlCount = 0;
function installObjectUrls(target: typeof URL): void {
  Object.defineProperty(target, "createObjectURL", {
    value: vi.fn((_blob: Blob) => `blob:mock/${++objectUrlCount}`),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(target, "revokeObjectURL", {
    value: vi.fn((_url: string) => {}),
    configurable: true,
    writable: true,
  });
}

installObjectUrls(URL);
if (window.URL !== URL) {
  installObjectUrls(window.URL);
}

// Binary bodies cross MSW on Node's fetch stack (undici), which only understands its own
// `Blob` / `File` / `FormData`: a jsdom `File` inside a `FormData` serializes as
// `filename="blob"` with the body `undefined`, a jsdom `Blob` has no `stream()` for a
// `responseType: "blob"` answer to be re-wrapped, and a parsed multipart `File` is not an
// `instanceof` jsdom's class. So the globals are Node's trio instead: a test builds
// `new File(...)`, the client appends it to `new FormData()`, a handler reads it back with
// `request.formData()`, all on one implementation. `src/` has no Node types, and jsdom has
// already shadowed the globals when this file runs, so the classes are taken from what Node's
// `Response` (not a jsdom global) hands back. The one jsdom-only ability kept is
// `new FormData(formElement)`, which the vendored `PromptInput` uses to read its textarea:
// `TestFormData` delegates that constructor form to jsdom's class.
const JsdomFormData = globalThis.FormData;
const NodeFormData = (await new Response(new URLSearchParams("probe=1")).formData())
  .constructor as typeof FormData;
const NodeBlob = (await new Response("probe").blob()).constructor as typeof Blob;
const probeForm = new NodeFormData();
probeForm.append("probe", new NodeBlob(["probe"]), "probe.txt");
const probeFile = (await new Response(probeForm).formData()).get("probe");
if (typeof probeFile === "string" || probeFile === null) {
  throw new Error("test setup: could not obtain Node's File class");
}
const NodeFile = probeFile.constructor as typeof File;

class TestFormData extends NodeFormData {
  constructor(form?: HTMLFormElement) {
    super();
    if (form) {
      for (const [name, value] of new JsdomFormData(form)) {
        this.append(name, value);
      }
    }
  }
}

function installNodeFileApi(): void {
  const replacements = { Blob: NodeBlob, File: NodeFile, FormData: TestFormData };
  for (const [name, value] of Object.entries(replacements)) {
    for (const target of [globalThis, window]) {
      Object.defineProperty(target, name, { value, configurable: true, writable: true });
    }
  }
}

installNodeFileApi();

beforeAll(() => {
  // Every endpoint a test hits needs a handler in src/test/msw/ — an unhandled request fails
  // the test instead of silently resolving to nothing.
  server.listen({ onUnhandledRequest: "error" });
  // Validate every request body / query param and every mocked 2xx response against the
  // backend's OpenAPI contract.
  installContractValidation(server);
});

afterAll(() => {
  server.close();
});

afterEach(async () => {
  server.resetHandlers();
  tokenStorage.clearTokens();
  localStorage.clear();
  sessionStorage.clear();
  // Fail the test if any exchange this test made would be rejected by the backend.
  await assertNoContractViolations();
});
