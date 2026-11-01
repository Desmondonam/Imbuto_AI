"""Silver and gold layers: turn raw downloads into commune-level tables.

Grain of silver rainfall: one row per commune and month. Grain of gold: one row per commune and
season. Boundaries are the 119 pre-reform communes, grouped into the five current provinces,
because no open geometry for the 42 new communes was found.
"""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.io import netcdf_file
from shapely import contains_xy
from shapely.geometry import shape

from imbuto.lakehouse.sources import BRONZE
from imbuto.settings import DATA

SILVER = DATA / "silver"
GOLD = DATA / "gold"

# Rumonge and Muramvya were split across provinces; each goes to its main successor for now.
NEW_PROVINCE = {
    "Cankuzo": "Buhumuza", "Muyinga": "Buhumuza", "Ruyigi": "Buhumuza",
    "Bubanza": "Bujumbura", "Bujumbura Mairie": "Bujumbura", "Bujumbura Rural": "Bujumbura",
    "Cibitoke": "Bujumbura",
    "Bururi": "Burunga", "Makamba": "Burunga", "Rutana": "Burunga", "Rumonge": "Burunga",
    "Kayanza": "Butanyerera", "Kirundo": "Butanyerera", "Ngozi": "Butanyerera",
    "Gitega": "Gitega", "Karuzi": "Gitega", "Mwaro": "Gitega", "Muramvya": "Gitega",
}  # fmt: skip

# Burundi's two main rain-fed seasons. Season A starts in September and runs into the new year,
# so it is labelled by the year it starts in. The outlook is issued after the first month, while
# planting decisions are still open; the target is the rain that falls afterwards.
SEASONS = {
    "A": {"months": [9, 10, 11, 12, 1], "issue_after": 9, "target": [10, 11, 12, 1]},
    "B": {"months": [2, 3, 4, 5], "issue_after": 2, "target": [3, 4, 5]},
}


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def build_communes(bronze: Path = BRONZE) -> pd.DataFrame:
    """Assign each commune to its legacy province by centroid, then to a current province."""
    adm1 = json.loads((bronze / "adm1.geojson").read_text())["features"]
    adm2 = json.loads((bronze / "adm2.geojson").read_text())["features"]
    provinces = [(f["properties"]["shapeName"], shape(f["geometry"]).buffer(0)) for f in adm1]
    rows = []
    for feature in adm2:
        geometry = shape(feature["geometry"]).buffer(0)
        point = geometry.representative_point()
        legacy = next((n for n, g in provinces if g.contains(point)), None)
        if legacy is None:  # coastline slivers: use the nearest province
            legacy = min(provinces, key=lambda item: item[1].distance(point))[0]
        rows.append({
            "commune": feature["properties"]["shapeName"],
            "legacy_province": legacy,
            "province": NEW_PROVINCE[legacy],
            "lat": round(point.y, 4),
            "lon": round(point.x, 4),
            "area_km2": round(geometry.area * 111.32**2, 1),
            "geojson": json.dumps(feature["geometry"]),
        })  # fmt: skip
    communes = pd.DataFrame(rows).sort_values(["province", "commune"]).reset_index(drop=True)
    communes["commune_id"] = [f"BI{i:03d}" for i in range(1, len(communes) + 1)]
    return communes


def build_rainfall(communes: pd.DataFrame, bronze: Path = BRONZE) -> pd.DataFrame:
    """Average the CHIRPS grid cells inside each commune for every month."""
    with netcdf_file(bronze / "chirps_monthly.nc", mmap=False) as nc:
        x = nc.variables["X"][:].astype(float)
        y = nc.variables["Y"][:].astype(float)
        grid = nc.variables["precipitation"][:].astype(float)
        months_since_1960 = nc.variables["T"][:].astype(float)
    grid[grid < -1000] = np.nan
    lon, lat = np.meshgrid(x, y)

    frames = []
    dates = pd.to_datetime(
        [f"{1960 + int(m) // 12}-{int(m) % 12 + 1:02d}-01" for m in months_since_1960]
    )
    for row in communes.itertuples():
        geometry = shape(json.loads(row.geojson)).buffer(0)
        mask = contains_xy(geometry, lon, lat)
        if not mask.any():  # small communes can miss every cell centre
            mask = np.zeros_like(lon, bool)
            mask[np.abs(y - row.lat).argmin(), np.abs(x - row.lon).argmin()] = True
        frames.append(pd.DataFrame({
            "commune_id": row.commune_id, "month": dates,
            "rain_mm": np.nanmean(grid[:, mask], axis=1), "cells": int(mask.sum()),
        }))  # fmt: skip
    rain = pd.concat(frames, ignore_index=True)
    rain["rain_mm"] = rain["rain_mm"].round(2)
    return rain.dropna(subset=["rain_mm"])


