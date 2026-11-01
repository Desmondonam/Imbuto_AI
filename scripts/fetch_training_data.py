"""Download the images and encoder used for training. Not needed to run the service."""

import requests

from imbuto.settings import DATA

BRONZE = DATA / "bronze"
BEANS = "https://huggingface.co/datasets/AI-Lab-Makerere/beans/resolve/main/data"
ENCODER = (
    "https://huggingface.co/onnx-community/mobilenetv4_conv_small.e2400_r224_in1k/resolve/main"
)
OOD = "https://huggingface.co/datasets/uoft-cs/cifar10/resolve/main/plain_text"

FILES = {
    **{f"beans/{s}.parquet": f"{BEANS}/{s}-00000-of-00001.parquet"
       for s in ("train", "validation", "test")},
    "encoder/model.onnx": f"{ENCODER}/onnx/model.onnx",
    "ood.parquet": f"{OOD}/test-00000-of-00001.parquet",
}  # fmt: skip

for name, url in FILES.items():
    target = BRONZE / name
    if target.exists():
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=600)
    response.raise_for_status()
    target.write_bytes(response.content)
    print(f"{name}: {len(response.content) / 1e6:.1f} MB")
