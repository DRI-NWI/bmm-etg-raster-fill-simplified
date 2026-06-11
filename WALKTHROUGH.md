# ETg Baseline Fill -- Walkthrough

A step-by-step guide for running the simplified, BpS-only workflow on a single
basin, then scaling up. If you used the original `bmm-etg-raster-fill`, the main
change is that there is no DEM, no terrain/soil covariates, and no machine-learning
step: the only covariate you prepare is BpS.


## 1. Set up the environment

```bash
conda env create -f environment.yml --solver=classic
conda activate bmm-etg-raster-fill
```

You need one input dataset to get started: the CONUS LANDFIRE BpS raster
(`LF2020_BPS_CONUS.tif`), downloadable from https://landfire.gov.


## 2. Run statewide BpS prep (one time only)

Clip the CONUS BpS raster to the NWI investigation extent. This is the only
one-time prep step.

```bash
python prep_statewide.py --bps /path/to/LF2020_BPS_CONUS.tif
```

Outputs, written to `statewide/`:

- `BpS_statewide.tif` -- BpS clipped to the NWI extent, reprojected to EPSG:32611.
- `bps_lookup.json` -- cached BpS class names and colours (used for symbology and
  for human-readable class names in logs and metadata).

Skip this step entirely if you only ever run custom (non-NWI) basins; in that case
`prep_custom_basin.py` reads BpS directly from the CONUS source.


## 3. Find your basin key

```bash
python prep_basin.py --list
```

This prints all 257 NWI basin keys (e.g. `053_PineValley`) with their names.


## 4. Prep the basin

```bash
python prep_basin.py 053_PineValley
```

This creates `basins/053_PineValley/` with `source/`, `input/`, and `output/`
subfolders, clips BpS into `input/BpS.tif` (with `.clr` / `.qml` symbology), and
generates a default `config.toml`.


## 5. Place your data files

Drop two files into `basins/053_PineValley/source/`:

- Your ETg raster (ft/yr), e.g. `PineValley_etg_median.tif`. This defines the output
  grid.
- Your treatment shapefile with `scale_fctr` and/or `rplc_rt` attribute columns.

Then re-run `python prep_basin.py 053_PineValley`. It preserves the existing
`config.toml` and just fills in the detected filenames if they were placeholders.
(Or edit `config.toml` by hand -- see next step.)


## 6. Review and edit config.toml

Open `basins/053_PineValley/config.toml`. Confirm the `[source]` filenames are
correct, then tune as needed:

```toml
[treatment]
buffer_m         = 90.0     # buffer (m) around treatment polygons
feather_width_px = 4        # Gaussian feather sigma (px) outside the boundary

[adjustment]
baseline_adjust = 1.0       # basin-wide multiplier on the baseline (1.0 = none)
attr_adjust     = "adj_fctr"

[baseline]
spatial_weight_radius_px = 33   # window radius (px), ~1 km at 30 m; 0 = flat class mean
```

The `[baseline] spatial_weight_radius_px` is the main scientific knob. The default
(~1 km) gives a smoothly varying per-class baseline; set it to 0 for a single flat
ETg value per BpS class across the whole basin.


## 7. Run the fill

```bash
python etg_baseline_fill.py 053_PineValley
```

Watch the log. Key things to confirm:

- `valid training pixels` is comfortably above the 50-pixel minimum.
- `BpS classes in training data` looks reasonable for the basin.
- The per-class mean table lists sensible ETg values per vegetation type.
- `Treatment-zone ETg volume change` is negative (the fill removed
  irrigation-inflated signal, as expected).

Outputs land in `basins/053_PineValley/output/`. The two you'll use most are
`053_PineValley_ETg_final.tif` (the filled raster) and
`053_PineValley_ETg_baseline_pred.tif` (the modeled baseline everywhere).


## 8. Run diagnostics and summary

```bash
python diagnostics.py 053_PineValley
python etunit_summary.py 053_PineValley
```

`diagnostics.py` writes eight PNGs (histograms, scatter, BpS box-plots, map panels,
difference and percent-change maps, feather weight). `etunit_summary.py` writes
`053_PineValley_ETUNIT_SUMMARY.csv` with area, ETg volume, and rate (with
mean +/- 1 SD uncertainty bounds) per ET unit.


## 9. Review and identify issues

Open `053_PineValley_ETg_final.tif` and the diagnostic PNGs in QGIS. Look for:

- Treatment zones whose filled values look too high or too low relative to the
  surrounding native vegetation.
- BpS classes that appear only inside treatment (visible in the box-plots), which
  fall back to the basin-wide or global mean.
- Edge artefacts around treatment polygons (the feather map helps here).

If a polygon's baseline needs tuning, use the expert adjustment knob.


## 10. Expert adjustment

The baseline can be scaled up or down based on professional judgment.

### Option A: adjust a single polygon via the shapefile

