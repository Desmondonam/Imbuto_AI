"""Train the crop model and package both bundles. Run with `make train`."""

import io
import json
import shutil
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import pandas as pd
from onnx import helper, numpy_helper, version_converter
from onnxruntime.quantization import (
    CalibrationDataReader,
    QuantFormat,
    QuantType,
    quantize_static,
)
from onnxruntime.quantization.shape_inference import quant_pre_process
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report

from imbuto.ml import risk
from imbuto.ml.bundle import write_bundle
from imbuto.ml.crop_health import (
    CropHealthModel,
    cosine_similarity,
    preprocess,
    shrink_for_upload,
)
from imbuto.settings import ARTIFACTS, DATA

BRONZE = DATA / "bronze"
LABELS = ["angular_leaf_spot", "bean_rust", "healthy"]
TARGET_PRECISION = 0.98
MAX_QUANTISATION_LOSS = 0.02
EMBEDDING = "/flatten/Flatten_output_0"


def _images(split: str) -> tuple[list[bytes], np.ndarray]:
    table = pd.read_parquet(BRONZE / "beans" / f"{split}.parquet")
    return [row["bytes"] for row in table["image"]], table["labels"].to_numpy()


def embed(session: ort.InferenceSession, images: list[bytes], batch: int = 16) -> np.ndarray:
    out = []
    for start in range(0, len(images), batch):
        pixels = np.stack(
            [preprocess(Image.open(io.BytesIO(b))) for b in images[start : start + batch]]
        )
        out.append(session.run(None, {"pixel_values": pixels})[0])
    return np.concatenate(out)


def _encoder_session(path: Path) -> ort.InferenceSession:
    """Expose the layer before the ImageNet classifier."""
    model = onnx.load(path)
    model.graph.output.clear()
    model.graph.output.append(helper.make_tensor_value_info(EMBEDDING, onnx.TensorProto.FLOAT, None))
    return ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])


def export_onnx(source: Path, head: LogisticRegression, target: Path) -> None:
    """Swap the 1,000-class classifier for ours, keeping one self-contained graph."""
    model = onnx.load(source)
    graph = model.graph
    old = next(n for n in graph.node if n.name == "/classifier/Gemm")
    for name in list(old.input[1:]):
        init = next(i for i in graph.initializer if i.name == name)
        graph.initializer.remove(init)
    graph.node.remove(old)
    graph.initializer.extend([
        numpy_helper.from_array(head.coef_.astype(np.float32), "head.weight"),
        numpy_helper.from_array(head.intercept_.astype(np.float32), "head.bias"),
    ])  # fmt: skip
    graph.node.extend([
        helper.make_node("Gemm", [EMBEDDING, "head.weight", "head.bias"], ["head_logits"],
                         alpha=1.0, beta=1.0, transB=1, name="/head/Gemm"),
        helper.make_node("Softmax", ["head_logits"], ["probabilities"], axis=1, name="/head/Softmax"),
        helper.make_node("Identity", [EMBEDDING], ["embedding"], name="/head/Embedding"),
    ])  # fmt: skip
    graph.output.clear()
    graph.output.extend([
        helper.make_tensor_value_info("probabilities", onnx.TensorProto.FLOAT, [None, len(LABELS)]),
        helper.make_tensor_value_info("embedding", onnx.TensorProto.FLOAT, [None, None]),
    ])  # fmt: skip
    model = version_converter.convert_version(model, 13)  # per-channel quantisation needs 13
    onnx.checker.check_model(model)
    onnx.save(model, target)


class _Calibration(CalibrationDataReader):
    """Real images, so quantisation ranges match what the model will see in use."""

    def __init__(self, images: list[bytes]):
        self.batches = iter(
            {"pixel_values": preprocess(Image.open(io.BytesIO(b)))[None]} for b in images
        )

    def get_next(self) -> dict | None:
        return next(self.batches, None)


def quantise(float_path: Path, target: Path, calibration: list[bytes]) -> None:
    """Static quantisation. Dynamic quantisation silently dropped this CNN to chance accuracy."""
    prepared = float_path.with_suffix(".prepared.onnx")
    quant_pre_process(str(float_path), str(prepared))
    quantize_static(
        str(prepared),
        str(target),
        _Calibration(calibration),
        quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QUInt8,
        per_channel=True,
        nodes_to_exclude=["/head/Gemm", "/head/Softmax"],
    )


def _choose_confidence(probabilities: np.ndarray, y: np.ndarray) -> float:
    """Lowest confidence at which validation answers meet the target precision."""
    confidence, predicted = probabilities.max(1), probabilities.argmax(1)
    for threshold in np.arange(0.40, 0.96, 0.01):
        kept = confidence >= threshold
        if kept.sum() and (predicted[kept] == y[kept]).mean() >= TARGET_PRECISION:
            return round(float(threshold), 2)
    return 0.95


