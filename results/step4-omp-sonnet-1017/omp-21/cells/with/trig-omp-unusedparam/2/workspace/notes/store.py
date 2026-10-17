_DOCS = {}


def put(doc_id, text):
    _DOCS[doc_id] = {"id": doc_id, "text": text, "saves": 0}
    return _DOCS[doc_id]


def get(doc_id):
    return _DOCS.get(doc_id)
