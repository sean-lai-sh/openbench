"""
Recover the first-layer weight matrix A1 of a one-hidden-layer ReLU network
f(x) = A2 @ relu(A1 @ x + b1) + b2 using only black-box queries to forward().

Method (critical-point / kink search):
  * Restricted to a random line x(t) = x0 + t*d, f is piecewise linear in t.
    Every kink corresponds to one hidden neuron i switching on/off, i.e. the
    line crossing the hyperplane A1[i] @ x + b1[i] = 0.
  * Kinks are located exactly by recursively intersecting the linear pieces
    at the ends of an interval and verifying the prediction.
  * At a kink, the gradient of f just on either side differs by
    +-A2[i] * A1[i], which is row i of A1 up to scale.
  * Rows from many lines are normalised and clustered; each cluster is one
    neuron. The number of hidden neurons is the number of clusters.
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


def find_kinks(x0, d, a, b, fa, fb, depth=0, out=None):
    """Find all kinks of g(t)=f(x0+t d) on [a,b]."""
    if out is None:
        out = []
    if b - a < 1e-9 or depth > 60:
        return out
    g = lambda t: f(x0 + t * d)
    mid = 0.5 * (a + b)
    fm = g(mid)
    scale = max(abs(fa), abs(fb), abs(fm), 1e-3)
    # linear on [a,b]? (missing a kink here requires an exact cancellation)
    if abs(fm - 0.5 * (fa + fb)) < 1e-12 * scale and depth > 2:
        return out
    # try to explain the interval with a single kink
    delta = (b - a) * 1e-4
    sl = (g(a + delta) - fa) / delta
    sr = (fb - g(b - delta)) / delta
    if abs(sl - sr) > 1e-12:
        # line L: fa + sl (t-a); line R: fb + sr (t-b)
        tk = (fb - fa + sl * a - sr * b) / (sl - sr)
        if a + delta < tk < b - delta:
            pred = fa + sl * (tk - a)
            fk = g(tk)
            # verify: f at kink matches both lines, and points between are linear
            if abs(fk - pred) < 1e-9 * scale:
                ql = 0.5 * (a + tk)
                qr = 0.5 * (tk + b)
                if (
                    abs(g(ql) - (fa + sl * (ql - a))) < 1e-9 * scale
                    and abs(g(qr) - (fb + sr * (qr - b))) < 1e-9 * scale
                ):
                    out.append(tk)
                    return out
    find_kinks(x0, d, a, mid, fa, fm, depth + 1, out)
    find_kinks(x0, d, mid, b, fm, fb, depth + 1, out)
    return out


def gradient(x, h):
    """Central finite-difference gradient (exact within a linear region)."""
    gr = np.zeros(DIM)
    for j in range(DIM):
        e = np.zeros(DIM)
        e[j] = h
        gr[j] = (f(x + e) - f(x - e)) / (2 * h)
    return gr


def collect_rows(n_lines=60, T=10.0):
    rows = []
    for _ in range(n_lines):
        x0 = rng.normal(size=DIM) * 0.5
        d = rng.normal(size=DIM)
        d /= np.linalg.norm(d)
        a, b = -T, T
        kinks = sorted(find_kinks(x0, d, a, b, f(x0 + a * d), f(x0 + b * d)))
        for k, tk in enumerate(kinks):
            left = kinks[k - 1] if k > 0 else a
            right = kinks[k + 1] if k + 1 < len(kinks) else b
            gap = min(tk - left, right - tk)
            eps = min(1e-3, gap / 4)
            if eps < 1e-8:
                continue
            h = eps * 1e-3
            xk = x0 + tk * d
            gp = gradient(xk + eps * d, h)
            gm = gradient(xk - eps * d, h)
            diff = gp - gm
            nrm = np.linalg.norm(diff)
            if nrm < 1e-10:
                continue
            rows.append(diff / nrm)
    return np.array(rows)


def canon(v):
    """Fix the sign ambiguity: largest-magnitude entry positive."""
    return v if v[np.argmax(np.abs(v))] > 0 else -v


def cluster(rows, tol=1e-4):
    centers, members = [], []
    for r in rows:
        r = canon(r)
        for i, c in enumerate(centers):
            if np.linalg.norm(r - c) < tol * 100:
                members[i].append(r)
                centers[i] = canon(np.mean(members[i], axis=0))
                centers[i] /= np.linalg.norm(centers[i])
                break
        else:
            centers.append(r)
            members.append([r])
    return centers, members


def main():
    rows = collect_rows()
    centers, members = cluster(rows)
    counts = np.array([len(m) for m in members])
    # drop spurious singletons if there are well-supported clusters
    keep = counts >= 2 if (counts >= 2).sum() > 0 else counts >= 1
    A1_hat = np.array([c for c, k in zip(centers, keep) if k])
    np.save("/app/stolen_A1.npy", A1_hat)
    print(f"queries used: {n_queries}")
    print(f"kinks found: {len(rows)}, hidden neurons recovered: {A1_hat.shape[0]}")
    print("cluster sizes:", sorted(counts[keep].tolist(), reverse=True))
    np.set_printoptions(precision=5, suppress=True, linewidth=150)
    print(A1_hat)
    return A1_hat


if __name__ == "__main__":
    main()
