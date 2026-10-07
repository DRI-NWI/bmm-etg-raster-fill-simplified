# ETg Baseline Fill -- Walkthrough

A step-by-step guide for running the simplified, BpS-only workflow on a single
basin, then scaling up. If you used the original `bmm-etg-raster-fill`, the main
change is that there is no DEM, no terrain/soil covariates, and no machine-learning
step: the only covariate you prepare is BpS.

> **Running this for the first time?** Use
> [COOKBOOK_PineValley.md](COOKBOOK_PineValley.md) instead. It is this same
> workflow on Pine Valley with the actual console output beside every command,
> a checkpoint after each step, the numbers a correct run produces, and a
> troubleshooting table. Come back here for the general case once Pine Valley
> reproduces.


## 1. Set up the environment

> **Which window to type in.** On Windows, open the **Anaconda Prompt** (or
> Miniforge Prompt) from the Start menu. On a Mac, open **Terminal**. Every
> command in this guide is typed the same way in both. Type one line at a
> time and press Enter. Example paths are shown in Windows form
> (`C:\path\to\file.tif`); on a Mac, use your own path instead
> (`/Users/you/Downloads/file.tif`).

```
conda env create -f environment.yml --solver=classic
conda activate bmm-etg-raster-fill
```

You need one input dataset to get started: the CONUS LANDFIRE BpS raster
(`LF2020_BPS_CONUS.tif`), downloadable from https://landfire.gov.

Check that the `gdal` Python bindings came through, because `rasterio` alone
does not provide them and they are what read the LANDFIRE class names:

```
python -c "from osgeo import gdal; print(gdal.__version__)"
```

If that fails, run `conda install -c conda-forge gdal`. Only two things need
it: building `bps_lookup.json` in step 2, and embedding the colour table in
each basin's `BpS.tif`. Build the lookup without gdal and every class comes out
as `BpS 1073` with a grey palette, and everything downstream inherits that.


## 2. Run statewide BpS prep (one time only)

Clip the CONUS BpS raster to the NWI investigation extent. This is the only
one-time prep step.

```
python prep_statewide.py --bps C:\path\to\LF2020_BPS_CONUS.tif
```

Outputs, written to `statewide/`:

- `BpS_statewide.tif` -- BpS clipped to the NWI extent, reprojected to EPSG:32611.
- `bps_lookup.json` -- cached BpS class names and colours (used for symbology and
  for human-readable class names in logs and metadata).

Skip this step entirely if you only ever run custom (non-NWI) basins; in that case
`prep_custom_basin.py` reads BpS directly from the CONUS source.


## 3. Find your basin key

```
python prep_basin.py --list
```

This prints all 257 NWI basin keys (e.g. `053_PineValley`) with their names.


## 4. Prep the basin

```
python prep_basin.py 053_PineValley
```

This creates `basins/053_PineValley/` with `source/`, `input/`, and `output/`
subfolders, clips BpS into `input/BpS.tif` (with `.clr` / `.qml` symbology), and
generates a default `config.toml`.


## 5. Place your data files

Drop two files into `basins/053_PineValley/source/`:

- Your ETg raster (ft/yr), e.g. `PineValley_etg_median.tif`. This defines the output
  grid.
- Your treatment shapefile. A polygon is treated when any of these numeric
  columns is above 0: `scale_fctr` or `rplc_rt` (modeled fill), `bsnAv_flag`
  (basin-average fill), or `fixed_rt` (a rate burned in as-is). Column names
  can be changed in `config.toml`; see [ADJUSTING_RATES.md](ADJUSTING_RATES.md)
  for what each one does.

Then re-run `python prep_basin.py 053_PineValley`. It fills in the two
`# PLACE ...` placeholders with the filenames it detects, and changes nothing
else -- any value you have already set stays as you left it. The log tells you
which fields it filled:

```
config.toml already exists - filled in etg_tif, treatment_shp
  (your other edits are untouched)
```

If it detects the wrong file (several rasters in `source/`, say), edit
`config.toml` by hand -- see the next step.


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

```
python etg_baseline_fill.py 053_PineValley
```

