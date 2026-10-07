"""
test_treatment_subset.py
========================
Subsetting a statewide treatment dataset down to one basin:

  * treatment_subset.subset_treatment keeps overlapping polygons whole, drops
    far-away and edge-touching ones, and records each row's source FID;
  * prep_custom_basin.py --treatment-src writes source/<key>_treatment.shp,
    points config.toml at it, and the fill runs on the subset;
  * the fill warns when handed a statewide file directly;
  * prep_basin.py --treatment-src works against the real NWI basin outline.
"""

from __future__ import annotations

import csv
import os
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
pytest.importorskip("rasterio")
pytest.importorskip("scipy")
import pandas as pd  # noqa: E402
from shapely.geometry import box  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT))
import synth_data  # noqa: E402
import treatment_subset  # noqa: E402


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


def _make_statewide(data: dict, dest: Path) -> Path:
    """The synthetic basin's 3 treatment polygons plus: 10 far-away polygons,
    one that straddles the basin line, and one that only shares its edge."""
    X0, Y0, RES, W = synth_data.X0, synth_data.Y0, synth_data.RES, synth_data.W
    bx1 = X0 + (W - 3) * RES                     # east edge of the boundary
    t = gpd.read_file(data["treatment"]).drop(columns=["adj_fctr"])
    extra = []
    for k in range(10):
        x = X0 + 60_000 + k * 1_000
        extra.append({"ET_unit": "Far", "scale_fctr": 0.0, "rplc_rt": 0.7,
                      "DRI_ID": f"F{k}", "geometry": box(x, Y0 - 900, x + 300, Y0 - 600)})
    extra.append({"ET_unit": "Straddle", "scale_fctr": 0.0, "rplc_rt": 0.0,
                  "DRI_ID": "S1",
                  "geometry": box(bx1 - 300, Y0 - 1500, bx1 + 600, Y0 - 1200)})
    extra.append({"ET_unit": "Touch", "scale_fctr": 0.0, "rplc_rt": 0.0,
                  "DRI_ID": "E1",
                  "geometry": box(bx1, Y0 - 2400, bx1 + 600, Y0 - 2100)})
    # Far polygons first so the basin's own rows are not at FID 0..2.
    sw = gpd.GeoDataFrame(
        pd.concat(
            [gpd.GeoDataFrame(extra, crs=t.crs), t], ignore_index=True),
        crs=t.crs)
    path = dest / "statewide_etunits.shp"
    sw.to_file(path)
    return path


def test_subset_selection(tmp_path):
    data = synth_data.generate(tmp_path / "synth")
    sw_path = _make_statewide(data, tmp_path)
    sw = gpd.read_file(sw_path)
    bnd = gpd.read_file(data["boundary"])

    out = treatment_subset.subset_treatment(
        sw_path, bnd.geometry.iloc[0], bnd.crs, tmp_path / "Sub_treatment.shp")
    sub = gpd.read_file(out)

    assert sorted(sub["DRI_ID"]) == ["S1", "T1", "T2", "U1"]
    # src_fid points back at the same row in the statewide file.
    for _, r in sub.iterrows():
        assert sw.loc[int(r["src_fid"]), "DRI_ID"] == r["DRI_ID"]
    # The straddling polygon is kept whole, not clipped at the basin line.
    s_sub = sub.loc[sub["DRI_ID"] == "S1"].geometry.iloc[0]
    s_src = sw.loc[sw["DRI_ID"] == "S1"].geometry.iloc[0]
    assert abs(s_sub.area - s_src.area) < 1e-6


def test_subset_no_overlap_raises(tmp_path):
    data = synth_data.generate(tmp_path / "synth")
    sw_path = _make_statewide(data, tmp_path)
    sw = gpd.read_file(sw_path)
    far_only = sw[sw["ET_unit"] == "Far"]
    far_path = tmp_path / "far_only.shp"
    far_only.to_file(far_path)
    bnd = gpd.read_file(data["boundary"])
    with pytest.raises(treatment_subset.SubsetError):
        treatment_subset.subset_treatment(
            far_path, bnd.geometry.iloc[0], bnd.crs, tmp_path / "x.shp")


