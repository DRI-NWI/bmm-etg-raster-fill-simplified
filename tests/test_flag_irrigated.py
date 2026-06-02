"""
test_flag_irrigated.py
=====================
Tests for the auto-flagging helper (flag_irrigated.py).

Sets up an isolated project copy with synthetic data (an inflated "irrigated"
block plus two natural polygons), clears any manual flags, and checks that:

  * the irrigation-inflated polygon is auto-flagged (autoflag == 1);
  * natural polygons are not flagged (autoflag == 0);
  * an analyst override (editing autoflag in the output) survives a re-run
    while the raw machine suggestion (autoflag_a) is preserved separately.

Run with:   pytest -q
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = [
    "basin_config.py", "bps_utils.py", "etg_baseline_fill.py",
    "diagnostics.py", "etunit_summary.py", "prep_custom_basin.py",
    "prep_basin.py", "run_all.py", "flag_irrigated.py",
]
NWI_STEM = "NWI_Investigations_EPSG_32611"

gpd = pytest.importorskip("geopandas")
pytest.importorskip("rasterio")
pytest.importorskip("scipy")

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
import synth_data  # noqa: E402

KEY = "SmokeTest"


def _run(script, *args, cwd):
    proc = subprocess.run([sys.executable, script, *args],
                          cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"{script} {' '.join(args)} exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc


def _read_report(out_dir: Path) -> dict:
    """Return {polygon_id: row dict} from the autoflag report CSV."""
    path = out_dir / f"{KEY}_autoflag_report.csv"
    with open(path, newline="") as f:
        return {r["polygon_id"]: r for r in csv.DictReader(f)}


@pytest.fixture(scope="module")
def flagged(tmp_path_factory):
    work = tmp_path_factory.mktemp("flagrepo")
    for f in CODE_FILES:
        shutil.copy2(PROJECT_ROOT / f, work / f)
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        src = PROJECT_ROOT / f"{NWI_STEM}{ext}"
        if src.exists():
            shutil.copy2(src, work / src.name)
    (work / "basins" / "_template").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "basins" / "_template" / "config.toml",
                 work / "basins" / "_template" / "config.toml")

    data = synth_data.generate(work / "_synth")
    source = work / "basins" / KEY / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / "SmokeTest_ETg.tif")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        p = data["treatment"].with_suffix(ext)
        if p.exists():
            shutil.copy2(p, source / f"treatment{ext}")

    _run("prep_custom_basin.py", KEY,
         "--boundary", str(data["boundary"]), "--bps", str(data["bps"]), cwd=work)

    # Clear the analyst's manual flags so the flagger must auto-detect.
    tshp = source / "treatment.shp"
    g = gpd.read_file(tshp)
    g["scale_fctr"] = 0.0
    g["rplc_rt"] = 0.0
    g.to_file(tshp)

    _run("flag_irrigated.py", KEY, "--reset", cwd=work)

    out_dir = work / "basins" / KEY / "output"
    return {"work": work, "source": source, "out": out_dir}


def test_irrigated_polygon_flagged(flagged):
    rep = _read_report(flagged["out"])
    t1 = rep["T1"]                      # the inflated "irrigated" block
    assert int(t1["autoflag_a"]) == 1
    assert int(t1["autoflag"]) == 1
    assert float(t1["etg_ratio"]) >= 1.5
    assert float(t1["etg_excs"]) >= 0.3
    assert t1["source"] == "auto"


def test_natural_polygons_not_flagged(flagged):
    rep = _read_report(flagged["out"])
    for pid in ("T2", "U1"):           # natural / un-inflated polygons
        assert int(rep[pid]["autoflag"]) == 0, f"{pid} should not be flagged"


def test_class_summary_written(flagged):
    """A per-BpS-class diagnostic CSV is produced with a flagged-area share."""
    path = flagged["out"] / f"{KEY}_autoflag_class_summary.csv"
    assert path.exists(), "class summary CSV not written"
    with open(path, newline="") as f:
        rows = {int(r["bps_code"]): r for r in csv.DictReader(f)}
    assert rows, "class summary is empty"
    # Expected columns present, and shares are valid percentages.
    for r in rows.values():
        assert 0.0 <= float(r["pct_area_flagged"]) <= 100.0
        assert int(r["n_polys_dom_flagged"]) <= int(r["n_polys_dom"])
    # The irrigated block's dominant class should show some flagged area.
    rep = _read_report(flagged["out"])
    dom = int(rep["T1"]["bps_dom"])
    assert float(rows[dom]["pct_area_flagged"]) > 0.0


def test_analyst_override_is_sticky(flagged):
    """Editing autoflag in the output must survive a re-run (no --reset),
    while the raw machine suggestion (autoflag_a) is preserved."""
    work = flagged["work"]
    out_shp = flagged["source"] / "treatment_autoflag.shp"

    g = gpd.read_file(out_shp)
    g.loc[g["DRI_ID"] == "T1", "autoflag"] = 0   # analyst: T1 is fine as-is
    g.to_file(out_shp)

    _run("flag_irrigated.py", KEY, cwd=work)     # no --reset: honor overrides

    rep = _read_report(flagged["out"])
    assert int(rep["T1"]["autoflag"]) == 0, "override was not preserved"
    assert int(rep["T1"]["autoflag_a"]) == 1, "machine suggestion should remain 1"
    assert rep["T1"]["source"] == "analyst_override"
