# Changelog -- bmm-etg-raster-fill (simplified)

All notable changes to this project are documented in this file.

## [1.0.4] - 2026-08-19

### Removed

- **`[baseline] max_train_pixels` and `random_seed`** - the last functional
  remnants of the ML era.  The random-subsample cap existed to bound
  model-training cost; the simplified baseline is per-class
  means plus Gaussian smoothing, whose cost depends on raster size, not on
  training-pixel count.  Measured on Pine Valley: capping to 50k of 165,811
  pixels saved no time (10.5 s vs 10.7 s) but changed the treatment-zone
  volume change from -43.40% to -43.05%, cut rare classes to a handful of
  pixels (pinyon-juniper to n=1), and made the answer seed-dependent
  (seed 42: -43.05%; seed 7: -42.40%).  All valid pixels are now always used,
  so results on basins large enough to have tripped the cap (>500k training
  pixels) are deterministic and change slightly; basins under the cap,
  including Pine Valley, are unchanged.  Old config.toml files that still
  carry the two keys keep working - they are ignored.
  (`random_seed` never affected anything unless the cap fired.)

## [1.0.3] - 2026-07-29

Makes the review-and-tune loop usable.  No change to the modeled values: the
Pine Valley fill reproduces the 1.0.0 numbers exactly.

### Fixed

- **`polygon_id` was not an identifier.**  The column picker accepted
  `ET_unit`, which is a category, so 96 rows of the Pine Valley summary all
  read `cropland` and no row could be traced back to a feature.  Candidates
  (`DRI_ID`, `UniqueID`, `OBJECTID`, `FID`) are now accepted only when every
  value is present and distinct, otherwise `polygon_id` is the shapefile row
  number.  The run logs which one it used.

### Added

- `{key}_polygon_summary.csv` gains `legacy_rplc_rt` and
  `baseline_minus_legacy` when the treatment shapefile carries `rplc_rt`, so
  the modeled baseline can be reviewed against the analyst's hand-picked rate
  without a manual join.
- `flag_irrigated.py` seeds empty `UniqueID` and `adj_fctr` columns into the
  `_autoflag` copy it writes when the source lacks them, so the per-polygon
  tuning knob exists without anyone editing the original shapefile.  The
  original is still never modified.
- The fill now says what to do when `adj_fctr` is missing, instead of only
  reporting that it is.
- A "Where the rates are, and how to tune them" section in
  `COOKBOOK_PineValley.md`.

## [1.0.2] - 2026-07-29

### Fixed

- **`UnicodeEncodeError` on Windows.**  `diagnostics.py`, `etunit_summary.py`,
  and `prep_humboldt.py` printed characters (`->`, `x`, `...`, box-drawing
  rules, en and em dashes) that cp1252 cannot encode.  Windows uses the locale
  code page, not UTF-8, whenever stdout is redirected or captured, so `pytest`
  and `python run_all.py > log.txt` both died while the same commands worked
  in an interactive console.  Four smoke tests errored out at
  `etunit_summary.py` line 128.  All Python source is now plain ASCII.

### Added

- Two regression guards for the above, both of which reproduce the Windows
  failure on Linux and macOS:
  - `tests/test_repo_files.py::test_source_is_ascii` scans every `.py` file.
  - `tests/test_pipeline_smoke.py` now runs its subprocesses with
    `PYTHONIOENCODING=cp1252`.

## [1.0.1] - 2026-07-29

Packaging and documentation fixes found while re-running the Pine Valley
workflow from a clean checkout.  No change to the science: the fill reproduces
the 1.0.0 outputs exactly.

### Fixed

- **`basins/_template/config.toml` was not tracked in git.**  `.gitignore`
  excluded all of `basins/`, so a fresh clone had no config template and every
  prep script exited with "config template not found".  Nine of the ten tests
  failed for the same reason.  `.gitignore` now uses `basins/*` with a negation
  for `basins/_template/`.
- **`statewide/bps_lookup.json` is now tracked** (180 KB of LANDFIRE class
  names and colours), so a new clone gets readable class names without
  rebuilding the statewide clip.