Watch the log. Key things to confirm:

- The `polygons:` line under step 2 and the three mode counts beneath it
  (`baseline fill`, `basin average`, `fixed rate`) match what you expect from
  the shapefile. A column that is absent is reported as such.
- `valid training pixels` is comfortably above the 50-pixel minimum. For a
  basin the size of Pine Valley, expect six figures; a few thousand means the
  training boundary is wrong.
- No boundary-coverage warning in step 4 (custom basins only).
- `BpS classes in training data` looks reasonable for the basin.
- The per-class mean table lists sensible ETg values per vegetation type.
- `Treatment-zone ETg volume change` is negative (the fill removed
  irrigation-inflated signal, as expected).

Outputs land in `basins/053_PineValley/output/`. The two you'll use most are
`053_PineValley_ETg_final.tif` (the filled raster) and
`053_PineValley_ETg_baseline_pred.tif` (the modeled baseline everywhere).


## 8. Run diagnostics and summary

```
python diagnostics.py 053_PineValley
python etunit_summary.py 053_PineValley
```

`diagnostics.py` writes seven PNGs (histogram, scatter, BpS box-plots, map panels,
difference map, treatment-zone map, feather weight). The eighth figure in
`output/`, `053_PineValley_diag_pct_change_map.png`, was already written by the
fill. `etunit_summary.py` writes
`053_PineValley_ETUNIT_SUMMARY.csv` with area, ETg volume, and rate (with
mean +/- 1 SD uncertainty bounds) per ET unit.


## 9. Review and identify issues

Open `053_PineValley_ETg_final.tif` and the diagnostic PNGs in QGIS. Look for:

- Treatment zones whose filled values look too high or too low relative to the
  surrounding native vegetation.
- BpS classes that appear only inside treatment (visible in the box-plots), which
  fall back to the basin-wide or global mean.
- Edge artefacts around treatment polygons (the feather map helps here).

If a polygon's baseline needs tuning, use the expert adjustment knob. If it
needs a specific number (open water, say), burn one in with `fixed_rt`.
`output/{basin_key}_polygon_summary.csv` says how each polygon was handled
(`treatment` and `trigger` columns).


## 10. Expert adjustment

The baseline can be scaled up or down based on professional judgment, or
replaced outright with a number you supply. For a plain-language walk through
every editable column, see [ADJUSTING_RATES.md](ADJUSTING_RATES.md).

### Option A: adjust single polygons via the rates file

Every fill run writes `{basin_key}_rates_adjust.shp` next to the treatment
shapefile. It carries each polygon's input / baseline / final rates and a
pre-seeded, editable `adj_fctr` column. Open it in QGIS, set `adj_fctr` on the
polygons you want to change (a value > 0 multiplies that polygon's baseline,
e.g. `0.8` reduces it 20%), and re-run the fill. Edits round-trip: the next
run reads them back and rewrites the file with refreshed rates and your
overrides intact. Per-polygon values take precedence over the basin-wide
default. (Adding an `adj_fctr` column to the treatment shapefile itself still
works and wins over the rates file.)

### Option B: adjust the whole basin via config.toml

Set `[adjustment] baseline_adjust` to a value other than 1.0 to scale every
treatment polygon's baseline. Per-polygon `adj_fctr` overrides still win where
present.

The adjustment is applied before feathering, and the downward-only cap still
applies: an adjusted baseline is never allowed to exceed the original input ETg.

### Option C: burn in a fixed rate

For a polygon whose rate you already know, type it into the `fixed_rt` column
of the same `{basin_key}_rates_adjust.shp` (or add a `fixed_rt` column to the
treatment shapefile) and re-run. That value is written in as-is: no model, no
adjustment factor, no cap, no buffer, no feathering. It is the only override
that can raise a polygon above its input.

Document your reasoning (a note in the basin folder, or a commit message) so the
adjustment is reproducible.


## Optional: auto-flag irrigation-influenced polygons

If you'd rather not hand-pick every treatment polygon, run the pre-screening
helper after prep (it needs the ETg raster, BpS, and the treatment shapefile in
place):

```
python flag_irrigated.py 053_PineValley
```

