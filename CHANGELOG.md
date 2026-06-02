# Changelog -- bmm-etg-raster-fill (simplified)

All notable changes to this project are documented in this file.

## [1.0.0] - 2026-06-01

Streamlined, BpS-only release.  This repository is a simplified fork of
`bmm-etg-raster-fill` that removes the machine-learning framework and keeps
only the baseline that the cross-validation showed was best.

### Why

In the original two-stage model, a per-BpS-class mean was refined by a
LightGBM / RandomForest terrain-residual model.  Three-fold cross-validation
of the residual model consistently produced a negative R-squared, meaning the
terrain model never improved on the BpS-class baseline; the automatic fallback
to the BpS mean fired on every basin, so the ML branch never contributed to a
final product.  Carrying it added dependencies (scikit-learn, LightGBM), input
data (DEM, slope, WTD, HAND, REM, soil), and prep machinery (OpenTopography /
3DEP downloads, whitebox-tools HAND derivation) that no output ever used.

### Baseline method

The baseline is now a **spatially weighted per-BpS-class mean** ETg.  For each
LANDFIRE Biophysical Settings class, each pixel's baseline is a Gaussian-windowed
local mean of the non-irrigated, in-basin training pixels of that same class
(default radius ~1 km).  Set `spatial_weight_radius_px = 0` for a flat
basin-wide class mean.  Treatment handling is unchanged: buffered treatment
zones are replaced with the (optionally adjusted) baseline, never allowed to
exceed the original input ETg, and Gaussian-feathered into the surrounding
landscape just outside the boundary.

### Removed

- The LightGBM / RandomForest terrain-residual model, 3-fold cross-validation,
  early stopping, and the negative-CV fallback logic.
- All terrain / ancillary covariates: DEM, slope, WTD (water-table depth),
  HAND (height above nearest drainage), REM (relative elevation model), and
  gSSURGO soil (AWC, depth to restrictive layer).
- The slope-based training-pixel filter (`max_slope_deg`).
- Scripts: `opentopo.py` (OpenTopography DEM download) and `fetch_wtd.py`
  (HydroFrame WTD download).
- Covariate prep in `prep_statewide.py` / `prep_basin.py` /
  `prep_custom_basin.py` for everything except BpS, plus the whitebox-tools
  HAND/REM derivation helpers.
- Dependencies: `scikit-learn`, `lightgbm`, `py3dep`, `whitebox`,
  `hf-hydrodata`.

### Changed

- `config.toml` lost its `[model]`, `[lgbm]`, and `[rf]` sections and gained a
  small `[baseline]` section (`spatial_weight_radius_px`, `max_train_pixels`,
  `random_seed`).  Legacy `[model] spatial_fallback_radius_px` is still read for
  backward compatibility.
- `prep_statewide.py` now only clips BpS and caches the BpS class lookup.
- `prep_basin.py` / `prep_custom_basin.py` now only clip BpS (plus, for custom
  basins, copy the boundary shapefile) and generate `config.toml`.
- `run_all.py` uses `BpS.tif` (not `DEM.tif`) as the prep/readiness sentinel,
  and the cross-basin summary reports BpS-baseline metrics instead of model
  CV / feature-importance metrics.
- Run metadata (`*_run_metadata.txt`) drops the model, feature-importance, and
  CV sections and adds a `[baseline]` block.

### Unchanged

- Treatment-zone classification, buffering, per-polygon and basin-wide expert
  adjustment, downward-only cap, and Gaussian edge feathering.
- `diagnostics.py`, `etunit_summary.py`, `bps_utils.py`, and `prep_humboldt.py`
  carry over from the original (no model dependencies).
- The NWI 257-basin framework, custom-basin workflow, per-basin `config.toml`,
  and batch orchestration.
- Output file names, so existing QGIS/ArcGIS projects and downstream tooling
  keep working.

### Added

- `flag_irrigated.py`, an optional pre-screening helper that flags treatment
  polygons whose ETg is elevated relative to their BpS class (ratio + minimum
  excess against a robust per-class median baseline). It writes an `autoflag`
  attribute plus diagnostics to a copy of the treatment shapefile; analyst edits
  to `autoflag` are preserved across re-runs (overrides are sticky). Configurable
  via a new `[flag]` section in `config.toml`. It also writes a per-BpS-class
  summary (`{key}_autoflag_class_summary.csv`) reporting the share of each
  class's area that ended up flagged, and warns when a class is largely
  irrigated (its median baseline may be inflated, causing under-flagging).
- `tests/` with a self-contained pytest smoke test that runs the full pipeline
  on synthetic data (`pytest -q`) and asserts the irrigation signal is removed
  and no machine-learning dependencies are imported, plus tests for the
  auto-flagger (detection, non-detection of natural polygons, sticky overrides).
- Updated `ETg_fill_methodology.docx`, rewritten to document the BpS-only
  spatially weighted per-class baseline.
