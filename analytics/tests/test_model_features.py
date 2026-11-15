import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_features import FEATURES, build, time_split  # noqa: E402


def peer_series(asn, start, n, updates, withdrawals):
    return pd.DataFrame({
        "window_start": pd.date_range(start, periods=n, freq="5min", tz="UTC"),
        "peer_asn": asn, "updates": updates, "withdrawals": withdrawals})


def test_label_is_about_next_window_and_features_only_past():
    # withdrawals spike in window 6 only -> the row for window 5 must be labelled 1,
    # and that row's own features must not see the spike.
    upd = [100] * 10
    wd = [0] * 10; wd[6] = 50
    ds = build(peer_series(1, "2026-11-14 00:00", 10, upd, wd), threshold=0.25)
    by_ws = ds.set_index("window_start")
    t5 = pd.Timestamp("2026-11-14 00:25", tz="UTC")
    t6 = pd.Timestamp("2026-11-14 00:30", tz="UTC")
    assert by_ws.loc[t5, "label"] == 1
    assert by_ws.loc[t5, "rate_t0"] == 0          # the spike is NOT in its features
    assert by_ws.loc[t6, "rate_t0"] == 0.5 and by_ws.loc[t6, "label"] == 0
    assert ds["label"].sum() == 1


def test_gaps_break_contiguity():
    s = peer_series(1, "2026-11-14 00:00", 10, [10] * 10, [0] * 10)
    s = s.drop(index=5)                               # a missing window in the middle
    ds = build(s, 0.25)
    # rows needing window 5 as a lag or as "next" must be gone
    missing = pd.Timestamp("2026-11-14 00:25", tz="UTC")
    for _, r in ds.iterrows():
        assert r.window_start != missing
    assert len(ds) < 10 - 4


def test_time_split_is_chronological():
    s = peer_series(1, "2026-11-14 00:00", 100, [10] * 100, [0] * 100)
    ds = build(s, 0.25)
    tr, te = time_split(ds, 0.2)
    assert tr["window_start"].max() < te["window_start"].min()
    assert set(FEATURES) <= set(ds.columns)
    assert not ds[FEATURES].isna().any().any()
