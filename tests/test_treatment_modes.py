"""
test_treatment_modes.py
=======================
The three treatment modes added in 1.1.0:

  * baseline   - any column in [treatment] attr_treat > 0 (the original
                 scale_fctr / rplc_rt behaviour);
  * basin_avg  - bsnAv_flag > 0: every pixel gets the mean of the training
                 pixels, then the usual adjustment / cap / feather;
  * fixed      - fixed_rt > 0: the value is burned in as-is, no cap, no
                 buffer, no feather band around it.

Also: fixed_rt round-trips through {key}_rates_adjust.shp like adj_fctr, and
an old config with only attr_scale / attr_replace still works.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = [
    "basin_config.py", "bps_utils.py", "etg_baseline_fill.py",
    "diagnostics.py", "etunit_summary.py", "prep_custom_basin.py",
    "prep_basin.py", "run_all.py", "flag_irrigated.py", "treatment_subset.py",
]
NWI_STEM = "NWI_Investigations_EPSG_32611"
SHP_EXTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("scipy")
import numpy as np  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
import synth_data  # noqa: E402


def _run(script, *args, cwd, check=True):
    proc = subprocess.run([sys.executable, script, *args], cwd=cwd,
                          capture_output=True, text=True, encoding="cp1252",
                          env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    if check and proc.returncode != 0:
        raise AssertionError(
            f"{script} {' '.join(args)} exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc


def _workdir(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    for f in CODE_FILES:
        shutil.copy2(PROJECT_ROOT / f, work / f)
    for ext in SHP_EXTS:
        src = PROJECT_ROOT / f"{NWI_STEM}{ext}"
        if src.exists():
            shutil.copy2(src, work / src.name)
    (work / "basins" / "_template").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "basins" / "_template" / "config.toml",
                 work / "basins" / "_template" / "config.toml")
    return work


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        nd = src.nodata
    if nd is not None:
        a[a == np.float32(nd)] = np.nan
    return a


def _summary(work: Path, key: str) -> dict:
    path = work / "basins" / key / "output" / f"{key}_polygon_summary.csv"
    with open(path, newline="") as f:
        return {r["polygon_id"]: r for r in csv.DictReader(f)}


def _prep_and_fill(tmp_path, key="Modes", edit_treatment=None):
    work = _workdir(tmp_path)
    data = synth_data.generate(work / "_synth", modes=True)
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / f"{key}_ETg.tif")
    g = gpd.read_file(data["treatment"])
    if edit_treatment is not None:
        g = edit_treatment(g)
    g.to_file(source / "treatment.shp")
    _run("prep_custom_basin.py", key, "--boundary", str(data["boundary"]),
         "--bps", str(data["bps"]), cwd=work)
    fill = _run("etg_baseline_fill.py", key, cwd=work)
    return work, data, fill


@pytest.fixture(scope="module")
def modes(tmp_path_factory):
    work, data, fill = _prep_and_fill(tmp_path_factory.mktemp("modes"))
    out = work / "basins" / "Modes" / "output"
    return {"work": work, "data": data, "out": out, "log": fill.stdout,
            "summary": _summary(work, "Modes")}


def test_modes_reported(modes):
    s = modes["summary"]
    assert s["T1"]["treatment"] == "baseline" and s["T1"]["trigger"] == "rplc_rt"
    assert s["T2"]["treatment"] == "baseline" and s["T2"]["trigger"] == "scale_fctr"
    assert s["U1"]["treatment"] == "none"
    assert s["B1"]["treatment"] == "basin_avg" and s["B1"]["trigger"] == "bsnAv_flag"
    assert s["W1"]["treatment"] == "fixed" and s["W1"]["trigger"] == "fixed_rt"
    assert float(s["W1"]["fixed_rate"]) == synth_data.WATER_FIXED
    assert "polygons_basin_avg    = 1" in (modes["out"] / "Modes_run_metadata.txt").read_text()


def test_basin_avg_polygon_is_filled(modes):
    """B1 has zeros in scale_fctr / rplc_rt, so before 1.1.0 it passed through
    untouched.  Now it is pulled down to the training mean."""
    s = modes["summary"]
    b0, b1 = modes["data"]["bavg_block"]
    final = _read(modes["out"] / "Modes_ETg_final.tif")
    inp = _read(modes["data"]["etg"])
    blk_final = final[b0:b1, b0:b1]
    blk_in = inp[b0:b1, b0:b1]
    assert np.nanmean(blk_final) < np.nanmean(blk_in) - 1.0, \
        "basin-average polygon was not filled"
    # Every pixel of the polygon holds one value: the training mean.
    assert np.nanstd(blk_final) < 1e-4
    meta = (modes["out"] / "Modes_run_metadata.txt").read_text()
    y_mean = float([ln for ln in meta.splitlines() if ln.startswith("y_mean")][0]
                   .split("=")[1].split("#")[0])
    assert abs(float(s["B1"]["mean_final_ETg"]) - y_mean) < 1e-3
    assert float(s["B1"]["mean_baseline_ETg"]) == pytest.approx(y_mean, abs=1e-3)


def test_fixed_rate_burned_in(modes):
    """W1: input 3.0, BpS baseline well under 1, fixed_rt 4.0.  The output
    must hold exactly 4.0 (so the downward-only cap was bypassed)."""
    w0, w1 = modes["data"]["water_block"]
    final = _read(modes["out"] / "Modes_ETg_final.tif")
    blk = final[w0:w1, w0:w1]
    assert np.all(np.isfinite(blk))
    assert np.allclose(blk, synth_data.WATER_FIXED, atol=1e-5)
    s = modes["summary"]
    assert float(s["W1"]["mean_final_ETg"]) == pytest.approx(synth_data.WATER_FIXED, abs=1e-3)
    # The summary still reports what the model would have said, for review.
    assert float(s["W1"]["mean_baseline_ETg"]) < 2.0
    assert "Fixed-rate burn-in: 100 pixels" in modes["log"]


def test_fixed_rate_has_hard_edge(modes):
    """No buffer and no feather around a fixed-rate polygon: the pixels just
    outside W1 keep their input value, and the treatment zone is exactly the
    polygon."""
    w0, w1 = modes["data"]["water_block"]
    final = _read(modes["out"] / "Modes_ETg_final.tif")
    inp = _read(modes["data"]["etg"])
    tz = _read(modes["out"] / "treatment_zone.tif")
    # One-pixel ring just outside the block.
    ring = np.zeros_like(tz, dtype=bool)
    ring[w0 - 1:w1 + 1, w0 - 1:w1 + 1] = True
    ring[w0:w1, w0:w1] = False
    assert np.all(tz[ring] == 0), "fixed polygon was buffered"
    assert np.allclose(final[ring], inp[ring], atol=1e-5), \
        "pixels outside the fixed polygon were feathered"
    # Contrast: the baseline polygon T1 IS buffered (90 m = 3 px).
    i0, i1 = modes["data"]["irr_block"]
    assert tz[i0 - 2, i0 + 5] == 1


def test_fixed_rate_roundtrips_via_rates_file(tmp_path):
    """Type a fixed_rt into {key}_rates_adjust.shp, re-run, and the polygon is
    burned in; the regenerated file keeps the value."""
    key = "FixedRT"

    def _strip(g):
        return g.drop(columns=["fixed_rt", "adj_fctr"], errors="ignore")

    work, data, _ = _prep_and_fill(tmp_path, key=key, edit_treatment=_strip)
    source = work / "basins" / key / "source"
    rates = source / f"{key}_rates_adjust.shp"
    g = gpd.read_file(rates)
    assert "fixed_rt" in g.columns and (g["fixed_rt"] == 0).all()
    before = _summary(work, key)
    assert before["W1"]["treatment"] == "none"       # no fixed_rt column now

    g.loc[g["poly_id"] == "W1", "fixed_rt"] = 2.5
    g.to_file(rates)
    _run("etg_baseline_fill.py", key, cwd=work)
    after = _summary(work, key)
    assert after["W1"]["treatment"] == "fixed"
    assert float(after["W1"]["mean_final_ETg"]) == pytest.approx(2.5, abs=1e-3)
    g2 = gpd.read_file(rates)
    assert float(g2.loc[g2["poly_id"] == "W1", "fixed_rt"].iloc[0]) == 2.5
    # Shapefile column wins over the rates file.
    g3 = gpd.read_file(source / "treatment.shp")
    g3["fixed_rt"] = 0.0
    g3.loc[g3["DRI_ID"] == "W1", "fixed_rt"] = 1.0
    g3.to_file(source / "treatment.shp")
    fill = _run("etg_baseline_fill.py", key, cwd=work)
    assert "takes precedence" in fill.stdout
    assert float(_summary(work, key)["W1"]["mean_final_ETg"]) == pytest.approx(1.0, abs=1e-3)


def _set_treatment_section(cfg: Path, body: str) -> None:
    """Replace everything in [treatment] with *body* (other sections kept)."""
    txt = cfg.read_text()
    m = re.search(r"\[treatment\]\n(.*?)(?=\n\[)", txt, re.S)
    assert m, "no [treatment] section"
    cfg.write_text(txt[:m.start(1)] + body.strip() + "\n" + txt[m.end(1):])


def test_attr_treat_list_and_legacy_keys(tmp_path):
    """attr_treat replaces attr_scale / attr_replace; a config with only the
    old keys still works, and a custom list is honoured."""
    key = "ListCfg"
    work, data, fill = _prep_and_fill(tmp_path, key=key)
    cfg = work / "basins" / key / "config.toml"
    assert "attr_treat" in cfg.read_text()

    # Legacy config: only the two pre-1.1.0 keys.  bsnAv_flag / fixed_rt
    # keep their defaults, so B1 and W1 are still picked up.
    _set_treatment_section(cfg, """
