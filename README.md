# bmm-etg-raster-fill (simplified)

This tool replaces the manual approach of burning uniform ETg replacement rates
into 30-meter Landsat-derived ETg rasters. Instead, it builds a natural-baseline
estimate of what ETg *would* look like in irrigated areas if the irrigation were
absent, using the surrounding native vegetation as the reference.

This is a streamlined version of the original `bmm-etg-raster-fill`. The original
refined a per-vegetation-class baseline with a machine-learning terrain model
built on elevation, slope, water-table depth, and related covariates.
Cross-validation showed that terrain model never improved on the
vegetation-class baseline, so it was removed along with all of its input data and
dependencies. See [CHANGELOG.md](CHANGELOG.md) for details.

Developed at the [Desert Research Institute (DRI)](https://www.dri.edu/) for
Nevada's NWI investigation basins (257 hydrographic areas extending into adjacent
states). The workflow also supports custom study areas outside the NWI framework
via `prep_custom_basin.py`.

> **AI disclosure:** This codebase was developed collaboratively with Claude (Anthropic).
> All scientific decisions, model design choices, and domain validation were made by DRI
> research staff. See [AI_DISCLOSURE.md](AI_DISCLOSURE.md) for details.


## What this tool does, in plain language

In arid basins across Nevada, some of the water that evaporates or is transpired by
plants comes from groundwater. Measuring this "groundwater ET" across an entire
valley matters for managing the water budget, and satellites make it possible: we
can estimate how much water each 30-meter patch of land loses to the atmosphere by
looking at how green the vegetation is in Landsat imagery.

The challenge is irrigated farmland. A center-pivot alfalfa field shows up as very
green, and the ET estimate is high, but most of that water came from a well or a
ditch, not from the natural water table. To build an accurate groundwater budget we
need to answer: *if that field had never been irrigated, how much groundwater ET
would the native vegetation at that spot naturally produce?*

Previously a hydrologist drew a polygon around each irrigated area, picked a single
number (a "replacement rate") based on professional judgment, and pasted that number
uniformly across every pixel in the polygon.

This tool replaces that manual step. It looks at all the land *outside* the
irrigated areas (the sagebrush flats, the un-irrigated meadows, the hillslopes) and
learns the typical ETg of each natural vegetation type, then applies a spatial
smooth so the estimate varies gradually across the landscape. It then predicts what
each irrigated pixel's ETg *would* be if the irrigation were removed.


## The baseline method

Every pixel belongs to a LANDFIRE Biophysical Settings (BpS) vegetation class.
Sagebrush, wet meadow, and riparian willow each use water at different rates. The
tool computes, for each BpS class, the typical ETg of that class from the
non-irrigated training pixels, and applies a **Gaussian spatial weighting** so that
nearby reference pixels count more than distant ones:

> For each BpS class, a pixel's baseline is a Gaussian-windowed local mean of the
> non-irrigated, in-basin training pixels of that same class (default window radius
> ~1 km at 30 m resolution).

Where a window contains no training pixels of a class, the basin-wide mean for that
class is used. BpS classes that never appear outside treatment fall back to the
global training mean. Set `spatial_weight_radius_px = 0` in `config.toml` for a flat
basin-wide class mean (one value per class, no spatial variation within a class).

NDVI and other greenness indices are intentionally **excluded**, because they carry
the irrigation signal we are trying to remove.

There is no machine learning, no DEM, and no terrain or soil covariates.


## Background

### The Beamer-Minor Model

This tool builds on the Beamer-Minor Model (BMM), a place-based approach for
estimating groundwater evapotranspiration (ETg) from phreatophyte and riparian
vegetation across the Great Basin. The original framework established an empirical
relationship between Landsat-derived vegetation indices and flux-tower-calibrated ET
measurements to produce spatially distributed ETg estimates at 30-meter resolution
(Beamer et al., 2013). Minor (2019) extended this work to a basin-by-basin
methodology for estimating annual ETg across Great Basin hydrographic areas. The
combined BMM framework has been applied across Nevada and northeastern California,
including basin-scale groundwater discharge assessments for the Humboldt River Basin
(Huntington et al., 2022) and site-specific monitoring at contamination and
remediation sites (Huntington and Bromley, 2023).

### The problem with uniform burn-in

