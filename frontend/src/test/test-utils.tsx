/**
 * Create a fake (unsigned) JWT for expiry logic. The token has the structure
 * header.payload.signature with a valid base64url payload; nothing verifies the signature.
 */
export function createFakeJWT(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.fake-signature`;
}
