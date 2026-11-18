"""
Extract the first-layer weight matrix A1 of a one-hidden-layer ReLU network
f(x) = A2 @ relu(A1 @ x + b1) + b2 using only black-box queries to forward().

Idea: along any line x(t) = x0 + t*d, f is piecewise linear in t. Each kink
corresponds to some hidden neuron i crossing zero (A1[i] @ x + b1[i] = 0).
At that point the gradient of f jumps by exactly A2[i] * A1[i], so the
difference of gradients on either side of a kink gives row i of A1 up to
scaling. Collect these over many random lines and de-duplicate.
"""

import numpy as np

from forward import forward

DIM = 10
rng = np.random.default_rng(12345)

n_queries = 0


def f(x):
    global n_queries
    n_queries += 1
    return forward(np.asarray(x, dtype=np.float64))


def line_f(x0, d, t):
    return f(x0 + t * d)


H = 1e-6  # step for one-sided slopes along the line


def slope_right(x0, d, t, ft=None):
    if ft is None:
        ft = line_f(x0, d, t)
    return (line_f(x0, d, t + H) - ft) / H


def slope_left(x0, d, t, ft=None):
    if ft is None:
        ft = line_f(x0, d, t)
    return (ft - line_f(x0, d, t - H)) / H


def find_kinks(x0, d, a, b, fa, fb, sa, sb, tol, depth=0, out=None):
    """Find kink locations of t -> f(x0 + t d) inside (a, b).

    sa: slope just to the right of a, sb: slope just to the left of b.
    """
    if out is None:
        out = []
    if b - a < 1e-9 or depth > 60:
        return out
    slope_scale = max(abs(sa), abs(sb), 1e-3)
    # Try the hypothesis of exactly one kink: intersect the two lines.
    if abs(sa - sb) > tol * slope_scale:
        tk = (fb - fa + sa * a - sb * b) / (sa - sb)
        if a + 2 * H < tk < b - 2 * H:
            ftk = line_f(x0, d, tk)
            pred = fa + sa * (tk - a)
            if abs(ftk - pred) < tol * max(1.0, abs(pred)):
                # Confirm left and right slopes around tk match sa and sb.
                eps = min(1e-4, (tk - a) / 4, (b - tk) / 4)
                l = slope_left(x0, d, tk - eps)
                r = slope_right(x0, d, tk + eps)
                if (
                    abs(l - sa) < 1e-5 * slope_scale
                    and abs(r - sb) < 1e-5 * slope_scale
                ):
                    out.append(tk)
                    return out
    else:
        # Same slope at both ends: check linearity at midpoint.
        m = 0.5 * (a + b)
        fm = line_f(x0, d, m)
        pred = fa + sa * (m - a)
        if (
            abs(fm - pred) < tol * max(1.0, abs(pred))
            and abs((fb - fa) / (b - a) - sa) < 1e-5 * slope_scale
        ):
            return out
    # Otherwise split.
    m = 0.5 * (a + b)
    fm = line_f(x0, d, m)
    sml = slope_left(x0, d, m, fm)
    smr = slope_right(x0, d, m, fm)
    find_kinks(x0, d, a, m, fa, fm, sa, sml, tol, depth + 1, out)
    find_kinks(x0, d, m, b, fm, fb, smr, sb, tol, depth + 1, out)
    return out


def gradient(x, h=1e-6):
    g = np.zeros(DIM)
    for j in range(DIM):
        e = np.zeros(DIM)
        e[j] = h
        g[j] = (f(x + e) - f(x - e)) / (2 * h)
    return g


def normalize(v):
    v = v / np.linalg.norm(v)
    k = np.argmax(np.abs(v))
    return v * np.sign(v[k])


def is_new(v, rows, thresh=1 - 1e-6):
    for r in rows:
        if abs(np.dot(v, r)) > thresh:
            return False
    return True


def steal(T=50.0, max_lines=300, patience=40, tol=1e-9):
    rows = []
    lines_without_new = 0
    for line_idx in range(max_lines):
        x0 = rng.normal(size=DIM)
        d = rng.normal(size=DIM)
        d /= np.linalg.norm(d)
        a, b = -T, T
        fa, fb = line_f(x0, d, a), line_f(x0, d, b)
        sa, sb = slope_right(x0, d, a, fa), slope_left(x0, d, b, fb)
        kinks = sorted(find_kinks(x0, d, a, b, fa, fb, sa, sb, tol))

        found_new = False
        for idx, tk in enumerate(kinks):
            # Distance to neighbouring kinks, to choose a safe offset.
            gaps = [tk - a, b - tk]
            if idx > 0:
                gaps.append(tk - kinks[idx - 1])
            if idx + 1 < len(kinks):
                gaps.append(kinks[idx + 1] - tk)
            delta = min(1e-3, min(gaps) / 4)
            xk = x0 + tk * d
            g_plus = gradient(xk + delta * d, h=min(1e-6, delta / 10))
            g_minus = gradient(xk - delta * d, h=min(1e-6, delta / 10))
            diff = g_plus - g_minus
            if np.linalg.norm(diff) < 1e-8:
                continue
            v = normalize(diff)
            if is_new(v, rows):
                rows.append(v)
                found_new = True
        lines_without_new = 0 if found_new else lines_without_new + 1
        if lines_without_new >= patience:
            break
    return np.array(rows)


if __name__ == "__main__":
    A1_stolen = steal()
    np.save("/app/stolen_A1.npy", A1_stolen)
    print(f"Recovered {A1_stolen.shape[0]} neurons using {n_queries} queries")
    print(A1_stolen)
