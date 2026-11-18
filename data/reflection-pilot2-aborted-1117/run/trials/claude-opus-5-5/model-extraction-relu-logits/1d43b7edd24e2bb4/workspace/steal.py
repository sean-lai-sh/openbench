"""
Recover the first-layer weight matrix A1 of a one-hidden-layer ReLU network
    f(x) = A2 @ ReLU(A1 @ x + b1) + b2
using only black-box queries to forward(x).

Method (critical-point / kink search):
  1. Pick random lines x(t) = x0 + t*d. Along a line f is piecewise linear in t;
     each kink corresponds to one hidden neuron switching on/off.
  2. Locate kinks by recursively comparing linear extrapolations of the
     function from both ends of an interval.
  3. At each kink x*, estimate the full input gradient just before and just
     after the kink (central finite differences; exact for linear pieces).
     The difference equals a2_i * sign(.) * A1[i], i.e. row i of A1 up to scale.
  4. Normalise and de-duplicate the recovered rows across many lines.
The result equals A1 up to row permutation and (per-row) scaling.
"""

import sys

import numpy as np

sys.path.insert(0, "/app")
from forward import forward  # noqa: E402

DIM = 10
rng = np.random.default_rng(12345)

n_queries = 0


def f(x):
    global n_queries
    n_queries += 1
    return forward(np.asarray(x, dtype=np.float64))


def gradient(x, h=1e-7):
    """Central finite-difference gradient (exact on a linear region)."""
    g = np.empty(DIM)
    for k in range(DIM):
        e = np.zeros(DIM)
        e[k] = h
        g[k] = (f(x + e) - f(x - e)) / (2 * h)
    return g


def find_kinks(x0, d, lo, hi, delta=1e-6, tol=1e-9, min_width=1e-5):
    """Return t-values of kinks of g(t)=f(x0+t d) in [lo, hi]."""
    g = lambda t: f(x0 + t * d)
    kinks = []

    def slope(t, side):
        if side > 0:
            return (g(t + delta) - g(t)) / delta
        return (g(t) - g(t - delta)) / delta

    stack = [(lo, hi)]
    while stack:
        a, b = stack.pop()
        ga, gb = g(a), g(b)
        sa, sb = slope(a, +1), slope(b, -1)
        scale = max(1.0, abs(ga), abs(gb))
        # Straight line between a and b?
        if abs(sa - sb) < tol * scale / delta * 10 and abs(
            (gb - ga) / (b - a) - sa
        ) < 1e-7 * max(1.0, abs(sa)):
            gm = g((a + b) / 2)
            if abs(gm - (ga + gb) / 2) < 1e-9 * scale:
                continue
        if b - a < min_width:
            # Intersection of the two lines
            if abs(sa - sb) > 1e-12:
                t = (gb - ga + sa * a - sb * b) / (sa - sb)
                if a <= t <= b:
                    kinks.append(t)
            continue
        # Try to explain the interval with a single kink.
        if abs(sa - sb) > 1e-12:
            t = (gb - ga + sa * a - sb * b) / (sa - sb)
            if a + delta * 2 < t < b - delta * 2:
                pred = ga + sa * (t - a)
                if abs(g(t) - pred) < 1e-9 * scale:
                    # Verify both halves are linear.
                    sl = slope(t, -1)
                    sr = slope(t, +1)
                    if abs(sl - sa) < 1e-6 * max(1, abs(sa)) and abs(
                        sr - sb
                    ) < 1e-6 * max(1, abs(sb)):
                        kinks.append(t)
                        continue
        m = (a + b) / 2
        stack.append((a, m))
        stack.append((m, b))
    return sorted(kinks)


def row_at_kink(x0, d, t, eps=1e-4):
    xs = x0 + t * d
    gl = gradient(xs - eps * d)
    gr = gradient(xs + eps * d)
    diff = gr - gl
    n = np.linalg.norm(diff)
    if n < 1e-8:
        return None
    return diff / n


def canon(v):
    v = v / np.linalg.norm(v)
    i = np.argmax(np.abs(v))
    return v if v[i] > 0 else -v


def steal(n_lines=60, span=30.0, patience=15):
    rows = []  # list of [sum_vector, count]
    since_new = 0
    for line in range(n_lines):
        x0 = rng.normal(size=DIM)
        d = rng.normal(size=DIM)
        d /= np.linalg.norm(d)
        kinks = find_kinks(x0, d, -span, span)
        # discard kinks too close together (two neurons at once)
        found_new = False
        for i, t in enumerate(kinks):
            if (i > 0 and t - kinks[i - 1] < 1e-3) or (
                i + 1 < len(kinks) and kinks[i + 1] - t < 1e-3
            ):
                continue
            r = row_at_kink(x0, d, t)
            if r is None:
                continue
            r = canon(r)
            for entry in rows:
                c = entry[0] / np.linalg.norm(entry[0])
                if abs(np.dot(c, r)) > 0.9999:
                    entry[0] += r * np.sign(np.dot(c, r))
                    entry[1] += 1
                    break
            else:
                rows.append([r.copy(), 1])
                found_new = True
        since_new = 0 if found_new else since_new + 1
        if since_new >= patience and line >= 20:
            break
    A = np.array(
        [canon(e[0]) for e in rows if e[1] >= 2] or [canon(e[0]) for e in rows]
    )
    return A


if __name__ == "__main__":
    A1_hat = steal()
    np.save("/app/stolen_A1.npy", A1_hat)
    print(f"Recovered {A1_hat.shape[0]} neurons using {n_queries} queries")
    print(A1_hat)