A key step in the BMM workflow is the delineation of "ET units": polygons
representing distinct land-use and vegetation categories. Within irrigated ET units,
the Landsat-derived ETg signal includes both the natural groundwater contribution
and the enhancement from applied irrigation water. The legacy workflow assigns each
irrigated polygon a uniform replacement rate chosen by an analyst and burns it into
the raster. This is defensible at the polygon level but lacks spatial realism: every
pixel in a polygon gets the same value regardless of the vegetation actually present.

### This tool's approach

Rather than a single number per polygon, this tool asks what ETg would look like at
each pixel if irrigation were removed, and answers with the natural ETg of the
vegetation type present at that pixel, smoothed across space. The result respects
the actual ecology at every pixel and varies continuously rather than in flat polygon
steps.

### Treatment handling

Any polygon in the treatment shapefile with `scale_fctr > 0` or `rplc_rt > 0` is
treated: its pixels are fully replaced with the modeled baseline. Polygons where both
attributes are zero are left untouched.

All treatment polygons are buffered outward (configurable, default 90 m) to exclude
irrigation edge effects from both the training data and the replacement zone. The
replacement is never allowed to exceed the original input ETg (a downward-only cap).
Gaussian feathering applies *outside* the treatment boundary, blending the baseline
values smoothly into the surrounding raw ETg landscape.


## Repository structure

Data folders (`statewide/`, `basins/`) are not tracked in git, apart from two
small files the workflow cannot start without: `basins/_template/config.toml`
and `statewide/bps_lookup.json`. Everything else in them is regenerated locally.

```
project/
    statewide/                  BpS clipped to the NWI extent (one-time prep)
        BpS_statewide.tif       (local only, ~100 MB)
        bps_lookup.json         Cached BpS class lookup (code, R, G, B, name) -- tracked

    basins/                     Per-basin directories (257 NWI basins)
        053_PineValley/
            config.toml         Per-basin configuration (auto-generated, editable)
            source/             Raw ETg raster + treatment shapefile (you drop these in)
            input/              Prep-generated BpS.tif (+ .clr / .qml symbology)
            output/             Fill results, diagnostics, logs
        _template/
            config.toml         Template used by prep scripts to generate each
                                basin's config.toml.  Edit to change defaults.
                                Tracked in git; prep fails without it.

    prep_statewide.py       One-time: clip CONUS BpS to NWI extent
    prep_basin.py           Per-basin: clip BpS + generate config.toml (NWI)
    prep_custom_basin.py    Set up a basin from any boundary shapefile (non-NWI)
    prep_humboldt.py        Stage the Humboldt 2022 dataset into basin dirs
    basin_config.py         TOML config reader (per-basin config interface)
    bps_utils.py            BpS class-name / colour (RAT) and symbology utilities
    etg_baseline_fill.py    Main workflow (training, prediction, fill, feathering)
    flag_irrigated.py       Optional pre-screen: auto-flag irrigation-influenced polygons
    diagnostics.py          Post-run plots and distribution summaries
    etunit_summary.py       ET-unit-level summary CSV (area, volume, rates)
    run_all.py              Orchestrator: batch-process multiple basins
    NWI_Investigations_EPSG_32611.shp  Basin boundaries, 257 areas (EPSG:32611)
    tests/                  Self-contained pytest suite (synthetic data)
    environment.yml         Conda environment specification
    README.md               This file
    WALKTHROUGH.md          Step-by-step guide for new users
    COOKBOOK_PineValley.md  Worked example: one basin, real output, expected numbers
    Sample_Commands.txt     Copy-paste command reference
    ETg_fill_methodology.docx  Methodology write-up
    AI_DISCLOSURE.md        AI-assisted development disclosure
    CHANGELOG.md            Version history
    LICENSE                 MIT license
```


## Quick start

New to this workflow? Run [COOKBOOK_PineValley.md](COOKBOOK_PineValley.md)
first. It walks one basin end to end with the console output printed beside
every command and the numbers a correct run produces, so you can confirm your
install before trusting a basin you don't already know the answer for.

### 1. Install dependencies

```bash
conda env create -f environment.yml --solver=classic
conda activate bmm-etg-raster-fill
```

Key packages: `numpy`, `scipy`, `rasterio`, `geopandas`, `fiona`, `shapely`,
`pyproj`, `matplotlib`, `gdal`, and `tomli` (only for Python < 3.11).

