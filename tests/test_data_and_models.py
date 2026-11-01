import json
import shutil

import pandas as pd
import pytest

from imbuto.lakehouse.build import NEW_PROVINCE, parse_dmi, parse_oni, season_features
from imbuto.ml import risk
from imbuto.ml.bundle import BundleError, load_bundle, write_bundle
from imbuto.ml.crop_health import CropHealthModel
from imbuto.settings import ARTIFACTS


def _rain(years=range(2000, 2004)):
    rows = []
    for year in years:
        for month in range(1, 13):
            rows.append({"commune_id": "BI001", "month": pd.Timestamp(year, month, 1),
                         "rain_mm": float(month)})  # fmt: skip
    return pd.DataFrame(rows)


def _climate():
    months = pd.date_range("1999-01-01", "2004-12-01", freq="MS")
    return pd.DataFrame({"month": months, "oni": range(len(months)), "dmi": 0.5})


def test_every_legacy_province_maps_to_one_of_five_current_provinces():
    assert len(NEW_PROVINCE) == 18
    assert len(set(NEW_PROVINCE.values())) == 5


def test_season_a_spans_the_new_year():
    table = season_features(_rain(), _climate())
    row = table[(table["season"] == "A") & (table["year"] == 2001)].iloc[0]
    assert row["rain_so_far"] == 9  # September only
    assert row["target_rain"] == 10 + 11 + 12 + 1  # October to the next January


def test_climate_index_is_from_before_the_issue_date():
    climate = _climate()
    table = season_features(_rain(), climate)
    row = table[(table["season"] == "A") & (table["year"] == 2001)].iloc[0]
    august = climate.set_index("month").loc["2001-08-01", "oni"]
    assert row["oni"] == august


def test_unfinished_season_keeps_its_row_without_a_target():
    rain = _rain()
    table = season_features(rain[rain["month"] <= "2003-09-01"], _climate())
    row = table[(table["season"] == "A") & (table["year"] == 2003)]
    assert len(row) == 1 and row["target_rain"].isna().all()


def test_oni_is_dated_to_the_end_of_its_three_months(tmp_path):
    path = tmp_path / "oni.txt"
    path.write_text("SEAS YR TOTAL ANOM\nDJF 2020 27 0.5\nNDJ 2020 26 -1.0\n")
    table = parse_oni(path)
    assert table["month"].tolist() == [pd.Timestamp(2020, 2, 1), pd.Timestamp(2021, 1, 1)]


def test_dmi_skips_missing_values(tmp_path):
    path = tmp_path / "dmi.txt"
    months = " ".join(["0.1"] * 2 + ["-9999.000"] * 10)
    path.write_text(f"2020 2026\n2020 {months}\nfooter\n")
    assert len(parse_dmi(path)) == 2


def test_backtest_thresholds_ignore_the_future():
    rows = []
    for year in range(2000, 2011):
        rows.append({"commune_id": "BI001", "season": "A", "year": year, "rain_so_far": 1.0,
                     "rain_prior_3m": 1.0, "rain_last_month": 1.0,
                     "target_rain": 100.0})  # fmt: skip
    history = pd.DataFrame(rows[:-1])
    future = pd.DataFrame(rows[-1:]).assign(target_rain=0.0)
    assert risk.prepare(future, history)["threshold"].iloc[0] == 100.0
    assert risk.prepare(future, history)["shortfall"].iloc[0] == 1


def test_gate_refuses_a_score_that_could_be_luck():
    report = {"m": {"brier_skill": 0.05, "brier_skill_ci90": [-0.01, 0.1]}}
    assert not risk.promotion_gate(report)["passed"]
    report["m"]["brier_skill_ci90"] = [0.01, 0.1]
    assert risk.promotion_gate(report)["passed"]


def test_bundle_rejects_tampering(tmp_path):
    (tmp_path / "weights.bin").write_bytes(b"good")
    write_bundle(tmp_path, "demo", "1.0.0", {})
    assert load_bundle(tmp_path)["name"] == "demo"
    (tmp_path / "weights.bin").write_bytes(b"evil")
    with pytest.raises(BundleError):
        load_bundle(tmp_path)


def test_shipped_bundles_verify():
    assert load_bundle(ARTIFACTS / "crop_health")["card"]["metrics"]["test_accuracy"] > 0.85
    assert load_bundle(ARTIFACTS / "rain")["card"]["farmer_facing_forecast"] is False


def test_rain_status_covers_every_commune():
    status = json.loads((ARTIFACTS / "rain" / "rain_status.json").read_text())
    assert len(status["communes"]) == 119


def test_model_loads_and_rejects_a_blank_image(tmp_path):
    import io

    from PIL import Image

    model = CropHealthModel(ARTIFACTS / "crop_health")
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), (20, 20, 200)).save(buffer, "JPEG")
    assert model.predict(buffer.getvalue()).outcome == "not_a_leaf"
    shutil.rmtree(tmp_path)
