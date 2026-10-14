import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";

import { tokenStorage } from "@/shared/services/token-storage";

import { assertNoContractViolations, installContractValidation } from "./contract/install";
import { server } from "./msw/server";

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
