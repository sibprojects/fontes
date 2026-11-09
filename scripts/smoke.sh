#!/usr/bin/env bash
# End-to-end smoke test of a running stack: health, upload, ingestion through the worker
# (parse, chunk, embed with Ollama, store), and the stored chunks.
# Usage: scripts/smoke.sh [base-url]   (default http://127.0.0.1:8000). Needs curl, grep, sed.
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
# The first embedding loads the model into memory, which can take a while on CPU.
TIMEOUT_SECONDS=180

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
  doc="$(curl -fsS "$BASE/documents" | grep -o "\"id\":\"$id\"[^}]*" || true)"
  status="$(printf '%s' "$doc" | sed -n 's/.*"status":"\([a-z]*\)".*/\1/p')"
  case "$status" in
    ready)
      echo "document $id is ready after $((SECONDS))s"
      chunks="$(curl -fsS "$BASE/documents/$id/chunks")"
      if [[ "$chunks" != *'"ordinal":0'* ]]; then
        echo "document $id is ready but has no chunks: $chunks" >&2
        exit 1
      fi
      echo "chunks: $chunks"
      exit 0
      ;;
    failed)
      echo "document $id failed: $(printf '%s' "$doc" | sed -n 's/.*"error":\(.*\),"attempts".*/\1/p')" >&2
      exit 1
      ;;
  esac
  sleep 1
done

echo "document $id is still '${status:-missing}' after ${TIMEOUT_SECONDS}s" >&2
exit 1