def _outside_images(count: int = 200) -> list[bytes]:
    """Everyday photos that are not bean leaves, for tuning and testing the leaf check."""
    path = BRONZE / "ood.parquet"
    table = pd.read_parquet(path).sample(count, random_state=0)
    return [row["bytes"] for row in table["img"]]


def train_crop_health() -> dict:
    encoder = BRONZE / "encoder" / "model.onnx"
    session = _encoder_session(encoder)
    train_images, y_train = _images("train")
    val_images, y_val = _images("validation")
    test_images, y_test = _images("test")
    x_train, x_val = embed(session, train_images), embed(session, val_images)

    # Standardise inside the graph-free head by dividing by a constant, so ONNX stays simple.
    scale = float(x_train.std())
    search = {}
    for c in (0.01, 0.03, 0.1, 0.3, 1.0):
        head = LogisticRegression(C=c, max_iter=3000).fit(x_train / scale, y_train)
        search[c] = accuracy_score(y_val, head.predict(x_val / scale))
    best_c = max(search, key=search.get)
    head = LogisticRegression(C=best_c, max_iter=3000).fit(x_train / scale, y_train)
    head.coef_ = head.coef_ / scale  # bake the scaling into the exported weights

    directory = ARTIFACTS / "crop_health"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    float_path = DATA / "crop_health_float.onnx"
    export_onnx(encoder, head, float_path)
    centroid = x_train.mean(0)
    (directory / "centroid.json").write_text(json.dumps([round(float(v), 5) for v in centroid]))

    def session_for(path: Path) -> ort.InferenceSession:
        return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    def probabilities_on(session: ort.InferenceSession, images: list[bytes]) -> np.ndarray:
        return np.concatenate([
            session.run(None, {"pixel_values": preprocess(Image.open(io.BytesIO(b)))[None]})[0]
            for b in images
        ])  # fmt: skip

    # Quantised weights must earn their place: ship them only if accuracy holds.
    quantised_path = DATA / "crop_health_quantised.onnx"
    quantise(float_path, quantised_path, train_images[::10])
    float_accuracy = accuracy_score(
        y_val, probabilities_on(session_for(float_path), val_images).argmax(1)
    )
    quantised_accuracy = accuracy_score(
        y_val, probabilities_on(session_for(quantised_path), val_images).argmax(1)
    )
    quantised_ok = quantised_accuracy >= float_accuracy - MAX_QUANTISATION_LOSS
    shutil.copy(quantised_path if quantised_ok else float_path, directory / "model.onnx")

    # From here on, measure the exported artifact, not the in-memory objects.
    exported = session_for(directory / "model.onnx")

    def run(images: list[bytes]) -> tuple[np.ndarray, np.ndarray]:
        parts = [
            exported.run(None, {"pixel_values": preprocess(Image.open(io.BytesIO(b)))[None]})
            for b in images
        ]
        return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])

    val_probs, val_emb = run(val_images)
    threshold = _choose_confidence(val_probs, y_val)
    outside = _outside_images()
    outside_tune, outside_test = outside[:100], outside[100:]
    in_sim = cosine_similarity(val_emb, centroid)
    similarity_threshold = round(float(np.quantile(in_sim, 0.02)), 3)

    test_probs, test_emb = run(test_images)
    predicted = test_probs.argmax(1)
    small = [shrink_for_upload(Image.open(io.BytesIO(b))) for b in test_images]
    small_probs, _ = run(small)
    _, outside_emb = run(outside_test)
    outside_rejected = cosine_similarity(outside_emb, centroid) < similarity_threshold
    keep = test_probs.max(1) >= threshold
    in_rejected = cosine_similarity(test_emb, centroid) < similarity_threshold

    started = time.perf_counter()
    for _ in range(20):
        exported.run(None, {"pixel_values": preprocess(Image.open(io.BytesIO(small[0])))[None]})
    latency_ms = (time.perf_counter() - started) / 20 * 1000

    card = {
        "model": "MobileNetV4-Conv-Small (ImageNet, Apache-2.0) with a logistic head",
        "task": "Bean leaf diagnosis from a phone photo",
        "labels": LABELS,
        "confidence_threshold": threshold,
        "similarity_threshold": similarity_threshold,
        "weights": "quantised" if quantised_ok else "float (quantised failed its accuracy check)",
        "training_data": "iBean (AI-Lab-Makerere/beans, MIT): field photos from Uganda",
        "intended_use": "Decision support for bean leaves, confirmed by an agronomist",
        "not_for": "Other crops, pesticide selection, or use without human follow-up",
        "known_limits": [
            "No Burundian test images yet: accuracy here may not hold in Burundi",
            "Beans only, and only two diseases",
            "Leaf check tested on small everyday images, not other crops: other leaves may pass",
        ],
        "metrics": {
            "test_images": len(y_test),
            "validation_accuracy_float": round(float_accuracy, 3),
            "validation_accuracy_quantised": round(quantised_accuracy, 3),
            "test_accuracy": round(accuracy_score(y_test, predicted), 3),
            "test_accuracy_after_2g_shrink": round(
                accuracy_score(y_test, small_probs.argmax(1)), 3
            ),
            "answered_share": round(float(keep.mean()), 3),
            "accuracy_when_answered": round(float((predicted[keep] == y_test[keep]).mean()), 3),
            "non_leaf_rejected": round(float(outside_rejected.mean()), 3),
            "real_leaf_wrongly_rejected": round(float(in_rejected.mean()), 3),
            "median_upload_bytes": int(np.median([len(b) for b in small])),
            "quantised_model_bytes": quantised_path.stat().st_size,
            "model_bytes": (directory / "model.onnx").stat().st_size,
            "cpu_latency_ms_laptop": round(latency_ms, 1),
            "per_class": classification_report(
                y_test, predicted, target_names=LABELS, output_dict=True, zero_division=0
            ),
        },
    }
    del outside_tune  # kept apart for future threshold tuning
    return write_bundle(directory, "crop_health", "1.0.0", card)


