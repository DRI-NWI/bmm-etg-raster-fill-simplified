"""
test_flag_irrigated.py
=====================
Tests for the auto-flagging helper (flag_irrigated.py).

Sets up an isolated project copy with synthetic data (an inflated "irrigated"
block plus two natural polygons), clears any manual flags, and checks that:

  * the irrigation-inflated polygon is auto-flagged (autoflag == 1);
  * natural polygons are not flagged (autoflag == 0);
  * an analyst override (editing autoflag in the output) survives a re-run
    while the machine suggestion ('suggested') is preserved separately.

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
    "prep_basin.py", "run_all.py", "flag_irrigated.py", "treatment_subset.py",
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
    assert int(t1["suggested"]) == 1
    assert int(t1["analyst"]) == -1
    assert int(t1["autoflag"]) == 1
    assert float(t1["etg_ratio"]) >= 1.5
    assert float(t1["etg_excs"]) >= 0.3
    assert t1["source"] == "suggested"


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


def test_analyst_column_is_sticky(flagged):
    """A 0 or 1 typed into 'analyst' decides the result and survives a re-run;
    'suggested' is still the machine's call."""
    work = flagged["work"]
    out_shp = flagged["source"] / "treatment_autoflag.shp"

    g = gpd.read_file(out_shp)
    assert set(g["analyst"]) == {-1}, "analyst column should be seeded to -1"
    assert "autoflag_a" not in g.columns
    g.loc[g["DRI_ID"] == "T1", "analyst"] = 0   # analyst: T1 is fine as-is
    g.loc[g["DRI_ID"] == "U1", "analyst"] = 1   # analyst: U1 needs treating
    g.to_file(out_shp)

    _run("flag_irrigated.py", KEY, cwd=work)     # no --reset: keep the column

    rep = _read_report(flagged["out"])
    assert int(rep["T1"]["autoflag"]) == 0 and rep["T1"]["source"] == "analyst"
    assert int(rep["T1"]["suggested"]) == 1, "machine suggestion should remain 1"
    assert int(rep["U1"]["autoflag"]) == 1 and rep["U1"]["source"] == "analyst"
    g2 = gpd.read_file(out_shp)
    assert int(g2.loc[g2["DRI_ID"] == "T1", "analyst"].iloc[0]) == 0
    assert int(g2.loc[g2["DRI_ID"] == "U1", "analyst"].iloc[0]) == 1
    assert int(g2.loc[g2["DRI_ID"] == "T2", "analyst"].iloc[0]) == -1

    # --reset clears the analyst column and the result follows the suggestion.
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)
    rep = _read_report(flagged["out"])
    assert int(rep["T1"]["autoflag"]) == 1 and rep["T1"]["source"] == "suggested"
    assert int(rep["U1"]["autoflag"]) == 0
    assert set(gpd.read_file(out_shp)["analyst"]) == {-1}


def test_hand_edit_of_autoflag_is_rescued(flagged):
    """Editing 'autoflag' instead of 'analyst' is the old habit.  The script
    keeps the edit by moving it into 'analyst' and says so."""
    work = flagged["work"]
    out_shp = flagged["source"] / "treatment_autoflag.shp"
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)
    g = gpd.read_file(out_shp)
    g.loc[g["DRI_ID"] == "T1", "autoflag"] = 0
    g.to_file(out_shp)
    proc = _run("flag_irrigated.py", KEY, cwd=work)
    assert "edited by hand" in proc.stdout
    rep = _read_report(flagged["out"])
    assert int(rep["T1"]["autoflag"]) == 0 and int(rep["T1"]["analyst"]) == 0
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)   # leave fixture clean


def test_legacy_autoflag_a_file_is_migrated(flagged):
    """A pre-1.1.0 output (autoflag + autoflag_a) is read once: rows where the
    two differ become analyst values, and autoflag_a is dropped."""
    work = flagged["work"]
    out_shp = flagged["source"] / "treatment_autoflag.shp"
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)
    g = gpd.read_file(out_shp).drop(columns=["analyst", "suggested"])
    g["autoflag_a"] = g["autoflag"]
    g.loc[g["DRI_ID"] == "T1", "autoflag"] = 0        # an old-style override
    g.to_file(out_shp)
    proc = _run("flag_irrigated.py", KEY, cwd=work)
    assert "migrating pre-1.1.0" in proc.stdout
    g2 = gpd.read_file(out_shp)
    assert "autoflag_a" not in g2.columns
    assert int(g2.loc[g2["DRI_ID"] == "T1", "analyst"].iloc[0]) == 0
    assert int(g2.loc[g2["DRI_ID"] == "T1", "autoflag"].iloc[0]) == 0
    assert int(g2.loc[g2["DRI_ID"] == "T2", "analyst"].iloc[0]) == -1
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)


def test_manual_flag_not_mistaken_for_hand_edit(flagged):
    """A polygon flagged by hand in the source (scale_fctr > 0) is always
    autoflag = 1 even when suggested = 0.  A re-run must not read that gap as
    a hand edit of autoflag, so the analyst column stays -1."""
    work = flagged["work"]
    src = flagged["source"] / "treatment.shp"
    g = gpd.read_file(src)
    g.loc[g["DRI_ID"] == "U1", "scale_fctr"] = 0.5      # natural, flagged by hand
    g.to_file(src)
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)
    rep = _read_report(flagged["out"])
    assert int(rep["U1"]["suggested"]) == 0 and int(rep["U1"]["autoflag"]) == 1
    proc = _run("flag_irrigated.py", KEY, cwd=work)      # second run, no edits
    assert "edited by hand" not in proc.stdout
    rep = _read_report(flagged["out"])
    assert int(rep["U1"]["analyst"]) == -1 and rep["U1"]["source"] == "manual_flag"
    # Restore the fixture.
    g.loc[g["DRI_ID"] == "U1", "scale_fctr"] = 0.0
    g.to_file(src)
    _run("flag_irrigated.py", KEY, "--reset", cwd=work)
