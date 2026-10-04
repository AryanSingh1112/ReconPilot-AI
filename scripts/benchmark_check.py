"""Method check on real public data (DBLP-ACM). Not payments data."""
import json
import numpy as np, pandas as pd
import lightgbm as lgb
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from reconpilot import config as C, metrics as M

D = C.DATA / "benchmark"
a = pd.read_csv(D / "DBLP2.csv", encoding="latin-1").fillna("")
b = pd.read_csv(D / "ACM.csv", encoding="latin-1").fillna("")
m = pd.read_csv(D / "DBLP-ACM_perfectMapping.csv", encoding="latin-1")
truth = set(zip(m.iloc[:, 0].astype(str), m.iloc[:, 1].astype(str)))
a["id"], b["id"] = a["id"].astype(str), b["id"].astype(str)

# candidate search (unsupervised, no labels used): top-10 nearest ACM titles per DBLP record
vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1).fit(pd.concat([a.title, b.title]))
Xa, Xb = vec.transform(a.title), vec.transform(b.title)
nn = NearestNeighbors(n_neighbors=10, metric="cosine", algorithm="brute").fit(Xb)
dist, idx = nn.kneighbors(Xa)

rows = []
for i in range(len(a)):
    ra = a.iloc[i]
    for rank, (j, d) in enumerate(zip(idx[i], dist[i])):
        rb = b.iloc[j]
        rows.append({
            "a_id": ra["id"], "b_id": rb["id"], "year": ra["year"], "rank": rank, "cos": 1 - d,
            "title_ratio": fuzz.ratio(ra.title.lower(), rb.title.lower()) / 100,
            "title_set": fuzz.token_set_ratio(ra.title, rb.title) / 100,
            "authors_set": fuzz.token_set_ratio(ra.authors, rb.authors) / 100,
            "venue_part": fuzz.partial_ratio(ra.venue.lower(), rb.venue.lower()) / 100,
            "year_equal": float(str(ra.year) == str(rb.year)),
            "title_exact": float(ra.title.lower().strip() == rb.title.lower().strip()),
        })
P = pd.DataFrame(rows)
P["y"] = [int((x, z) in truth) for x, z in zip(P.a_id, P.b_id)]
F = ["cos", "rank", "title_ratio", "title_set", "authors_set", "venue_part", "year_equal"]

yr = pd.to_numeric(P.year, errors="coerce").fillna(0)
q60, q80 = yr.quantile(0.6), yr.quantile(0.8)
tr, va, te = (yr <= q60), (yr > q60) & (yr <= q80), (yr > q80)
print(f"pairs={len(P)} matches in truth={len(truth)} split sizes train/val/test={tr.sum()}/{va.sum()}/{te.sum()}")

lr = make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000)).fit(P.loc[tr, F], P.y[tr])
gb = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, n_jobs=2, random_state=42, verbose=-1).fit(P.loc[tr, F], P.y[tr])
S = {"exact": P.title_exact.to_numpy(),
     "fuzzy": (0.7 * P.title_set + 0.3 * P.authors_set).to_numpy(),
     "lr": lr.predict_proba(P[F])[:, 1], "lgbm": gb.predict_proba(P[F])[:, 1]}

t = P[te].reset_index(drop=True); y = t.y.to_numpy()
true_in_test = {p for p in truth if p[0] in set(t.a_id)}
out = {"dataset": "DBLP-ACM (public entity-matching benchmark, real records)", "note": "Method check, not payments data.",
       "test_pairs": int(len(t)), "test_true_matches": len(true_in_test),
       "candidate_recall": float(t.y.sum() / max(len(true_in_test), 1)), "methods": {}}
for k, s in S.items():
    s = s[te.to_numpy()]
    d = t.assign(s=s)
    top = d.sort_values("s", ascending=False).groupby("a_id").head(1)
    top1 = float(top.y.sum() / max(len(true_in_test), 1))
    out["methods"][k] = {"pr_auc": float(average_precision_score(y, s)), "pr_auc_ci95": M.bootstrap_ci(y, s), "top1_accuracy": top1}
(C.ART / "eval_json" / "benchmark.json").write_text(json.dumps(out, indent=2))
print("candidate recall:", round(out["candidate_recall"], 3), "| test true matches:", out["test_true_matches"])
for k, v in out["methods"].items():
    print(f"{k:6s} PR-AUC={v['pr_auc']:.3f} CI={[round(x, 3) for x in v['pr_auc_ci95']]} top1={v['top1_accuracy']:.3f}")