"""Bean leaf diagnosis: a small ImageNet encoder with a new head, exported as one ONNX file.

Serving depends only on onnxruntime, numpy and Pillow, so the container needs no deep learning
framework. `CropHealthModel` is the serving half; the training half lives in `imbuto.ml.train`.
"""

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps

from imbuto.ml.bundle import load_bundle

IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
UPLOAD_SIZE = 320
UPLOAD_QUALITY = 40


def preprocess(image: Image.Image) -> np.ndarray:
    """Shortest side to 256, centre crop to 224, ImageNet normalisation, as the encoder expects."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = 256 / min(image.size)
    image = image.resize(
        (round(image.width * scale), round(image.height * scale)), Image.Resampling.BICUBIC
    )
    left, top = (image.width - 224) // 2, (image.height - 224) // 2
    pixels = np.asarray(image.crop((left, top, left + 224, top + 224)), dtype=np.float32) / 255
    return (pixels.transpose(2, 0, 1) - IMAGE_MEAN) / IMAGE_STD


def shrink_for_upload(image: Image.Image) -> bytes:
    """What the browser does before upload on 2G; used here to test the model on the same bytes."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = UPLOAD_SIZE / min(image.size)
    resized = image.resize((round(image.width * scale), round(image.height * scale)))
    left, top = (resized.width - UPLOAD_SIZE) // 2, (resized.height - UPLOAD_SIZE) // 2
    square = resized.crop((left, top, left + UPLOAD_SIZE, top + UPLOAD_SIZE))
    buffer = io.BytesIO()
    square.save(buffer, "JPEG", quality=UPLOAD_QUALITY, optimize=True)
    return buffer.getvalue()


@dataclass
class Diagnosis:
    label: str
    confidence: float
    probabilities: dict[str, float]
    similarity: float
    outcome: str  # "confident", "unsure" or "not_a_leaf"


class CropHealthModel:
    def __init__(self, directory: Path):
        self.manifest = load_bundle(directory)
        self.card = self.manifest["card"]
        self.version = self.manifest["version"]
        self.labels: list[str] = self.card["labels"]
        self.confidence_threshold: float = self.card["confidence_threshold"]
        self.similarity_threshold: float = self.card["similarity_threshold"]
        self.centroid = np.array(json.loads((directory / "centroid.json").read_text()))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2  # stay polite on a small shared server
        self.session = ort.InferenceSession(
            str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )

    def predict_batch(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        probabilities, embeddings = self.session.run(None, {"pixel_values": batch})
        return probabilities, embeddings

    def predict(self, image_bytes: bytes) -> Diagnosis:
        image = Image.open(io.BytesIO(image_bytes))
        probabilities, embedding = self.predict_batch(preprocess(image)[None])
        probabilities = probabilities[0]
        index = int(probabilities.argmax())
        confidence = float(probabilities[index])
        similarity = cosine_similarity(embedding, self.centroid)[0]
        if similarity < self.similarity_threshold:
            outcome = "not_a_leaf"
        elif confidence < self.confidence_threshold:
            outcome = "unsure"
        else:
            outcome = "confident"
        return Diagnosis(
            label=self.labels[index],
            confidence=round(confidence, 3),
            probabilities={
                k: round(float(v), 3) for k, v in zip(self.labels, probabilities, strict=True)
            },
            similarity=round(float(similarity), 3),
            outcome=outcome,
        )


def cosine_similarity(embeddings: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(centroid)
    return (embeddings @ centroid) / np.clip(norm, 1e-9, None)
