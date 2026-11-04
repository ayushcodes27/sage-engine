"""Shared client-level aggregation and threshold rules of configs/offline_protocol_v1.json."""

import numpy as np
import pandas as pd


def client_table(sessions, prob):
    """One row per client: label (if its scored known-label sessions agree) and score = max probability.

    sessions: DataFrame with IpId and label ('bot'/'human') of scored known-label sessions, aligned with prob.
    Returns (clients, n_mixed) where clients has columns IpId, y (1 = bot), score.
    """
    df = pd.DataFrame({"IpId": sessions["IpId"].values, "y": (sessions["label"].values == "bot").astype(int),
                       "score": np.asarray(prob, dtype=float)})
    g = df.groupby("IpId").agg(y_min=("y", "min"), y_max=("y", "max"), score=("score", "max"))
    mixed = g["y_min"] != g["y_max"]
    out = g.loc[~mixed].reset_index().rename(columns={"y_min": "y"})[["IpId", "y", "score"]]
    return out, int(mixed.sum())


def threshold_at_fpr(human_scores, max_fpr):
    """Smallest threshold t with FPR = #(human score >= t) / N <= max_fpr (flag if score >= t)."""
    h = np.sort(np.asarray(human_scores, dtype=float))[::-1]
    k = int(np.floor(max_fpr * len(h)))  # number of false positives allowed
    if k >= len(h):
        return float(h[-1])
    return float(np.nextafter(h[k], np.inf))  # excludes the (k+1)-th highest human score and its ties


def confusion(y, score, t):
    y, flag = np.asarray(y), np.asarray(score) >= t
    return {"tp": int(((y == 1) & flag).sum()), "fn": int(((y == 1) & ~flag).sum()),
            "fp": int(((y == 0) & flag).sum()), "tn": int(((y == 0) & ~flag).sum())}
