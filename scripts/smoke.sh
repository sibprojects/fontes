#!/usr/bin/env bash
# End-to-end smoke test of a running stack: health, upload, ingestion through the worker
# (parse, chunk, embed with Ollama, store), the stored chunks, then one question through
# POST /ask (SSE) and its entry in the history.
# Usage: scripts/smoke.sh [base-url]   (default http://127.0.0.1:8000). Needs curl, grep, sed.
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
# The first embedding loads the model into memory, which can take a while on CPU.
TIMEOUT_SECONDS=180
# The first answer also loads the chat model.
ASK_TIMEOUT_SECONDS=300

echo "health: $(curl -fsS "$BASE/health")"

cd "$(mktemp -d)"  # a relative path also works for the Windows build of curl
file=smoke.md
# A random line, so the upload is never deduplicated against an earlier run.
line="$(date +%s)-$RANDOM$RANDOM"
printf '# Smoke test\n\n%s\n' "$line" > "$file"
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
      break
      ;;
    failed)
      echo "document $id failed: $(printf '%s' "$doc" | sed -n 's/.*"error":\(.*\),"attempts".*/\1/p')" >&2
      exit 1
      ;;
  esac
  sleep 1
done
if [[ "$status" != ready ]]; then
  echo "document $id is still '${status:-missing}' after ${TIMEOUT_SECONDS}s" >&2
  exit 1
fi

# Ask about the random line. Any verdict will do (even not_found): this checks the wiring
# (embed, search, stream from the chat model, verify, store), not the answer.
question="What does the smoke test say about $line?"
echo "asking: $question"
answer="$(curl -fsS -N --max-time "$ASK_TIMEOUT_SECONDS" -H 'content-type: application/json' \
  -d "{\"question\":\"$question\"}" "$BASE/ask")"
echo "$answer"
if [[ "$answer" == *'event: error'* || "$answer" != *'event: verdict'* ]]; then
  echo "asking did not end with a verdict" >&2
  exit 1
fi
history="$(curl -fsS "$BASE/questions")"
if [[ "$history" != *"$question"* ]]; then
  echo "the question is missing from history: $history" >&2
  exit 1
fi
echo "history has the question"
