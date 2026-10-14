const isClient = typeof window !== "undefined";

function tryGet(key: string): string | null {
  if (!isClient) return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function trySet(key: string, value: string): void {
  if (!isClient) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // quota exceeded or storage disabled — silently fail
  }
}

/**
 * Thin wrapper around localStorage with SSR safety and error handling.
 * Callers never need `typeof window` guards or try/catch blocks.
 */
export const storage = {
  /** Read a JSON-parsed value. Returns `fallback` (default `null`) on miss or error. */
  get<T>(key: string, fallback: T | null = null): T | null {
    const raw = tryGet(key);
    if (raw === null) return fallback;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return fallback;
    }
  },

  /** Write a JSON-stringified value. */
  set<T>(key: string, value: T): void {
    trySet(key, JSON.stringify(value));
  },

  /** Read a raw string value. Returns `fallback` (default `null`) on miss or error. */
  getString(key: string, fallback: string | null = null): string | null {
    return tryGet(key) ?? fallback;
  },

  /** Write a raw string value. */
  setString(key: string, value: string): void {
    trySet(key, value);
  },

  /** Remove a single key. */
  remove(key: string): void {
    if (!isClient) return;
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  },

  /** Remove all keys that start with `prefix`. */
  removeByPrefix(prefix: string): void {
    if (!isClient) return;
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key?.startsWith(prefix)) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach((key) => localStorage.removeItem(key));
    } catch {
      // ignore
    }
  },
};
