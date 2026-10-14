#!/usr/bin/env bash
#
# THE command to run after any backend API change: `just contract-refresh` (from frontend/).
# Walks the whole contract chain, in order (docs/api-contract.md):
#
#   1. ../backend `just openapi-snapshot` rewrites tests/guards/openapi.snapshot.json from the app
#      (guarded by tests/guards/test_openapi.py::test_openapi_snapshot_is_current).
#   2. cp that snapshot -> src/test/contract/openapi.json. The vendored spec is a BYTE COPY of the
#      backend's guarded snapshot, never a second `app.openapi()` dump: one serialization path, so
#      the two files can only differ when this script was not run.
#   3. `npm run types:generate` — openapi-typescript (exact-pinned) -> src/shared/api/generated/schema.d.ts
#
# All three outputs are GENERATED: never hand-edit them; commit them together.
# scripts/check-contract.sh (`just contract-check`, pre-commit, CI) verifies links 2 and 3 without
# mutating anything; the backend guard verifies link 1.
#
# Usage: just contract-refresh                              (or: npm run contract:refresh)
#        BACKEND_DIR=/other/backend just contract-refresh   # non-sibling checkout

set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${BACKEND_DIR:-$FRONTEND_DIR/../backend}"
SNAPSHOT="$BACKEND_DIR/tests/guards/openapi.snapshot.json"
VENDORED="$FRONTEND_DIR/src/test/contract/openapi.json"

if [ ! -d "$BACKEND_DIR" ]; then
  echo "error: backend not found at $BACKEND_DIR (override with BACKEND_DIR=...)" >&2
  exit 1
fi

echo "1/3 backend: just openapi-snapshot" >&2
(cd "$BACKEND_DIR" && just openapi-snapshot)

echo "2/3 copy tests/guards/openapi.snapshot.json -> src/test/contract/openapi.json" >&2
cp "$SNAPSHOT" "$VENDORED"

# Sanity: valid JSON with a paths object, or the backend wrote garbage.
node -e 'const s=require(process.argv[1]); if(!s.openapi||!s.paths){console.error("spec missing openapi/paths");process.exit(1)} console.error("    openapi="+s.openapi+" paths="+Object.keys(s.paths).length+" schemas="+Object.keys((s.components||{}).schemas||{}).length)' "$VENDORED"

echo "3/3 openapi-typescript -> src/shared/api/generated/schema.d.ts" >&2
(cd "$FRONTEND_DIR" && npm run --silent types:generate)

echo "done: commit openapi.snapshot.json, openapi.json and schema.d.ts together" >&2
