"""Free-text notes attached to a bill."""

def clip(text, limit=40):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "..."
