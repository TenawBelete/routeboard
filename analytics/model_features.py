"""Feature and label construction for the withdrawal-risk model.

Unit of prediction: one (peer_asn, 5-minute window). Features use only that
window and the three before it; the label is about the NEXT window. So nothing
the model sees can leak the answer, which was the flaw in the course version
(there, null origin_asn identified withdrawals directly).
"""

import numpy as np
import pandas as pd

LAGS = 3
FEATURES = ["rate_t0", "rate_t1", "rate_t2", "rate_t3",
            "log_updates_t0", "delta_updates", "hour_sin", "hour_cos"]


def build(peers: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """peers: columns window_start (tz-aware), peer_asn, updates, withdrawals.
    Returns one row per (peer, window) that has LAGS history and a next window."""
    df = peers.sort_values(["peer_asn", "window_start"]).copy()
    df["rate"] = np.where(df["updates"] > 0, df["withdrawals"] / df["updates"], 0.0)

    g = df.groupby("peer_asn", sort=False)
    step = pd.Timedelta(minutes=5)
    # Only use consecutive windows; a gap means the peer was quiet, not zero-rate.
    for k in range(LAGS + 1):
        df[f"rate_t{k}"] = g["rate"].shift(k)
        df[f"_ws_t{k}"] = g["window_start"].shift(k)
    df["_ws_next"] = g["window_start"].shift(-1)
    df["rate_next"] = g["rate"].shift(-1)
    df["_upd_t1"] = g["updates"].shift(1)

    contiguous = np.ones(len(df), dtype=bool)
    for k in range(1, LAGS + 1):
        contiguous &= (df[f"_ws_t{k-1}"] - df[f"_ws_t{k}"]) == step
    contiguous &= (df["_ws_next"] - df["window_start"]) == step
    df = df[contiguous].copy()

    df["log_updates_t0"] = np.log1p(df["updates"])
    df["delta_updates"] = np.log1p(df["updates"]) - np.log1p(df["_upd_t1"])
    hour = df["window_start"].dt.hour + df["window_start"].dt.minute / 60
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["label"] = (df["rate_next"] >= threshold).astype(int)
    return df[["window_start", "peer_asn", "label", "rate_next"] + FEATURES].reset_index(drop=True)


def time_split(ds: pd.DataFrame, test_fraction: float = 0.2):
    """Train on the earlier part of time, test on the later part. Never random."""
    cut = ds["window_start"].quantile(1 - test_fraction)
    train = ds[ds["window_start"] < cut]
    test = ds[ds["window_start"] >= cut]
    return train, test
