"""Bronze layer: download open sources exactly as published, and record where they came from."""

import datetime as dt
import hashlib
import json
from pathlib import Path

import requests

from imbuto.settings import DATA

BRONZE = DATA / "bronze"
_GB = "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/BDI"
_HDX = "https://data.humdata.org/dataset/e7e5df38-adb6-4843-a053-24e119b27afc/resource"
_IRI = "https://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.monthly/.global/.precipitation"

SOURCES = {
    "chirps_monthly.nc": f"{_IRI}/X/28.95/30.9/RANGEEDGES/Y/-4.5/-2.25/RANGEEDGES/data.nc",
    "wfp_food_prices_bdi.csv": f"{_HDX}/efa227dd-2fd5-437e-b79d-130af02b769d/download/wfp_food_prices_bdi.csv",
    "adm1.geojson": f"{_GB}/ADM1/geoBoundaries-BDI-ADM1_simplified.geojson",
    "adm2.geojson": f"{_GB}/ADM2/geoBoundaries-BDI-ADM2_simplified.geojson",
    "oni.txt": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "dmi.txt": "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data",
}


def fetch_all(force: bool = False, bronze: Path = BRONZE) -> dict[str, dict]:
    """Download each source once. The manifest makes every later result traceable."""
    bronze.mkdir(parents=True, exist_ok=True)
    manifest_path = bronze / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, url in SOURCES.items():
        target = bronze / name
        if target.exists() and not force:
            continue
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        target.write_bytes(response.content)
        manifest[name] = {
            "url": url,
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "bytes": len(response.content),
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
