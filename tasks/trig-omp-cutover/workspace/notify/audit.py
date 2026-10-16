"""Audit helpers. Public API used by the ops dashboard (separate repo)."""

__all__ = ["export_csv", "redact"]


def redact(email):
    user, _, domain = email.partition("@")
    return user[:1] + "***@" + domain


def export_csv(rows):
    return "\n".join(",".join(str(c) for c in r) for r in rows)
