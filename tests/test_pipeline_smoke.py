"""
test_pipeline_smoke.py
======================
End-to-end smoke test for the BpS-only ETg raster-fill pipeline.

It copies the project code into a temporary directory, generates a small
synthetic study area (no network / external data), runs the real command-line
scripts as subprocesses, and asserts that:

  * prep_custom_basin, etg_baseline_fill, and etunit_summary all succeed;
  * the expected output rasters / CSVs / metadata are written;
  * the modeled baseline removes the simulated irrigation signal in the
    treatment zone (final ETg < input ETg there) without exceeding it;
  * the project carries no machine-learning dependencies.

Run with:   pytest -q          (from the project root)

Requires the runtime stack (rasterio, geopandas, scipy, matplotlib).  If those
are not importable the geospatial tests skip rather than fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files the pipeline needs in its working directory.
CODE_FILES = [
    "basin_config.py", "bps_utils.py", "etg_baseline_fill.py",
    "diagnostics.py", "etunit_summary.py", "prep_custom_basin.py",
    "prep_basin.py", "prep_statewide.py", "prep_humboldt.py",
    "run_all.py", "flag_irrigated.py", "treatment_subset.py",
]
NWI_STEM = "NWI_Investigations_EPSG_32611"

# Skip the geospatial end-to-end test cleanly if the stack isn't installed.
gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("scipy")
import numpy as np  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
import synth_data  # noqa: E402


def _run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run a project script as a subprocess; fail loudly with captured output.

    stdout is forced to cp1252, the default on a US/Western-European Windows
    install when output is redirected or captured.  Any non-ASCII character in
    a printed string raises UnicodeEncodeError there, so running the scripts
    this way reproduces that failure on Linux and macOS too.  Do not relax
    this to UTF-8 to make a test pass; fix the offending string instead.
    """
    cmd = [sys.executable, script, *args]
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="cp1252", env=env)
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(cmd)} exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Set up an isolated project copy, run prep + fill + summary once."""
    work = tmp_path_factory.mktemp("repo")

    # Copy code + NWI shapefile + config template into the working dir.
    for f in CODE_FILES:
        shutil.copy2(PROJECT_ROOT / f, work / f)
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        src = PROJECT_ROOT / f"{NWI_STEM}{ext}"
        if src.exists():
            shutil.copy2(src, work / src.name)
    (work / "basins" / "_template").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "basins" / "_template" / "config.toml",
                 work / "basins" / "_template" / "config.toml")

    # Generate synthetic inputs.
    data = synth_data.generate(work / "_synth")

    key = "SmokeTest"
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    # ETg raster + treatment shapefile go into source/ before prep so the
    # generated config.toml detects them.
    shutil.copy2(data["etg"], source / "SmokeTest_ETg.tif")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        p = data["treatment"].with_suffix(ext)
        if p.exists():
            shutil.copy2(p, source / f"treatment{ext}")

    _run("prep_custom_basin.py", key,
         "--boundary", str(data["boundary"]),
         "--bps", str(data["bps"]), cwd=work)
    _run("etg_baseline_fill.py", key, cwd=work)
    _run("etunit_summary.py", key, cwd=work)

    out = work / "basins" / key / "output"
    return {"work": work, "key": key, "out": out,
            "etg": data["etg"], "irr": data["irr_block"]}


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        nd = src.nodata
    if nd is not None:
        a[a == np.float32(nd)] = np.nan
    return a


def test_expected_outputs_exist(pipeline):
    out, key = pipeline["out"], pipeline["key"]
    for name in (
        f"{key}_ETg_final.tif",
        f"{key}_ETg_baseline_pred.tif",
        f"{key}_ETg_pct_change.tif",
        "treatment_zone.tif",
        "BpS_matched.tif",
        f"{key}_run_metadata.txt",
        f"{key}_polygon_summary.csv",
        f"{key}_ETUNIT_SUMMARY.csv",
    ):
        assert (out / name).exists(), f"missing output: {name}"


def test_irrigation_signal_removed(pipeline):
    """In the treatment zone, the final ETg must be reduced toward the natural
    baseline and never exceed the original (downward-only cap)."""
    key = pipeline["key"]
    tz = _read(pipeline["out"] / "treatment_zone.tif")
    final = _read(pipeline["out"] / f"{key}_ETg_final.tif")
    inp = _read(pipeline["etg"])
    m = (tz == 1) & np.isfinite(final) & np.isfinite(inp)
    assert m.sum() > 0
    # The simulated irrigation block was inflated by +2.5 ft, so the fill must
    # pull the treatment-zone mean down substantially.
    assert np.mean(final[m]) < np.mean(inp[m])
    # Downward-only cap: final never exceeds input by more than fp tolerance.
    assert np.all(final[m] <= inp[m] + 1e-4)


def test_baseline_recovers_class_levels(pipeline):
    """The baseline in the irrigated block should land near the natural level
    of its BpS class (~well below the inflated ~3.6 ft), not the inflated value."""
    key = pipeline["key"]
    base = _read(pipeline["out"] / f"{key}_ETg_baseline_pred.tif")
    finite = base[np.isfinite(base)]
    assert finite.size > 0
    # Synthetic natural ETg ranges roughly 0.5-1.8 ft; baseline must stay in a
    # sane band and well under the irrigation-inflated ~3.6 ft.
    assert 0.0 <= np.nanmin(finite)
    assert np.nanmax(finite) < 2.5


def test_metadata_is_bps_only(pipeline):
    """Run metadata should describe the BpS baseline and carry no ML fields."""
    key = pipeline["key"]
    meta = (pipeline["out"] / f"{key}_run_metadata.txt").read_text()
    assert "spatial_weight_radius_px" in meta
    assert "[baseline]" in meta
    for ml_token in ("cv_r2", "feature_importance", "lgbm", "random_forest",
                     "residual_model"):
        assert ml_token not in meta.lower(), f"unexpected ML token in metadata: {ml_token}"


def test_boundary_derived_from_treatment(tmp_path_factory):
    """Prepped with --treatment (no --boundary), the fill should derive the
    training boundary from the treatment shapefile rather than using all pixels."""
    work = tmp_path_factory.mktemp("noboundary")
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
    key = "NoBound"
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / "NoBound_ETg.tif")   # placed before prep

    # Prep with --treatment only: no separate boundary.
    _run("prep_custom_basin.py", key, "--treatment", str(data["treatment"]),
         "--bps", str(data["bps"]), cwd=work)

    # config.toml must not carry an active boundary_shp line.
    cfg_txt = (work / "basins" / key / "config.toml").read_text()
    assert all(not ln.strip().startswith("boundary_shp")
               for ln in cfg_txt.splitlines()), "boundary_shp should be commented out"

    _run("etg_baseline_fill.py", key, cwd=work)
    meta = (work / "basins" / key / "output" / f"{key}_run_metadata.txt").read_text()
    assert "basin_boundary_mask = yes" in meta, \
        "fill did not build a training boundary from the treatment shapefile"


def test_rates_adjust_roundtrip(tmp_path_factory):
    """The fill writes {key}_rates_adjust.shp next to the treatment shapefile;
    an adj_fctr edited there must be applied on the next run, reported in the
    polygon summary, and carried forward into the regenerated file."""
    import csv as _csv

    work = tmp_path_factory.mktemp("ratesadj")
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
    key = "RatesAdj"
    source = work / "basins" / key / "source"
    source.mkdir(parents=True)
    shutil.copy2(data["etg"], source / "RatesAdj_ETg.tif")
    # The synthetic shapefile carries an adj_fctr column (used by other tests
    # to exercise the shapefile-precedence path).  Drop it here: this test is
    # about tuning through the rates_adjust file, which is only consulted when
    # the treatment shapefile has no adj_fctr overrides of its own.
    g_t = gpd.read_file(data["treatment"]).drop(columns=["adj_fctr"],
                                                errors="ignore")
    g_t.to_file(source / "treatment.shp")

    _run("prep_custom_basin.py", key, "--boundary", str(data["boundary"]),
         "--bps", str(data["bps"]), cwd=work)

    # Run 1: creates the rates file with adj_fctr seeded to 0.
    _run("etg_baseline_fill.py", key, cwd=work)
    rates_shp = source / f"{key}_rates_adjust.shp"
    assert rates_shp.exists(), "fill did not write the rates_adjust shapefile"
    g = gpd.read_file(rates_shp)
    for col in ("row_i", "treated", "etg_input", "etg_base", "etg_final",
                "adj_fctr"):
        assert col in g.columns, f"rates_adjust missing column {col}"
    assert (g["adj_fctr"] == 0).all(), "adj_fctr should be seeded to 0"

    def _summary():
        path = work / "basins" / key / "output" / f"{key}_polygon_summary.csv"
        return {r["polygon_id"]: r for r in _csv.DictReader(open(path))}

    before = _summary()
    treated = g[g["treated"] == 1]
    assert len(treated) > 0, "synthetic basin has no treated polygons"
    target = int(treated["row_i"].iloc[0])
    # polygon_summary.csv is keyed by polygon_id; the rates file carries the
    # same value in its poly_id column, so join through that.
    pid = {int(r): str(pd_) for r, pd_ in zip(g["row_i"], g["poly_id"])}

    # Analyst edit: halve the target polygon's rate; original shp untouched.
    g.loc[g["row_i"] == target, "adj_fctr"] = 0.5
    g.to_file(rates_shp)

    # Run 2: the override must round-trip.
    _run("etg_baseline_fill.py", key, cwd=work)
    after = _summary()
    tkey = pid[target]
    assert after[tkey]["adj_factor"] == "0.5", \
        f"adj_factor not reported (got {after[tkey]['adj_factor']!r})"
    assert float(after[tkey]["mean_final_ETg"]) < \
        float(before[tkey]["mean_final_ETg"]), "override did not reduce the rate"
    # Untouched treated polygons must not move.
    for r in treated["row_i"].astype(int).tolist()[1:]:
        assert after[pid[r]]["mean_final_ETg"] == before[pid[r]]["mean_final_ETg"]
    # Regenerated file preserves the edit and refreshes the rates.
    g2 = gpd.read_file(rates_shp)
    assert float(g2.loc[g2["row_i"] == target, "adj_fctr"].iloc[0]) == 0.5


def test_no_ml_dependencies_in_source():
    """The shipped pipeline must not import scikit-learn / lightgbm / whitebox."""
    banned = ("import lightgbm", "import sklearn", "from sklearn",
              "import whitebox", "import py3dep", "RandomForestRegressor")
    offenders = []
    for f in CODE_FILES:
        text = (PROJECT_ROOT / f).read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{f}: {token}")
    assert not offenders, "ML dependency found in shipped source: " + "; ".join(offenders)
