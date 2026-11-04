def scrub(message: str, secret: str | None) -> str:
    """Remove a secret (e.g. a password from a connection URL) from an error message."""
    if secret:
        message = message.replace(secret, "***")
    return message
