"""Server-Sent Events formatting."""

import json


def event(name: str, data: object) -> str:
    """One SSE event. JSON has no raw newlines, so `data` always fits on one line."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
