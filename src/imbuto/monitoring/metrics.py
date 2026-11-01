"""Live monitoring: Prometheus counters, plus drift and quality read from the prediction log."""

import math
import time

import numpy as np
from prometheus_client import Counter, Histogram

from imbuto.monitoring.store import Store

REQUESTS = Counter("imbuto_requests_total", "Requests handled", ["channel"])
PREDICTIONS = Counter("imbuto_predictions_total", "Crop predictions", ["outcome"])
ESCALATIONS = Counter("imbuto_escalations_total", "Questions handed to a person")
LATENCY = Histogram(
    "imbuto_inference_seconds", "Model inference time",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)  # fmt: skip

MIN_SAMPLE = 30
# Alert on recent photos, because a 24-hour average lets healthy traffic hide a shift. In notebook
# 6 this rule gave 0.4% false alarms, against 57% for PSI above 0.25 on the same 30-photo windows,
# so PSI is shown for context only.
ALERT_WINDOW = 30
ALERT_FLAGGED = 12
_BINS = np.linspace(0.0, 1.0, 11)


def psi(reference: list[float], current: list[float]) -> float:
    """Population Stability Index, a rough comparison of two distributions."""
    expected = np.histogram(reference, _BINS)[0] / len(reference)
    actual = np.histogram(current, _BINS)[0] / len(current)
    expected, actual = np.clip(expected, 1e-4, None), np.clip(actual, 1e-4, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def summary(store: Store, reference_confidence: list[float], hours: int = 24) -> dict:
    since = time.time() - hours * 3600
    with store.db() as con:
        rows = con.execute(
            "select outcome, confidence, latency_ms from predictions where ts > ?", (since,)
        ).fetchall()
        recent = con.execute(
            "select outcome from predictions order by id desc limit ?", (ALERT_WINDOW,)
        ).fetchall()
        feedback = con.execute(
            "select count(*) n, sum(correct) ok from feedback where ts > ?", (since,)
        ).fetchone()
        questions = con.execute(
            "select count(*) n, sum(escalated) e from questions where ts > ?", (since,)
        ).fetchone()
        gaps = con.execute(
            """select question, lang, score from questions where escalated = 1
            order by ts desc limit 8"""
        ).fetchall()
        reports = con.execute(
            "select kind, count(*) n from reports where ts > ? group by kind", (since,)
        ).fetchall()
    count = len(rows)
    latencies = [r["latency_ms"] for r in rows]
    outcomes = {o: sum(r["outcome"] == o for r in rows) for o in
                ("confident", "unsure", "not_a_leaf")}  # fmt: skip
    leaves = [r["confidence"] for r in rows if r["outcome"] != "not_a_leaf"]
    drift = psi(reference_confidence, leaves) if len(leaves) >= MIN_SAMPLE else None
    flagged = sum(r["outcome"] != "confident" for r in recent)
    return {
        "hours": hours,
        "predictions": count,
        "outcomes": outcomes,
        "unsure_rate": round(outcomes["unsure"] / count, 3) if count else None,
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 1) if latencies else None,
        "drift_psi": None if drift is None or math.isnan(drift) else round(drift, 3),
        "drift_alert": len(recent) >= ALERT_WINDOW and flagged >= ALERT_FLAGGED,
        "recent_flagged": flagged,
        "recent_count": len(recent),
        "drift_min_sample": MIN_SAMPLE,
        "feedback_count": feedback["n"],
        "feedback_agreement": round(feedback["ok"] / feedback["n"], 3) if feedback["n"] else None,
        "questions": questions["n"],
        "escalation_rate": round((questions["e"] or 0) / questions["n"], 3)
        if questions["n"] else None,
        "knowledge_gaps": [dict(g) for g in gaps],
        "reports": {r["kind"]: r["n"] for r in reports},
    }  # fmt: skip
