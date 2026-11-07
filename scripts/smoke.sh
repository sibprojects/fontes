#!/usr/bin/env bash
# End-to-end smoke test of a running stack: health, upload, and ingestion through the worker.
# Usage: scripts/smoke.sh [base-url]   (default http://127.0.0.1:8000). Needs curl, grep, sed.
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
TIMEOUT_SECONDS=30

echo "health: $(curl -fsS "$BASE/health")"

cd "$(mktemp -d)"  # a relative path also works for the Windows build of curl
file=smoke.md
# A random line, so the upload is never deduplicated against an earlier run.
printf '# Smoke test\n\n%s-%s\n' "$(date +%s)" "$RANDOM$RANDOM" > "$file"
created="$(curl -fsS -F "file=@$file;type=text/markdown" "$BASE/documents")"
id="$(printf '%s' "$created" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
if [[ -z "$id" ]]; then
  echo "upload returned no id: $created" >&2
  exit 1
fi
echo "uploaded $id"

status=unknown
deadline=$((SECONDS + TIMEOUT_SECONDS))
while ((SECONDS < deadline)); do
  status="$(curl -fsS "$BASE/documents" \
    | grep -o "\"id\":\"$id\"[^}]*" \
    | sed -n 's/.*"status":"\([a-z]*\)".*/\1/p')"
  if [[ "$status" == "ready" ]]; then
    echo "document $id is ready"
    exit 0
  fi
  sleep 1
done

echo "document $id is still '${status:-missing}' after ${TIMEOUT_SECONDS}s" >&2
exit 1