def parse_oni(path: Path) -> pd.DataFrame:
    """ONI is a 3-month mean; assign it to its final month, when it is first knowable."""
    table = pd.read_csv(path, sep=r"\s+")
    end_month = {s: i + 1 for i, s in enumerate(
        "DJF JFM FMA MAM AMJ MJJ JJA JAS ASO SON OND NDJ".split())}  # fmt: skip
    table["month"] = pd.to_datetime(
        {"year": table["YR"] + (table["SEAS"] == "NDJ"),
         "month": table["SEAS"].map(lambda s: 1 if s == "NDJ" else end_month[s] + 1), "day": 1}
    )  # fmt: skip
    return table.rename(columns={"ANOM": "oni"})[["month", "oni"]]


def parse_dmi(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) != 13 or not parts[0].isdigit():
            continue
        year = int(parts[0])
        for month, value in enumerate(parts[1:], 1):
            if float(value) > -999:
                rows.append({"month": pd.Timestamp(year, month, 1), "dmi": float(value)})
    return pd.DataFrame(rows)


def build_prices(bronze: Path = BRONZE) -> pd.DataFrame:
    """Keep actual retail prices in Burundian francs for staples farmers trade."""
    con = duckdb.connect()
    return con.execute(
        """
        select cast(date as date) as month, admin1 as legacy_province, market, commodity,
               unit, try_cast(price as double) as price_bif
        from read_csv(?, all_varchar = true)
        where pricetype = 'Retail' and currency = 'BIF'
          and try_cast(price as double) > 0
        """,
        [str(bronze / "wfp_food_prices_bdi.csv")],
    ).df()


def season_features(rain: pd.DataFrame, climate: pd.DataFrame) -> pd.DataFrame:
    """One row per commune and season, using only what is known on the issue date.

    Standardised anomalies compare each commune with its own history, so a dry year in the wet
    highlands and a dry year in the Imbo plain become comparable. Those anomalies are computed
    in `imbuto.ml.risk`, from training years only, so a backtest cannot see its own future.
    """
    r = rain.assign(idx=rain["month"].dt.year * 12 + rain["month"].dt.month - 1)
    pivot = r.pivot_table(index="commune_id", columns="idx", values="rain_mm")
    climate = climate.assign(
        idx=climate["month"].dt.year * 12 + climate["month"].dt.month - 1
    ).set_index("idx")
    rows = []
    for season, spec in SEASONS.items():
        for year in range(1981, int(rain["month"].dt.year.max()) + 1):
            issue = _month_index(year, spec["issue_after"])
            start = _month_index(year, spec["months"][0])
            target_idx = [start + (m - spec["months"][0]) % 12 for m in spec["target"]]
            observed = [i for i in range(start, issue + 1)]
            if issue not in pivot.columns or start - 3 not in pivot.columns:
                continue  # season not yet at its issue date, or history too short
            so_far = pivot[observed].sum(axis=1)
            prior = pivot[[start - 3, start - 2, start - 1]].sum(axis=1)
            last = pivot[issue]
            complete = all(i in pivot.columns for i in target_idx)
            target = pivot[target_idx].sum(axis=1) if complete else np.nan
            frame = pd.DataFrame({
                "season": season, "year": year, "rain_so_far": so_far, "rain_prior_3m": prior,
                "rain_last_month": last, "target_rain": target,
                # Use the previous month: the latest index is not yet published on the issue date.
                "oni": climate["oni"].reindex([issue - 1]).iloc[0],
                "dmi": climate["dmi"].reindex([issue - 1]).iloc[0],
            })  # fmt: skip
            rows.append(frame.reset_index())
    table = pd.concat(rows, ignore_index=True)
    return table.sort_values(["season", "year", "commune_id"]).reset_index(drop=True)


def run(bronze: Path = BRONZE) -> dict[str, int]:
    SILVER.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)
    communes = build_communes(bronze)
    rain = build_rainfall(communes, bronze)
    prices = build_prices(bronze)
    climate = parse_oni(bronze / "oni.txt").merge(parse_dmi(bronze / "dmi.txt"), "outer", "month")
    climate = climate.sort_values("month").ffill(limit=6)
    features = season_features(rain, climate)

    communes.to_parquet(SILVER / "communes.parquet", index=False)
    rain.to_parquet(SILVER / "rain_monthly.parquet", index=False)
    prices.to_parquet(SILVER / "prices.parquet", index=False)
    climate.to_parquet(SILVER / "climate.parquet", index=False)
    features.merge(communes[["commune_id", "commune", "province"]]).to_parquet(
        GOLD / "season_features.parquet", index=False
    )
    return {"communes": len(communes), "rain": len(rain), "prices": len(prices),
            "features": len(features)}  # fmt: skip


if __name__ == "__main__":
    print(run())