buffer_m = 90.0
feather_width_px = 4
attr_scale = "scale_fctr"
attr_replace = "rplc_rt"
""")
    _run("etg_baseline_fill.py", key, cwd=work)
    s = _summary(work, key)
    assert s["T1"]["treatment"] == "baseline"
    assert s["T2"]["treatment"] == "baseline"
    assert s["B1"]["treatment"] == "basin_avg"
    assert s["W1"]["treatment"] == "fixed"

    # Custom list: only rplc_rt triggers, and the basin average is switched off.
    _set_treatment_section(cfg, """
buffer_m = 90.0
feather_width_px = 4
attr_treat = ["rplc_rt"]
attr_basin_avg = ""
""")
    _run("etg_baseline_fill.py", key, cwd=work)
    s = _summary(work, key)
    assert s["T1"]["treatment"] == "baseline"
    assert s["T2"]["treatment"] == "none"     # scale_fctr no longer a trigger
    assert s["B1"]["treatment"] == "none"     # basin average switched off
    assert s["W1"]["treatment"] == "fixed"


def test_flag_irrigated_respects_new_columns(tmp_path):
    """flag_irrigated.py treats bsnAv_flag / fixed_rt polygons as already
    manually flagged, so it never proposes them as auto-detections."""
    key = "FlagModes"
    work, data, _ = _prep_and_fill(tmp_path, key=key)
    _run("flag_irrigated.py", key, "--reset", cwd=work)
    rep_path = work / "basins" / key / "output" / f"{key}_autoflag_report.csv"
    with open(rep_path, newline="") as f:
        rep = {r["polygon_id"]: r for r in csv.DictReader(f)}
    assert rep["B1"]["source"] == "manual_flag"
    assert rep["W1"]["source"] == "manual_flag"
