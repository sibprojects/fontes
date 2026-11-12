import json
from typing import Any


def parse_sse(body: str) -> list[tuple[str, Any]]:
    """Parse a text/event-stream body into [(event name, decoded JSON data)]."""
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events