`gdal` supplies the `osgeo` Python bindings, which read the LANDFIRE class
names and colours out of the BpS raster attribute table. Installing `rasterio`
alone does not provide them. Exactly two steps need it: `prep_statewide.py`,
when it builds `statewide/bps_lookup.json`, and the colour-table embed inside
each basin's `input/BpS.tif`. Everything downstream reads the cached lookup, so
a good `bps_lookup.json` (one ships with the repo) covers the rest. Build that
file without gdal and it comes out with no class names at all, which then
propagates into every log and figure.

### 2. Prepare the statewide BpS (one time)

Clip the CONUS-wide LANDFIRE BpS raster to the NWI investigation extent:

```bash
python prep_statewide.py --bps /path/to/LF2020_BPS_CONUS.tif
```

This writes `statewide/BpS_statewide.tif` (reprojected to the NWI shapefile CRS,
EPSG:32611) and `statewide/bps_lookup.json` (class names and colours).

### 3. Set up basin directories

```bash
# List all 257 basin keys from the NWI shapefile:
python prep_basin.py --list

# Prep a single basin (clips BpS, generates config.toml):
python prep_basin.py 053_PineValley

# Prep all basins at once:
python prep_basin.py --all
```

`prep_basin.py` writes `BpS.tif` (with `.clr` / `.qml` symbology) to
`basins/<basin_key>/input/`, then place each basin's ETg raster and treatment
shapefile into its `basins/<basin_key>/source/` directory and review the generated
`config.toml`.

### 4. Configure per-basin parameters

Each basin gets a `config.toml` with sensible defaults. Edit as needed:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `[source] etg_tif` | -- | ETg raster filename (in `source/`) |
| `[source] treatment_shp` | -- | Treatment shapefile filename |
| `[source] boundary_shp` | -- | Optional. Training-boundary shapefile. If omitted, the boundary is taken from the treatment shapefile's extent (or the NWI outline for NWI basins) |
| `buffer_m` | `90.0` | Buffer distance (m) around treatment polygons |
| `feather_width_px` | `4` | Gaussian feathering sigma in pixels |
| `baseline_adjust` | `1.0` | Expert adjustment scalar (0.8 = reduce 20%) |
| `attr_adjust` | `adj_fctr` | Per-polygon adjustment override column |
| `spatial_weight_radius_px` | `33` | Gaussian window radius (px) for per-BpS mean; ~1 km at 30 m; 0 = flat class mean |

### 5. Run

```bash
# Single basin:
python etg_baseline_fill.py 053_PineValley
python diagnostics.py 053_PineValley
python etunit_summary.py 053_PineValley

# All configured basins (prep + fill + diagnostics + summary):
python run_all.py

# Dry run -- show what would be processed:
python run_all.py --dry-run

# Check readiness of all basins:
python run_all.py --list
```

### Batch and utility flags

The four per-basin scripts share the same batch interface, so anything you can
do for one basin you can do for many:

| Flag | Applies to | Purpose |
|------|------------|---------|
| `--all` | `etg_baseline_fill`, `diagnostics`, `etunit_summary`, `flag_irrigated`, `prep_basin` | Process every basin with a `config.toml` |
| `--only KEY [KEY ...]` | `etg_baseline_fill`, `diagnostics`, `etunit_summary`, `flag_irrigated` | Process just these basins |
| `--skip KEY [KEY ...]` | same, with `--all` | Leave these basins out |
| `--list` | same, plus `prep_basin`, `run_all` | List basins and exit |
| `--stop-on-error` | `etg_baseline_fill`, `diagnostics`, `etunit_summary` | Abort the batch on the first failure (default: continue) |

Script-specific flags:

| Flag | Script | Purpose |
|------|--------|---------|
| `--force` | `prep_basin`, `prep_custom_basin` | Re-clip `BpS.tif` even if it exists |
| `--only-missing` | `prep_basin --all` | Skip basins that already have `BpS.tif` |
| `--buffer-m` | `prep_statewide` (10000), `prep_custom_basin` (5000) | Clip buffer in metres |
| `--prep-only`, `--skip-prep`, `--skip-diag`, `--skip-summary` | `run_all` | Run part of the four-step pipeline |
| `--dry-run` | `run_all`, `prep_humboldt` | Show what would happen, write nothing |
| `--ratio`, `--min-excess`, `--pctl`, `--reset`, `--mirror-to` | `flag_irrigated` | Override `[flag]` thresholds; see below |

### 6. Custom study areas (non-NWI)

For basins outside the Nevada NWI framework (e.g. Sierra Valley CA, or basins in
other states), use `prep_custom_basin.py`:

