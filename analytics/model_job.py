"""Six-hourly withdrawal-risk model.

Question: for a peer that is active right now, will its withdrawal rate in the
NEXT 5-minute window be elevated (>= LABEL_THRESHOLD)?

Data: kpi_peers_5m in Postgres (last MODEL_HISTORY_DAYS). Train/test split is by
time. Metrics are reported against a baseline that always predicts the
training positive rate (AUC 0.5), so the dashboard can show whether the model
adds anything. The run and the latest predictions are written to Postgres.
"""

import json
import logging
import os
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import connect
from model_features import FEATURES, build, time_split

HISTORY_DAYS = int(os.environ.get("MODEL_HISTORY_DAYS", "7"))
THRESHOLD = float(os.environ.get("MODEL_LABEL_THRESHOLD", "0.25"))
MIN_ROWS = int(os.environ.get("MODEL_MIN_ROWS", "500"))
KEEP_RUNS_DAYS = int(os.environ.get("MODEL_KEEP_RUNS_DAYS", "30"))
TOP_PREDICTIONS = int(os.environ.get("MODEL_TOP_PREDICTIONS", "200"))
log = logging.getLogger("model_job")


def load_peers(conn) -> pd.DataFrame:
    return pd.read_sql_query(
        "select window_start, peer_asn, updates, withdrawals from kpi_peers_5m "
        "where window_start >= now() - make_interval(days => %s) order by peer_asn, window_start",
        conn, params=(HISTORY_DAYS,))


def train(ds: pd.DataFrame):
    tr, te = time_split(ds)
    model = make_pipeline(StandardScaler(),
                          LogisticRegression(class_weight="balanced", max_iter=1000))
    model.fit(tr[FEATURES], tr["label"])
    prob = model.predict_proba(te[FEATURES])[:, 1]
    pred = prob >= 0.5
    y = te["label"].values
    metrics = {
        "auc": float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else None,
        "precision_": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "baseline_auc": 0.5,
    }
    coef = dict(zip(FEATURES, model[-1].coef_[0].round(4).tolist()))
    return model, tr, te, metrics, coef


def fill_actuals(cur) -> None:
    """Once the next window is known, record what really happened for earlier predictions."""
    cur.execute("""
        update model_predictions p
           set actual = (case when k.updates > 0 then k.withdrawals::float / k.updates else 0 end) >= %s
          from kpi_peers_5m k
         where p.actual is null
           and k.peer_asn = p.peer_asn
           and k.window_start = p.window_start + interval '5 minutes'""", (THRESHOLD,))


def main() -> int:
    with connect() as conn:
        peers = load_peers(conn)
        ds = build(peers, THRESHOLD)
        if len(ds) < MIN_ROWS or ds["label"].nunique() < 2:
            log.warning("not enough data yet: %d rows, %d classes (need %d rows, 2 classes)",
                        len(ds), ds["label"].nunique(), MIN_ROWS)
            return 0

        model, tr, te, m, coef = train(ds)
        log.info("trained on %d, tested on %d: AUC=%s P=%.3f R=%.3f F1=%.3f (positive rate %.3f)",
                 len(tr), len(te), m["auc"], m["precision_"], m["recall"], m["f1"], ds["label"].mean())

        # Predict for the newest window of each peer (the one whose "next" is still unknown).
        latest_ws = peers["window_start"].max()
        current = build(pd.concat([peers, _ghost_next(peers, latest_ws)]), THRESHOLD)
        current = current[current["window_start"] == latest_ws]
        current["probability"] = model.predict_proba(current[FEATURES])[:, 1]
        current = current.nlargest(TOP_PREDICTIONS, "probability")

        with conn.cursor() as cur:
            cur.execute("""insert into model_runs (model_type, label_rule, train_from, train_to, test_from, test_to,
                             n_train, n_test, positive_rate, auc, precision_, recall, f1, baseline_auc, features, coefficients)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning run_id""",
                        ("logistic_regression", f"next_window_withdraw_rate >= {THRESHOLD}",
                         tr["window_start"].min(), tr["window_start"].max(),
                         te["window_start"].min(), te["window_start"].max(),
                         len(tr), len(te), float(ds["label"].mean()),
                         m["auc"], m["precision_"], m["recall"], m["f1"], m["baseline_auc"],
                         json.dumps(FEATURES), json.dumps(coef)))
            run_id = cur.fetchone()[0]
            cur.executemany("insert into model_predictions (run_id, window_start, peer_asn, probability, predicted) "
                            "values (%s,%s,%s,%s,%s)",
                            [(run_id, r.window_start.to_pydatetime(), int(r.peer_asn),
                              float(r.probability), bool(r.probability >= 0.5))
                             for r in current.itertuples(index=False)])
            fill_actuals(cur)
            cur.execute("delete from model_runs where trained_at < now() - make_interval(days => %s)",
                        (KEEP_RUNS_DAYS,))
        conn.commit()
        log.info("run %d stored with %d predictions", run_id, len(current))
    return 0


def _ghost_next(peers: pd.DataFrame, latest_ws) -> pd.DataFrame:
    """build() needs a 'next' window to exist; add an empty placeholder so the
    newest real window becomes a prediction row. Its label is discarded."""
    last = peers[peers["window_start"] == latest_ws][["peer_asn"]].copy()
    last["window_start"] = latest_ws + timedelta(minutes=5)
    last["updates"] = 0
    last["withdrawals"] = 0
    return last


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("model job failed")
        raise SystemExit(1)
