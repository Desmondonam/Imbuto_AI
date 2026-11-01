"""Rain-shortfall risk: will the rest of this season be among the driest fifth for this commune?

Trained on real CHIRPS rainfall. Every statistic a model sees comes from earlier years only.
Rows in one year share the same weather, so the honest sample size is seasons, not rows, and
confidence intervals resample whole years.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

SHORTFALL_QUANTILE = 0.2
FEATURES = ["z_so_far", "z_prior", "z_last", "oni", "dmi", "is_season_a"]
Z_COLUMNS = {"z_so_far": "rain_so_far", "z_prior": "rain_prior_3m", "z_last": "rain_last_month"}


def _history_stats(train: pd.DataFrame) -> pd.DataFrame:
    grouped = train.groupby(["commune_id", "season"])
    stats = grouped[list(Z_COLUMNS.values())].agg(["mean", "std"])
    stats.columns = ["_".join(c) for c in stats.columns]
    stats["threshold"] = grouped["target_rain"].quantile(SHORTFALL_QUANTILE)
    return stats.reset_index()


def prepare(rows: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Express `rows` as anomalies against `history`, and label them by its thresholds."""
    out = rows.merge(_history_stats(history), on=["commune_id", "season"], how="left")
    for z, column in Z_COLUMNS.items():
        out[z] = (out[column] - out[f"{column}_mean"]) / out[f"{column}_std"].clip(lower=1e-6)
    out["is_season_a"] = (out["season"] == "A").astype(int)
    out["shortfall"] = (out["target_rain"] < out["threshold"]).astype(int)
    return out


def make_models() -> dict:
    return {
        "logistic": LogisticRegression(C=0.3, max_iter=1000),
        "gradient_boosting": HistGradientBoostingClassifier(
            max_depth=3, max_iter=120, learning_rate=0.05, min_samples_leaf=200, random_state=0
        ),
    }


def backtest(gold: pd.DataFrame, first_year: int = 2006) -> pd.DataFrame:
    """Walk forward by year: for each test season, train only on seasons before it."""
    results = []
    known = gold.dropna(subset=["target_rain"])
    for year in sorted(y for y in known["year"].unique() if y >= first_year):
        history = known[known["year"] < year]
        test = known[known["year"] == year]
        train_x = prepare(history, history)
        test_x = prepare(test, history)
        frame = test_x[["commune_id", "season", "year", "shortfall"]].copy()
        frame["climatology"] = SHORTFALL_QUANTILE
        for name, model in make_models().items():
            model.fit(train_x[FEATURES], train_x["shortfall"])
            frame[name] = model.predict_proba(test_x[FEATURES])[:, 1]
        results.append(frame)
    return pd.concat(results, ignore_index=True)


def _skill(y: np.ndarray, p: np.ndarray) -> float:
    reference = brier_score_loss(y, np.full(len(y), SHORTFALL_QUANTILE))
    return 1 - brier_score_loss(y, p) / reference


def evaluate(results: pd.DataFrame, models: list[str], boot: int = 1000) -> dict:
    """Skill against always predicting the base rate, with a by-season bootstrap interval."""
    rng = np.random.default_rng(0)
    seasons = list(results.groupby(["year", "season"]).indices.values())
    report = {}
    for name in models:
        y, p = results["shortfall"].to_numpy(), results[name].to_numpy()
        draws = []
        for _ in range(boot):
            picks = rng.integers(0, len(seasons), len(seasons))
            idx = np.concatenate([seasons[i] for i in picks])
            draws.append(_skill(y[idx], p[idx]))
        report[name] = {
            "brier_skill": round(_skill(y, p), 3),
            "brier_skill_ci90": [round(float(q), 3) for q in np.quantile(draws, [0.05, 0.95])],
            "auc": round(roc_auc_score(y, p), 3),
            "brier": round(brier_score_loss(y, p), 4),
        }
    return report


def promotion_gate(report: dict) -> dict:
    """A forecast reaches farmers only if it demonstrably beats the base rate.

    The lower end of the 90% interval must be above zero. A point estimate is not enough: with
    about 40 test seasons, a lucky score is easy to get and costly to act on.
    """
    best = max(report, key=lambda name: report[name]["brier_skill"])
    lower = report[best]["brier_skill_ci90"][0]
    return {
        "best_model": best,
        "rule": "lower bound of 90% interval on Brier skill must exceed 0",
        "lower_bound": lower,
        "passed": lower > 0,
    }


def by_season(results: pd.DataFrame, name: str) -> dict:
    return {
        season: {
            "auc": round(roc_auc_score(part["shortfall"], part[name]), 3),
            "brier_skill": round(_skill(part["shortfall"].to_numpy(), part[name].to_numpy()), 3),
            "shortfall_rate": round(float(part["shortfall"].mean()), 3),
        }
        for season, part in results.groupby("season")
    }