```bash
python prep_custom_basin.py SierraValley \
    --boundary  /path/to/sierra_valley_boundary.shp \
    --bps       /path/to/LF2020_BPS_CONUS.tif
```

This clips BpS to the boundary, copies the boundary into `source/boundary.shp`, and
generates a `config.toml` with a `[source]` section that references it. Drop your raw
ETg raster and treatment shapefile into `source/`, then run the fill. If your
boundary uses a geographic CRS (e.g. EPSG:4326), the script auto-detects the
appropriate UTM zone from the centroid.

If your ET-unit / treatment shapefile covers the whole study area, you
don't need a separate boundary - pass it as `--treatment` and the fill derives the
training boundary from its extent. Check first: this only works when the ET units
tile the basin. If the shapefile covers just the phreatophyte and irrigated
areas, the derived boundary is much smaller than the basin, most of it is inside
the buffered treatment zones, and very little is left to train on. The fill warns
when the derived boundary covers less than 25% of the valid ETg extent; if you
see that warning, supply `--boundary` instead.

```bash
python prep_custom_basin.py SierraValley \
    --treatment /path/to/sierra_valley_etunits.shp \
    --bps       /path/to/LF2020_BPS_CONUS.tif
```

This clips BpS to the treatment shapefile's extent, copies it into `source/`, and
generates a `config.toml` with `boundary_shp` left commented out. Drop your ETg
raster into `source/` and run the fill.

The resulting basin directory is identical in structure to an NWI basin, and all
downstream scripts work the same way.


## Pre-screening: flagging irrigation-influenced polygons

Normally a GIS analyst decides which polygons need treatment by setting
`scale_fctr` or `rplc_rt` in the treatment shapefile. `flag_irrigated.py` is an
optional helper that proposes those flags automatically, so the analyst starts
from a first pass instead of a blank slate.

For each BpS class it computes a robust natural baseline ETg (a percentile,
default the median, of the raw ETg over all in-basin pixels of that class - the
median is resistant to the elevated minority of irrigated pixels). Each
polygon's expected baseline is the pixel-count-weighted average of the baselines
of the BpS classes it covers. A polygon is auto-flagged when its mean ETg is
both a configurable multiple of that baseline **and** a configurable amount
above it:

```
mean ETg  >=  ratio_thresh x expected_baseline      (default 1.5x)
   AND
mean ETg  -  expected_baseline  >=  min_excess_ft    (default 0.3 ft/yr)
```

The min-excess guard prevents flagging trivial differences in low-ET classes.
Thresholds live in the `[flag]` section of `config.toml` and can be overridden
on the command line.

```bash
python flag_irrigated.py 053_PineValley
python flag_irrigated.py 053_PineValley --ratio 1.4 --min-excess 0.25
python flag_irrigated.py --all
```

The script writes a copy of the treatment shapefile,
`<treatment>_autoflag.shp`, into `basins/<basin_key>/source/` (next to the
original, not in `output/`). It keeps every original attribute and adds:

| Attribute | Meaning |
|-----------|---------|
| `autoflag` | The actionable decision (1 = treat, 0 = leave). **Edit this to override.** |
| `autoflag_a` | The raw machine suggestion (always recomputed; never edited). |
| `etg_mean` | Polygon mean raw ETg |
| `bps_base` | Expected natural baseline for the polygon |
| `etg_ratio` | `etg_mean / bps_base` |
| `etg_excs` | `etg_mean - bps_base` |
| `bps_dom` | Dominant BpS class code in the polygon |
| `n_pix` | Valid pixels in the polygon |

A `{key}_autoflag_report.csv` with the same per-polygon diagnostics is written to
`output/` for review outside GIS.

It also writes `{key}_autoflag_class_summary.csv`, a per-BpS-class diagnostic
giving each class's baseline and the share of its in-basin area that ended up
inside flagged polygons. A high share (>= 50%) means the class is largely
irrigated, so its median baseline is likely inflated and the screen is probably
**under-flagging** it - the run prints a warning suggesting you lower
`baseline_pctl` (e.g. to 30-40) and re-run with `--reset`.

**Reviewing and overriding.** Open `<treatment>_autoflag.shp` in QGIS/ArcGIS,
inspect `autoflag` and the diagnostics, and edit the `autoflag` value where your
professional judgement differs (set it to 0 to reject a false positive, or 1 to
add a feature the screen missed). Re-running the script **preserves your edits**
(it compares `autoflag` against `autoflag_a` to detect overrides) unless you pass
`--reset`. Polygons the analyst had already flagged manually (`scale_fctr` or
`rplc_rt` > 0) are carried over as flagged.

