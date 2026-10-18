"""Two candidate sort implementations for the ingest pipeline."""
import bisect


def sort_a(xs):
    """Top-down merge sort."""
    if len(xs) <= 1:
        return list(xs)
    mid = len(xs) // 2
    left, right = sort_a(xs[:mid]), sort_a(xs[mid:])
    out, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            out.append(left[i]); i += 1
        else:
            out.append(right[j]); j += 1
    out.extend(left[i:]); out.extend(right[j:])
    return out


def sort_b(xs):
    """Incremental sorted insert (keeps the output sorted at every step)."""
    out = []
    for x in xs:
        bisect.insort(out, x)
    return out
