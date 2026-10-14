import { describe, expect, it } from "vitest";

import { STORAGE_KEYS } from "@/shared/constants/storage-keys";
import { createFakeJWT } from "@/test/test-utils";

import { tokenStorage } from "../token-storage";

describe("tokenStorage", () => {
  it("keeps the access token in memory and the refresh token in localStorage", () => {
    tokenStorage.setTokens({ accessToken: "at", refreshToken: "rt", expiresIn: 3600 });

    expect(tokenStorage.getAccessToken()).toBe("at");
    expect(tokenStorage.getRefreshToken()).toBe("rt");
    expect(localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)).toBe("rt");
    // The access token is never persisted — a reload must go through refresh.
    expect(Object.values(localStorage)).not.toContain("at");
  });

  it("clears both tokens", () => {
    tokenStorage.setTokens({ accessToken: "at", refreshToken: "rt", expiresIn: 3600 });
    tokenStorage.clearTokens();

    expect(tokenStorage.getAccessToken()).toBeNull();
    expect(tokenStorage.getRefreshToken()).toBeNull();
  });

  it("treats a missing or undecodable access token as expired", () => {
    expect(tokenStorage.isAccessTokenExpired()).toBe(true);
    tokenStorage.setTokens({ accessToken: "not-a-jwt", refreshToken: "rt", expiresIn: 3600 });
    expect(tokenStorage.isAccessTokenExpired()).toBe(true);
  });

  it("reports expiry from the JWT `exp` claim with a 10-second buffer", () => {
    const now = Math.floor(Date.now() / 1000);

    tokenStorage.setTokens({
      accessToken: createFakeJWT({ exp: now + 60 }),
      refreshToken: "rt",
      expiresIn: 60,
    });
    expect(tokenStorage.isAccessTokenExpired()).toBe(false);

    tokenStorage.setTokens({
      accessToken: createFakeJWT({ exp: now + 5 }),
      refreshToken: "rt",
      expiresIn: 5,
    });
    expect(tokenStorage.isAccessTokenExpired()).toBe(true);
  });
});