**Running the fill on the flags.** Point the fill at the flagged copy and tell it
to treat on the `autoflag` column - set in `config.toml`:

```toml
[source]
treatment_shp = "<treatment>_autoflag.shp"

[treatment]
attr_replace = "autoflag"
```

Alternatively, run `flag_irrigated.py ... --mirror-to rplc_rt` to copy the flag
into the standard `rplc_rt` trigger column, which saves you the `attr_replace`
line. You still need the `treatment_shp` line either way: the script writes a
copy and never modifies your original shapefile.


## Tests

A self-contained smoke test exercises the whole pipeline on a small synthetic
study area (no network or external data). It generates a BpS raster, an ETg
raster with a simulated irrigation block, a boundary, and a treatment
shapefile, runs `prep_custom_basin` -> `etg_baseline_fill` -> `etunit_summary` as
subprocesses in a temporary directory, and checks that the outputs exist, the
irrigation signal is removed in the treatment zone without exceeding the
original ETg, and the shipped code carries no machine-learning dependencies. A
companion test covers `flag_irrigated.py`: it confirms the inflated block is
auto-flagged, natural polygons are not, and an analyst override survives a
re-run.

```bash
pytest -q
```

The geospatial tests skip automatically if the runtime stack
(`rasterio`, `geopandas`, `scipy`) is not installed.


## Outputs

All output is written to `basins/<basin_key>/output/`. Final products are
prefixed with the basin key (e.g. `053_PineValley_ETg_final.tif`); the three
intermediate rasters (`treatment_zone.tif`, `feather_weight.tif`,
`BpS_matched.tif`) are not, because they are per-basin scratch layers.

One output does not land in `output/`: `flag_irrigated.py` writes
`<treatment>_autoflag.shp` next to the treatment shapefile, in
`basins/<basin_key>/source/`. Its two report CSVs do go to `output/`.

### Rasters (GeoTIFF, DEFLATE-compressed, float32)

| File | Description |
|------|-------------|
| `{key}_ETg_baseline_pred.tif` | Modeled baseline ETg (spatially weighted per-BpS mean) for all pixels |
| `{key}_ETg_final.tif` | Final ETg raster with treatment zones filled |
| `{key}_ETg_pct_change.tif` | Per-pixel percent change (raw to final) |
| `treatment_zone.tif` | Binary mask: 1 = treatment polygon (buffered), 0 = outside |
| `feather_weight.tif` | Gaussian blend weight (1 = baseline, 0 = raw ETg) |
| `{key}_rates_adjust.shp` | (In `source/`, not `output/`.) Per-polygon rates plus an editable `adj_fctr` column; the tuning surface. Edits round-trip on the next run |
| `BpS_matched.tif` | BpS reprojected to the ETg grid |

### Tables (CSV)

| File | Description |
|------|-------------|
| `{key}_polygon_summary.csv` | Per-polygon statistics: `polygon_id`, pixel count, treatment type, `adj_factor`, and mean input / baseline / final ETg. Where the treatment shapefile carries `rplc_rt`, also `legacy_rplc_rt` and `baseline_minus_legacy` for reviewing the modeled rate against the hand-picked one |
| `{key}_ETUNIT_SUMMARY.csv` | ET-unit-level summary: area (ac), volume (ac-ft), rate (ft/yr) with uncertainty |
| `cross_basin_summary.csv` | (Project root) Cross-basin comparison after batch runs |

### Metadata, logs, and symbology

| File | Description |
|------|-------------|
| `{key}_run_metadata.txt` | Configuration, training stats, and per-BpS class means (with names) |
| `{key}_run.log` | Timestamped log of the full run |
| `{key}_SKIPPED.txt` | Written if the basin had too few training pixels (< 50) |
| `input/BpS.clr`, `input/BpS.qml` | QGIS/ArcGIS symbology for the clipped BpS raster |

### Diagnostic plots (PNG)

`{key}_diag_histogram.png`, `{key}_diag_scatter.png`,
`{key}_diag_bps_boxplots.png`, `{key}_diag_map_panels.png`,
`{key}_diag_difference_map.png`, `{key}_diag_treatment_map.png`,
`{key}_diag_feather_map.png`, `{key}_diag_pct_change_map.png`.


## How the workflow operates

