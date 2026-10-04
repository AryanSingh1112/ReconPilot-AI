import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


class SigmoidCalibrator:
    def fit(self, p, y):
        self.m = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p), y)
        return self

    def predict(self, p):
        return self.m.predict_proba(_logit(p))[:, 1]


def ece(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    idx = np.clip(np.digitize(p, np.linspace(0, 1, bins + 1)[1:-1]), 0, bins - 1)
    return float(sum((idx == b).mean() * abs(y[idx == b].mean() - p[idx == b].mean())
                     for b in range(bins) if (idx == b).any()))


def bootstrap_ci(y, s, n=100, seed=0):
    rng = np.random.default_rng(seed); v = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() > 0: v.append(average_precision_score(y[i], s[i]))
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def paired_boot_diff(y, a, b, n=100, seed=0):
    rng = np.random.default_rng(seed); v = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() > 0: v.append(average_precision_score(y[i], a[i]) - average_precision_score(y[i], b[i]))
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def boot_mean(x, n=500, seed=0):
    x = np.asarray(x, float)
    if len(x) == 0: return [None, None]
    rng = np.random.default_rng(seed)
    m = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]