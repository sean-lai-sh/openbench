from . import store


def on_save(doc):
    doc["saves"] += 1
    doc["text"] = doc["text"].rstrip() + "\n"
    return doc


def save(doc_id, text, ctx=None):
    doc = store.put(doc_id, text)
    if ctx is not None:
        ctx.append(("save", doc_id))
    return on_save(doc)


def autosave(doc_id, ctx=None):
    doc = store.get(doc_id)
    if doc is None:
        return None
    if ctx is not None:
        ctx.append(("autosave", doc_id))
    return on_save(doc)