This section summarizes `etg_baseline_fill.py`.

1. **Read the ETg raster.** Its CRS, extent, resolution, and dimensions become the
   template grid that everything else aligns to.
2. **Rasterize the treatment shapefile.** Any polygon with `scale_fctr > 0` or
   `rplc_rt > 0` is treated. Treatment polygons are buffered outward (default 90 m)
   and burned into a binary treatment-zone mask. A per-pixel expert-adjustment raster
   is built from the basin-wide default plus any per-polygon overrides.
3. **Align BpS to the ETg grid** via nearest-neighbor resampling (categorical data).
4. **Build the basin boundary mask.** The training boundary is resolved in order:
   `boundary_shp` from the config, then the matching NWI polygon, then the dissolved
   extent of the treatment shapefile. This constrains training pixels to within the
   basin. The last option assumes the ET units tile the basin; when they don't, the
   run warns that the derived boundary covers only a small share of the ETg extent.
5. **Assemble training data and per-BpS means.** Training pixels are those outside
   treatment zones, within the basin, with a valid BpS class and ETg > 0. The mean
   ETg of each BpS class is recorded (with within-class standard deviation and
   count). If fewer than 50 valid pixels remain, the basin is gracefully skipped.
6. **Predict the baseline.** For each BpS class, a Gaussian-windowed local mean of
   that class's training pixels gives the spatially varying baseline (or a flat
   class mean if `spatial_weight_radius_px = 0`), clamped at zero.
7. **Fill treatment zones and feather edges.** Treatment pixels receive the baseline
   scaled by the expert adjustment factor, capped so it never exceeds the original
   input ETg. Gaussian feathering blends the transition just outside the boundary,
   with an irrigation-pull guard so the feather can only pull edges down toward
   natural values. A per-pixel percent-change raster and figure are produced.
8. **Write summaries.** A per-polygon summary CSV, run metadata, and the per-basin
   log are written. `etunit_summary.py` produces the ET-unit-level area / volume /
   rate table.


## Known considerations

### BpS class coverage

If a BpS class appears only inside treatment zones and never outside, the model has
no direct training data for it and falls back to the basin-wide or global mean. The
diagnostic box-plots help identify this situation.

### Buffer distance

Irrigation effects (lateral wetting, spray drift) extend beyond strict field
boundaries. The `buffer_m` parameter excludes these edge pixels from training.
Increase it for areas with flood irrigation or wide influence zones.

### Spatial weighting radius

The default ~1 km window balances spatial detail against having enough training
pixels of each class in every window. In basins where a vegetation class is sparse,
a larger radius gives more stable local means; a radius of 0 falls back to a single
basin-wide value per class.

### Small basins

Basins with fewer than 50 valid training pixels (after excluding treatment zones and
out-of-basin areas) are automatically skipped, with a `_SKIPPED.txt` marker.

### Training boundary on custom basins

For a custom basin with no `boundary_shp`, the training boundary comes from the
treatment shapefile. That is only equivalent to a basin outline when the ET units
tile the basin. Running Pine Valley both ways makes the difference concrete: via
the NWI polygon the model trains on 165,811 pixels and the treatment-zone volume
change is -43.4%; via the treatment shapefile alone (which covers about 2% of the
basin) it trains on 13,688 pixels and reports -31.7%. Watch the `valid training
pixels` line and the boundary-coverage warning in the log.


## References

Beamer, J.P., Huntington, J.L., Morton, C.G., and Pohll, G.M., 2013,
Estimation of annual groundwater evapotranspiration from phreatophyte vegetation in
the Great Basin using Landsat and flux tower measurements: Journal of the American
Water Resources Association, v. 49, no. 3, p. 518-533,
[doi:10.1111/jawr.12058](https://doi.org/10.1111/jawr.12058).

Minor, B.A., 2019, Estimating annual groundwater evapotranspiration from hydrographic
areas in the Great Basin using remote sensing and evapotranspiration data measured by
flux tower systems: University of Nevada, Reno, unpublished master's thesis.

Huntington, J.L., Bromley, M., and others, 2022, Groundwater discharge from
phreatophyte vegetation, Humboldt River Basin, Nevada: Desert Research Institute,
Publication No. 41288,
[project page](https://www.dri.edu/project/humboldt-etg/).

Huntington, J.L. and Bromley, M., 2023, Remote sensing of evapotranspiration at the
NERT site and surrounding properties: prepared for Nevada Division of Environmental
Protection.