Add (or edit) an `adj_fctr` column in your treatment shapefile. For any polygon,
a value > 0 multiplies that polygon's baseline (e.g. `0.8` reduces it 20%). Re-run
the fill. Per-polygon values take precedence over the basin-wide default.

### Option B: adjust the whole basin via config.toml

Set `[adjustment] baseline_adjust` to a value other than 1.0 to scale every
treatment polygon's baseline. Per-polygon `adj_fctr` overrides still win where
present.

The adjustment is applied before feathering, and the downward-only cap still
applies: an adjusted baseline is never allowed to exceed the original input ETg.

Document your reasoning (a note in the basin folder, or a commit message) so the
adjustment is reproducible.


## Optional: auto-flag irrigation-influenced polygons

If you'd rather not hand-pick every treatment polygon, run the pre-screening
helper after prep (it needs the ETg raster, BpS, and the treatment shapefile in
place):

```bash
python flag_irrigated.py 053_PineValley
```

It compares each polygon's mean ETg to the natural baseline of its BpS class and
writes `<treatment>_autoflag.shp` (plus a `..._autoflag_report.csv`) with an
`autoflag` column (1 = looks irrigation-influenced) and per-polygon diagnostics
(`etg_mean`, `bps_base`, `etg_ratio`, `etg_excs`, dominant BpS class).

Tune the sensitivity in `config.toml [flag]` (`ratio_thresh`, `min_excess_ft`,
`baseline_pctl`) or on the command line (`--ratio`, `--min-excess`, `--pctl`).

Open `<treatment>_autoflag.shp` in QGIS, review the `autoflag` values against the
diagnostics, and edit any you disagree with - set `autoflag` to 0 to keep a
polygon as-is, or 1 to add one the screen missed. Re-running the helper keeps
your edits (it tracks the raw suggestion separately in `autoflag_a`); pass
`--reset` to recompute from scratch.

To run the fill on the flags, set in `config.toml`:

```toml
[source]
treatment_shp = "<treatment>_autoflag.shp"

[treatment]
attr_replace = "autoflag"
```

or run `flag_irrigated.py ... --mirror-to rplc_rt` to copy the decision into the
standard `rplc_rt` trigger column instead. Then run the fill as usual.


## Running multiple basins

Once several basins are prepped and have their data in place:

```bash
# Prep + fill + diagnostics + summary for every configured basin:
python run_all.py

# Check what's ready first:
python run_all.py --list
python run_all.py --dry-run

# Just specific basins:
python run_all.py 053_PineValley 042_MarysRiverArea
```

After a batch run, `cross_basin_summary.csv` (in the project root) collects training
pixel counts, BpS class counts, treatment pixels, and percent-change stats for every
basin.


## Custom study areas (outside NWI)

For an area that isn't an NWI basin, use `prep_custom_basin.py`.

### What you need

- The CONUS BpS raster.
- Your ETg raster and treatment / ET-unit shapefile.
- Optionally, a separate boundary shapefile (only if the treatment polygons
  don't cover the whole study area).

### Prep the basin

If your ET-unit / treatment shapefile already covers the study area (the usual
case), let it define the area - no separate boundary needed:

```bash
python prep_custom_basin.py SierraValley \
    --treatment /path/to/sierra_valley_etunits.shp \
    --bps       /path/to/LF2020_BPS_CONUS.tif
```

This clips BpS to the treatment shapefile's extent, copies it into `source/`, and
writes a `config.toml` with `boundary_shp` left commented out; the fill derives the
training boundary from the treatment shapefile.

If you do have a distinct basin outline (e.g. the treatment shapefile is only the
irrigated fields), pass it as `--boundary` instead:

```bash
python prep_custom_basin.py SierraValley \
    --boundary  /path/to/sierra_valley_boundary.shp \
    --bps       /path/to/LF2020_BPS_CONUS.tif
```

Either way the script auto-detects a UTM zone if the input is in a geographic CRS.

### Place your data and run

Drop your ETg raster into `basins/SierraValley/source/` (and the treatment
shapefile too, if you used `--boundary`), review `config.toml`, then:

```bash
python etg_baseline_fill.py SierraValley
python diagnostics.py SierraValley
python etunit_summary.py SierraValley
```

### Key differences from NWI basins

- The training mask comes from your `boundary_shp` if set, otherwise the
  treatment shapefile's extent - not the NWI shapefile.
- BpS is clipped from the CONUS source you pass, not from `statewide/`.
- Everything downstream is identical to an NWI basin.


## BpS symbology in QGIS

`prep_basin.py` and `prep_custom_basin.py` embed a color table and raster attribute
table in `input/BpS.tif` and write `BpS.clr` / `BpS.qml` sidecars, so the BpS raster
opens in QGIS or ArcGIS with the original LANDFIRE class names and colours. If the
colours don't load automatically, apply the `.qml` style manually
(Layer Properties > Symbology > Load Style).