It compares each polygon's mean ETg to the natural baseline of its BpS class and
writes `<treatment>_autoflag.shp` into `source/`, next to the original shapefile
(the `..._autoflag_report.csv` goes to `output/`), with an
`suggested` column (1 = looks irrigation-influenced), an `analyst` column for
your own call, an `autoflag` column with the result, and per-polygon
diagnostics (`etg_mean`, `bps_base`, `etg_ratio`, `etg_excs`, dominant BpS class).

Tune the sensitivity in `config.toml [flag]` (`ratio_thresh`, `min_excess_ft`,
`baseline_pctl`) or on the command line (`--ratio`, `--min-excess`, `--pctl`).

Open `<treatment>_autoflag.shp` in QGIS, review `suggested` against the
diagnostics, and type your call into `analyst` where you disagree: 0 keeps a
polygon as-is, 1 adds one the screen missed, -1 (the default) goes with the
suggestion. `autoflag` is the result and is recomputed every run, so edit
`analyst`, not `autoflag`. Re-running keeps `analyst`; pass `--reset` to clear it.

To run the fill on the flags, set in `config.toml`:

```toml
[source]
treatment_shp = "<treatment>_autoflag.shp"

[treatment]
attr_treat = ["scale_fctr", "rplc_rt", "autoflag"]
```

or run `flag_irrigated.py ... --mirror-to rplc_rt` to copy the decision into the
standard `rplc_rt` trigger column, which saves you the `attr_treat` line. The
`treatment_shp` line is needed either way, because the script writes a copy and
leaves your original shapefile untouched. Then run the fill as usual.


## Running multiple basins

Once several basins are prepped and have their data in place:

Prep + fill + diagnostics + summary for every configured basin:

```
python run_all.py
```

To check what's ready first:

```
python run_all.py --list
python run_all.py --dry-run
```

Just specific basins:

```
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

If your ET-unit / treatment shapefile tiles the study area, let it define the
area - no separate boundary needed. Confirm that it really does tile the basin
rather than covering only the phreatophyte and irrigated ground; if it is the
latter, the fill has almost nothing left to train on and will say so:

```
python prep_custom_basin.py SierraValley --treatment C:\path\to\sierra_valley_etunits.shp --bps C:\path\to\LF2020_BPS_CONUS.tif
```

This clips BpS to the treatment shapefile's extent, copies it into `source/`, and
writes a `config.toml` with `boundary_shp` left commented out; the fill derives the
training boundary from the treatment shapefile.

If you do have a distinct basin outline (e.g. the treatment shapefile is only the
irrigated fields), pass it as `--boundary` instead:

```
python prep_custom_basin.py SierraValley --boundary C:\path\to\sierra_valley_boundary.shp --bps C:\path\to\LF2020_BPS_CONUS.tif
```

Either way the script auto-detects a UTM zone if the input is in a geographic CRS.

### Place your data and run

Drop your ETg raster into `basins/SierraValley/source/` (and the treatment
shapefile too, if you used `--boundary`), review `config.toml`, then:

```
python etg_baseline_fill.py SierraValley
python diagnostics.py SierraValley
python etunit_summary.py SierraValley
```

### Key differences from NWI basins

- The training mask comes from your `boundary_shp` if set, otherwise the
  treatment shapefile's extent - not the NWI shapefile. The fill warns when
  that derived boundary covers less than 25% of the valid ETg extent; if you
  see the warning, re-prep with `--boundary` or set `boundary_shp` by hand.
- BpS is clipped from the CONUS source you pass, not from `statewide/`.
- Everything downstream is identical to an NWI basin.


## BpS symbology in QGIS

`prep_basin.py` and `prep_custom_basin.py` always write `BpS.clr` / `BpS.qml`
sidecars, and additionally embed a color table and raster attribute table inside
`input/BpS.tif` when the `gdal` Python bindings are installed (see step 1). With
the embed, the BpS raster opens in QGIS or ArcGIS already carrying the LANDFIRE
class names and colours; without it, apply the `.qml` style manually
(Layer Properties > Symbology > Load Style). The prep log says which happened.