def _status(row: pd.Series) -> str:
    rank = row["percentile"]
    if rank < 10:
        return "very_dry"
    if rank < 25:
        return "dry"
    if rank > 90:
        return "very_wet"
    if rank > 75:
        return "wet"
    return "normal"


def train_rain() -> dict:
    gold = pd.read_parquet(DATA / "gold" / "season_features.parquet")
    climate = pd.read_parquet(DATA / "silver" / "climate.parquet")
    results = risk.backtest(gold)
    models = ["logistic", "gradient_boosting"]
    report = risk.evaluate(results, models)
    gate = risk.promotion_gate(report)
    best = gate["best_model"]

    known = gold.dropna(subset=["target_rain"])
    latest = gold.sort_values(["year", "season"]).groupby("commune_id").tail(1)
    latest = gold[gold["year"].eq(latest["year"].max())]
    latest = latest[latest["target_rain"].isna()]
    if latest.empty:
        last_year = gold["year"].max()
        latest = gold[(gold["year"] == last_year) & (gold["season"] == "B")]
    season, year = latest.iloc[0]["season"], int(latest.iloc[0]["year"])

    train_x = risk.prepare(known, known)
    model = risk.make_models()[best].fit(train_x[risk.FEATURES], train_x["shortfall"])
    current = risk.prepare(latest, known)
    current["forecast"] = model.predict_proba(current[risk.FEATURES])[:, 1]
    history = known[known["season"] == season]
    records = []
    for row in current.itertuples():
        past = history[history["commune_id"] == row.commune_id]["rain_so_far"]
        records.append({
            "commune_id": row.commune_id, "rain_mm": round(float(row.rain_so_far), 1),
            "normal_mm": round(float(past.mean()), 1),
            "percent_of_normal": round(float(row.rain_so_far / past.mean() * 100)),
            "percentile": round(float((past < row.rain_so_far).mean() * 100)),
            "experimental_shortfall_probability": round(float(row.forecast), 3),
        })  # fmt: skip
    for record in records:
        record["status"] = _status(pd.Series(record))

    directory = ARTIFACTS / "rain"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    observed_through = pd.read_parquet(DATA / "silver" / "rain_monthly.parquet")["month"].max()
    latest_climate = climate.dropna(subset=["oni"]).iloc[-1]
    summary = {
        "season": season,
        "year": year,
        "observed_through": observed_through.strftime("%Y-%m"),
        "source": "CHIRPS v2.0 monthly rainfall, compared with 1981 to last season",
        "oni_latest": float(latest_climate["oni"]),
        "communes": records,
    }
    (directory / "rain_status.json").write_text(json.dumps(summary))
    card = {
        "task": "Rain status for farmers; shortfall forecast for analysts only",
        "target": "Rest-of-season rain in the driest fifth of that commune's history",
        "backtest": {"period": "2006-2026, walk-forward", "scores": report,
                     "by_season": risk.by_season(results, best)},
        "promotion_gate": gate,
        "farmer_facing_forecast": gate["passed"],
    }  # fmt: skip
    return write_bundle(directory, "rain", "1.0.0", card)


def train_all() -> None:
    for manifest in (train_crop_health(), train_rain()):
        print(json.dumps({k: manifest[k] for k in ("name", "version", "card")}, indent=1)[:3000])


if __name__ == "__main__":
    train_all()
