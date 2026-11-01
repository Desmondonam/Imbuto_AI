"""Drive a running server with normal traffic, then with shifted photos, to show monitoring.

Normal traffic uses held-out bean images. The drifted burst darkens and blurs them, as a dusty
lens at dusk might. It is simulated, so numbers on /ops are for demonstration, not field results.
"""

import argparse
import io
import random
import time

import pandas as pd
import requests
from PIL import Image, ImageEnhance, ImageFilter

from imbuto.ml.crop_health import shrink_for_upload
from imbuto.settings import DATA

QUESTIONS = [
    ("How do I store maize after harvest?", "en"),
    ("mes haricots ont des taches orange", "fr"),
    ("Ibiharage vyanje bifise indwara", "rn"),
    ("Is there a subsidy for fertiliser this season?", "en"),
    ("Comment vendre mon cafe a l'etranger ?", "fr"),
]


def degrade(image: Image.Image) -> Image.Image:
    image = ImageEnhance.Brightness(image.convert("RGB")).enhance(0.45)
    return image.filter(ImageFilter.GaussianBlur(4))


def post_photo(base: str, data: bytes) -> dict:
    files = {"image": ("leaf.jpg", data, "image/jpeg")}
    while True:
        response = requests.post(f"{base}/api/v1/diagnose", files=files, timeout=30)
        if response.status_code != 429:  # the rate limit is doing its job: wait, do not crash
            response.raise_for_status()
            return response.json()
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--count", type=int, default=28)
    parser.add_argument("--pause", type=float, default=2.5, help="seconds, to respect the limit")
    args = parser.parse_args()
    table = pd.read_parquet(DATA / "bronze" / "beans" / "test.parquet")
    labels = table["labels"].tolist()
    images = [Image.open(io.BytesIO(row["bytes"])) for row in table["image"]]
    random.seed(0)
    order = random.sample(range(len(images)), len(images))

    def run(indices: list[int], change) -> None:
        for index in indices:
            result = post_photo(args.base, shrink_for_upload(change(images[index])))
            print(result["outcome"], result["label"], result["confidence"])
            if result["outcome"] == "confident" and random.random() < 0.5:
                correct = ["angular_leaf_spot", "bean_rust", "healthy"][labels[index]]
                requests.post(f"{args.base}/api/v1/feedback", timeout=30, json={
                    "prediction_id": result["prediction_id"],
                    "correct": result["label"] == correct,
                })  # fmt: skip
            time.sleep(args.pause)

    for question, lang in QUESTIONS:
        requests.post(f"{args.base}/api/v1/advice", timeout=30,
                      json={"question": question, "lang": lang})  # fmt: skip
    run(order[: args.count], lambda image: image)
    print("Now sending the drifted burst")
    run(order[args.count : args.count * 2], degrade)


if __name__ == "__main__":
    main()