- **`gdal` added to `environment.yml`.**  `bps_utils.py` reads the LANDFIRE
  raster attribute table through `osgeo.gdal`, which conda-forge `rasterio`
  does not provide.  Without it `prep_statewide.py` silently produced a lookup
  with no class names (`BpS 1073`) and a grey palette, and the color table and
  RAT were never embedded in `BpS.tif`.  The prep log now names the reason
  instead of "non-integer dtype or GDAL missing".
- **`prep_basin.py` / `prep_custom_basin.py` now back-fill `# PLACE ...`
  placeholders** in an existing `config.toml`, which is what WALKTHROUGH.md
  step 5 always claimed.  Only unfilled placeholders are touched; every other
  value stays as the user left it.  The shared helper is
  `basin_config.backfill_source_files`.
- **`diagnostics.py` printed filenames that don't exist**, reporting
  `diag_histogram.png` while writing `{basin_key}_diag_histogram.png`.
- **Divide-by-zero warning** on every run from `_spatially_weighted_bps_mean`;
  the fallback branch is now selected with `np.divide(..., where=)`.

### Added

- The fill warns when a treatment-derived training boundary covers less than
  25% of the valid ETg extent.  ET-unit shapefiles that cover only the
  phreatophyte and irrigated ground leave very few training pixels, and the
  result differed by 12 percentage points on Pine Valley with no indication in
  the log.
- `tests/test_repo_files.py`, guarding that the two required files inside the
  ignored data folders exist and are not gitignored.
- `prep_statewide.py` and `prep_humboldt.py` added to the smoke test's
  no-machine-learning-imports scan.
- A batch-and-utility flag reference in README.md.  The `--all / --only /
  --skip / --list / --stop-on-error` interface on the four per-basin scripts
  was implemented but undocumented.
- `COOKBOOK_PineValley.md`, a worked end-to-end example on basin 053.  Every
  command is shown with its verified console output, a "you should now have"
  checkpoint, and the reference numbers a correct run produces (165,811
  training pixels, -43.40% treatment-zone volume change, 45,172 ac /
  27,331 ac-ft), plus a troubleshooting table.  README.md and WALKTHROUGH.md
  point new users at it.

### Changed

- `prep_humboldt.py` renders a missing `config.toml` from the shared template
  instead of a five-line stub, and its docstring now states that it does
  overwrite the two `[source]` filenames (that is its job) rather than
  implying `prep_basin.py` completes the file later.
- Removed the `[flag] trigger_attr` key.  It was read into
  `basin_config.FLAG_TRIGGER_ATTR` and never used; `flag_irrigated.py`
  hardcodes `autoflag`.

### Documentation

- README.md: corrected the claim that all output filenames carry the basin-key
  prefix (three intermediate rasters do not), noted that
  `<treatment>_autoflag.shp` is written to `source/` rather than `output/`,
  added `tests/`, `Sample_Commands.txt`, and `ETg_fill_methodology.docx` to the
  repository structure, and added a "Training boundary on custom basins"
  caveat.
- WALKTHROUGH.md: `diagnostics.py` writes seven PNGs, not eight (the
  percent-change map comes from the fill), plus a `gdal` check in step 1 and
  the boundary-coverage caveat.
- `diagnostics.py` and `etunit_summary.py` docstrings showed a usage example
  with no basin key, which exits with a usage error.
- Sample_Commands.txt now covers `flag_irrigated.py`, the setup check, the
  placeholder back-fill step, and the batch flags.

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
- `boundary_shp` is now optional and redundant for the usual ET-unit workflow:
  when it isn't set (and the basin isn't an NWI match), the fill and
  `flag_irrigated.py` derive the training boundary from the dissolved extent of
  the treatment shapefile. `prep_custom_basin.py` gained an optional
  `--treatment` argument (use it instead of `--boundary` when the treatment
  shapefile already covers the study area), and `--boundary` is no longer
  required. An explicit `boundary_shp` still overrides, for cases where the
  treatment polygons cover less than the full basin.
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
