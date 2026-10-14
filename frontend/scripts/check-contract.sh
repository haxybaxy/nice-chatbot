#!/usr/bin/env bash
#
# Non-mutating check of the contract chain's two frontend links (`just contract-check`; also the
# root pre-commit hook `frontend-contract-check` and .github/workflows/frontend.yml):
#
#   a. src/test/contract/openapi.json  ==  ../backend/tests/guards/openapi.snapshot.json  (bytes)
#   b. src/shared/api/generated/schema.d.ts  ==  openapi-typescript(openapi.json)
#
# Needs node + `npm ci` in frontend/ only — no uv: link 1 (app -> backend snapshot) is the
# backend's own guard. Never writes: `openapi-typescript --check` compares in memory and exits
# before touching the output file. On mismatch: remediation on stderr, exit 1.
#
# Usage: just contract-check   (or: npm run contract:check)

set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${BACKEND_DIR:-$FRONTEND_DIR/../backend}"
SNAPSHOT="$BACKEND_DIR/tests/guards/openapi.snapshot.json"
VENDORED="$FRONTEND_DIR/src/test/contract/openapi.json"
GENERATED="$FRONTEND_DIR/src/shared/api/generated/schema.d.ts"
REMEDY='run `just contract-refresh` in frontend/ and commit the result (docs/api-contract.md)'

fail() {
  echo "contract-check: $1" >&2
  echo "contract-check: $REMEDY" >&2
  exit 1
}

for f in "$SNAPSHOT" "$VENDORED" "$GENERATED"; do
  [ -f "$f" ] || fail "missing $f"
done
[ -d "$FRONTEND_DIR/node_modules/openapi-typescript" ] || fail 'frontend/node_modules is missing — `npm ci` in frontend/ first'

# (a) the vendored spec is a byte copy of the backend snapshot.
if ! cmp -s "$SNAPSHOT" "$VENDORED"; then
  echo "contract-check: src/test/contract/openapi.json differs from backend/tests/guards/openapi.snapshot.json (first 40 lines):" >&2
  # diff exits 1 on a difference; without `|| true` pipefail would end the script before the remedy.
  diff -u "$VENDORED" "$SNAPSHOT" | head -n 40 >&2 || true
  fail "the vendored spec is stale or was hand-edited"
fi

# (b) the committed schema.d.ts is what the generator emits. Same npm script as `just types`, so
# the generator flags cannot drift between generating and checking.
if ! (cd "$FRONTEND_DIR" && npm run --silent types:generate -- --check); then
  fail "src/shared/api/generated/schema.d.ts is stale or was hand-edited"
fi

echo "contract-check: OK (openapi.json == backend snapshot; schema.d.ts is current)" >&2