def test_prep_custom_basin_treatment_src(tmp_path):
    work = _workdir(tmp_path)
    data = synth_data.generate(work / "_synth")
    sw_path = _make_statewide(data, work / "_synth")
    key = "SubsetBasin"
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / f"{key}_ETg.tif")

    _run("prep_custom_basin.py", key, "--boundary", str(data["boundary"]),
         "--treatment-src", str(sw_path), "--bps", str(data["bps"]), cwd=work)

    subset = source / f"{key}_treatment.shp"
    assert subset.exists()
    cfg_txt = (work / "basins" / key / "config.toml").read_text()
    assert f'treatment_shp = "{subset.name}"' in cfg_txt

    fill = _run("etg_baseline_fill.py", key, cwd=work)
    assert "looks like a statewide file" not in fill.stdout

    out = work / "basins" / key / "output"
    with open(out / f"{key}_polygon_summary.csv", newline="") as f:
        ids = sorted(r["polygon_id"] for r in csv.DictReader(f))
    assert ids == ["S1", "T1", "T2", "U1"]
    # Review file lands in this basin's source/, not next to the statewide file.
    assert (source / f"{key}_rates_adjust.shp").exists()
    assert not (sw_path.parent / f"{key}_rates_adjust.shp").exists()

    # Re-running prep with an up-to-date subset leaves it alone.
    again = _run("prep_custom_basin.py", key, "--boundary", str(data["boundary"]),
                 "--treatment-src", str(sw_path), "--bps", str(data["bps"]),
                 cwd=work)
    assert "already present and newer" in again.stdout


def test_treatment_src_requires_boundary(tmp_path):
    work = _workdir(tmp_path)
    data = synth_data.generate(work / "_synth")
    sw_path = _make_statewide(data, work / "_synth")
    proc = _run("prep_custom_basin.py", "NoBnd", "--treatment",
                str(data["treatment"]), "--treatment-src", str(sw_path),
                "--bps", str(data["bps"]), cwd=work, check=False)
    assert proc.returncode != 0
    assert "--treatment-src needs --boundary" in proc.stderr


def test_fill_warns_on_statewide_input(tmp_path):
    work = _workdir(tmp_path)
    data = synth_data.generate(work / "_synth")
    sw_path = _make_statewide(data, work / "_synth")
    key = "Direct"
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / f"{key}_ETg.tif")
    sw = gpd.read_file(sw_path)
    sw.to_file(source / "treatment.shp")

    _run("prep_custom_basin.py", key, "--boundary", str(data["boundary"]),
         "--bps", str(data["bps"]), cwd=work)
    fill = _run("etg_baseline_fill.py", key, cwd=work)
    assert "looks like a statewide file" in fill.stdout


def test_prep_basin_treatment_src_nwi(tmp_path):
    """prep_basin.py --treatment-src cuts by the NWI basin outline.  Uses the
    Pine Valley master shipped in the repo as the 'statewide' source."""
    src_dir = PROJECT_ROOT / "basins" / "053_PineValley" / "source"
    masters = sorted(src_dir.glob("*_w_ag.shp"))
    if not masters:
        pytest.skip("Pine Valley sample shapefile not present")
    work = _workdir(tmp_path)
    proc = _run("prep_basin.py", "053_PineValley", "--treatment-src",
                str(masters[0]), cwd=work)
    subset = work / "basins" / "053_PineValley" / "source" / \
        "053_PineValley_treatment.shp"
    assert subset.exists(), proc.stdout
    n_src = len(gpd.read_file(masters[0]))
    n_sub = len(gpd.read_file(subset))
    assert 0 < n_sub <= n_src
    cfg_txt = (work / "basins" / "053_PineValley" / "config.toml").read_text()
    assert 'treatment_shp = "053_PineValley_treatment.shp"' in cfg_txt
