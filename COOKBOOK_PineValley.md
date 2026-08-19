# Cookbook: running Pine Valley (053) end to end

A worked example with the actual console output beside every command, so you
can tell a correct run from a subtly wrong one. Pine Valley is the reference
basin: if it reproduces the numbers below, your install is good and you can
move on to other basins with confidence.

`WALKTHROUGH.md` is the general guide. This file is the same workflow with one
specific basin, real output, and a troubleshooting table.

Every number here comes from a verified run on 2026-07-29 against the Pine
Valley dataset described below. See [Reference numbers](#reference-numbers) for
what counts as a match.


## What you need before you start

| Item | Where it comes from |
|---|---|
| The repo | `git clone` |
| `LF2020_BPS_CONUS.tif` | https://landfire.gov, LANDFIRE 2020 Biophysical Settings, CONUS |
| `HA053_..._etg_adj_long_term_median_ft_1984_2025.tif` | Project deliverable. The BMM ETg raster for HA 053, ft/yr, 30 m, EPSG:32611 |
| `NV_phreats_MASTER_v11_PineValley_053_w_ag.shp` | Project deliverable. ET-unit polygons with `scale_fctr` and `rplc_rt` columns |

The last two are not in the repo and are not downloadable. Get them from the
NWI project data share.

The one-time CONUS clip in step 1 is the slow part: a few minutes, and the
LANDFIRE download is a couple of GB. It leaves a 96 MB `statewide/` folder.
Pine Valley itself then takes under a minute and 6 MB.


## Step 0. Environment check

```bash
conda env create -f environment.yml --solver=classic
conda activate bmm-etg-raster-fill

python -c "from osgeo import gdal; print(gdal.__version__)"
pytest -q
```

Expected: a GDAL version number, then

```
..............                                       [100%]
14 passed in 7.42s
```

Four of those checks confirm that `basins/_template/config.toml` and
`statewide/bps_lookup.json` are present and not gitignored. The
not-gitignored pair skips outside a git working tree.

If the `osgeo` import fails, run `conda install -c conda-forge gdal`.
Installing `rasterio` does not give you `osgeo`. Two things need it, and only
two:

- **Step 1.** Building `bps_lookup.json` reads the LANDFIRE attribute table
  through gdal. Without it the lookup comes out with no class names at all
  (`BpS 1073`) and a grey palette, and everything downstream inherits that.
  The repo ships a good `bps_lookup.json`, so this only bites if you rebuild it.
- **Step 2.** Embedding the colour table inside `BpS.tif`. Without it you load
  `BpS.qml` by hand in QGIS, which takes one click.

Everything else, including the LANDFIRE class names in the fill log, reads from
the cached `bps_lookup.json` and works fine without gdal.

**Checkpoint.** `pytest` passes and the gdal version prints.


## Step 1. Statewide BpS (one time for all basins)

```bash
python prep_statewide.py --bps C:\path\to\LF2020_BPS_CONUS.tif
```

Expected, abridged:

```
[10:12:03] Loading NWI investigation boundaries ...
[10:12:03]   257 basin polygons loaded
[10:12:03]   NWI shapefile CRS: EPSG:32611
[10:12:08]   Dissolved + 10000 m buffer ready
[10:12:08]   Output CRS for statewide BpS: EPSG:32611
[10:12:08] Clipping BpS ...
[10:12:54]     -> BpS_statewide.tif  (100.4 MB)
[10:12:54]   Extracting BpS class lookup (names + colours) ...
[10:13:21]     1749 BpS classes extracted -> statewide/bps_lookup.json
```

Takes a few minutes against the real CONUS file. Skip this step entirely if
`statewide/BpS_statewide.tif` already exists.

**Checkpoint.** `statewide/` holds `BpS_statewide.tif` (about 100 MB) and
`bps_lookup.json`. Open the JSON and confirm the names are real:

```json
"1073": [225, 225, 225, "Inter-Mountain Basins Greasewood Flat"]
```

If you see `"BpS 1073"` instead of the name, gdal was missing when this ran.
Fix step 0 and re-run with the file deleted.


## Step 2. Prep the basin

Find the key first if you don't know it:

```bash
python prep_basin.py --list
```

```
257 basins in NWI_Investigations_EPSG_32611.shp:

  001_PuebloValley                          (Pueblo Valley)
  002_ContinentalLakeValley                 (Continental Lake Valley)
  ...
  053_PineValley                            (Pine Valley)
```

Then:

```bash
python prep_basin.py 053_PineValley
```

```
[18:04:04] Preparing basin: 053_PineValley
[18:04:04]   Clipping BpS ...
[18:04:08]     -> BpS.tif  (1.6 MB)
[18:04:08]     -> BpS.tif color table + RAT embedded; BpS.clr + BpS.qml sidecars written
[18:04:08]   -> config.toml generated from basins/_template/config.toml (review & edit before running fill)
[18:04:08]   Done.  Place raw ETg raster and treatment shapefile in:
    ...\basins\053_PineValley\source\
```

**Checkpoint.** You now have:

```
basins/053_PineValley/
    config.toml
    input/          BpS.clr  BpS.qml  BpS.tif    (1.6 MB)
    output/         (empty)
    source/         (empty)
```

`config.toml` still carries two placeholders at this point. That is expected.


## Step 3. Place the data, then re-run prep

Copy both files, including every shapefile sidecar (`.shx`, `.dbf`, `.prj`,
`.cpg`), into `basins\053_PineValley\source\`:

```
HA053_NV_phreats_MASTER_v11_PineValley_053_w_ag_etg_adj_long_term_median_ft_1984_2025.tif
NV_phreats_MASTER_v11_PineValley_053_w_ag.shp   (+ .shx .dbf .prj .cpg)
```

Then run the exact same prep command again:

```bash
python prep_basin.py 053_PineValley
```

```
[18:04:09]     -> BpS.tif already present (1.6 MB) - skipping (pass --force to rebuild)
[18:04:09]   config.toml already exists - filled in etg_tif, treatment_shp (your other edits are untouched)
```

That second line is the point of re-running. It fills the two placeholders and
leaves every other value alone.

**Checkpoint.** `basins/053_PineValley/config.toml` now reads:

```toml
[source]
etg_tif       = "HA053_NV_phreats_MASTER_v11_PineValley_053_w_ag_etg_adj_long_term_median_ft_1984_2025.tif"
treatment_shp = "NV_phreats_MASTER_v11_PineValley_053_w_ag.shp"
```

If either still says `# PLACE ...`, the file is not where prep looked, or its
name does not match the patterns prep searches for (`*etg*median*.tif` /
`*ETg*.tif` for the raster; a stem containing `etunit`, `et_unit`, `phreats`,
`treatment`, `w_ag`, or `master` for the shapefile). Type the filename in by
hand.


## Step 4. Check the config

Open `basins/053_PineValley/config.toml`. For a first Pine Valley run, leave
every parameter at its default:

```toml
[treatment]
buffer_m         = 90.0
feather_width_px = 4

[adjustment]
baseline_adjust = 1.0

[baseline]
spatial_weight_radius_px = 33
```

`spatial_weight_radius_px` is the one scientific knob worth understanding
before you touch it: 33 px is about 1 km at 30 m, and 0 gives a single flat
ETg value per BpS class across the whole basin.


## Step 5. Run the fill

```bash
python etg_baseline_fill.py 053_PineValley
```

The console output. The same run is also written to
`basins/053_PineValley/output/053_PineValley_run.log`, with full timestamps
(`2026-07-29 18:04:10  1 . Reading ETg raster ...`) and starting one line
later, at step 1:

```
[17:52:57] === Study area: 053_PineValley ===
[17:52:57] 1 . Reading ETg raster (template grid) ...
[17:52:57]     shape=(2853, 970)  CRS=EPSG:32611  valid px=213,442
[17:52:57] 2 . Rasterizing treatment zones ...
[17:52:57]     polygons:  100 treatment  |  52 untouched
[17:52:57]     buffering treatment polygons by 90.0 CRS-units
[17:52:57]    2b . Per-polygon adjustment column 'adj_fctr' not found in shapefile - using basin-wide default (1.0)
[17:52:57]         To tune single polygons, edit the 'adj_fctr' column in 053_PineValley_rates_adjust.shp (written to the treatment shapefile's folder at the end of this run; 0 = no override, 0.8 = cut that polygon's baseline 20%) and re-run.
[17:52:57]   -> wrote treatment_zone.tif  (970x2853)
[17:52:57]     treatment-zone pixels: 49,592
[17:52:57]    2d . Building training ETg (NaN-ing all treatment pixels) ...
[17:52:57]     masked 49,592 treatment-zone pixels as NaN
[17:52:57] 3 . Matching BpS to ETg grid ...
[17:52:57]   -> matched BpS.tif -> BpS_matched.tif
[17:52:57]   4 . Rasterizing basin boundary (NWI) for training mask ...
[17:52:57]     basin boundary pixels: 2,138,982
[17:52:57] 5 . Assembling training data ...
[17:52:57]     basin boundary filter: 165,828 -> 165,811 (17 out-of-basin pixels excluded)
[17:52:57]     valid training pixels: 165,811
[17:52:57]    5a . Computing per-BpS mean ETg ...
[17:52:57]     BpS classes in training data: 15
[17:52:57]       Rocky Mountain Aspen Forest and Woodland            code=1048    mean=1.4787 ft  std=0.3885  n=35
[17:52:57]       Inter-Mountain Basins Semi-Desert Grassland         code=1071    mean=0.9935 ft  std=0.2219  n=13
[17:52:57]       Inter-Mountain Basins Montane Sagebrush Steppe      code=1069    mean=0.9293 ft  std=0.3577  n=61
[17:52:57]       Open Water                                          code=11      mean=0.8942 ft  std=0.4261  n=26
[17:52:57]       Inter-Mountain Basins Montane Riparian Systems      code=1074    mean=0.8132 ft  std=0.3924  n=12,398
[17:52:57]       Great Basin Pinyon-Juniper Woodland                 code=1050    mean=0.7222 ft  std=0.1141  n=4
[17:52:57]       Great Basin Xeric Mixed Sagebrush Shrubland         code=1060    mean=0.6941 ft  std=0.1789  n=2,808
[17:52:57]       Inter-Mountain Basins Semi-Desert Shrub-Steppe      code=1070    mean=0.6111 ft  std=0.1715  n=212
[17:52:57]       Inter-Mountain Basins Big Sagebrush Shrubland-Upland  code=2703    mean=0.5920 ft  std=0.1842  n=52,069
[17:52:57]       Inter-Mountain Basins Big Sagebrush Steppe          code=1068    mean=0.5282 ft  std=0.1490  n=25,116
[17:52:57]       Inter-Mountain Basins Mixed Salt Desert Scrub       code=1062    mean=0.5098 ft  std=0.1694  n=4,146
[17:52:57]       Inter-Mountain Basins Big Sagebrush Shrubland-Semi-Desert  code=2702    mean=0.5056 ft  std=0.1284  n=7,098
[17:52:57]       Inter-Mountain Basins Greasewood Flat               code=1073    mean=0.4992 ft  std=0.1499  n=58,918
[17:52:57]       Inter-Mountain Basins Sparsely Vegetated Systems    code=1045    mean=0.4028 ft  std=0.2087  n=1,762
[17:52:57]       Barren-Rock/Sand/Clay                               code=31      mean=0.2487 ft  std=0.0663  n=1,145
[17:52:57] 6 . Predicting baseline ETg (spatially weighted per-BpS mean) ...
[17:52:57]    6a . Spatially weighted BpS means (radius = 33 px ~ 990 m) ...
[17:53:04]     baseline BpS-mean range: 0.1509 - 1.9094 ft
[17:53:04]   -> wrote 053_PineValley_ETg_baseline_pred.tif  (970x2853)
[17:53:04] 7 . Building final ETg raster ...
[17:53:04]     downward-only cap applied to 6,052 pixels (baseline exceeded original input ETg)
[17:53:04]     treatment pixels filled with baseline: 49,592  /  49,592
[17:53:04]    7b . Gaussian feathering OUTSIDE treatment boundary (sigma=4 px, ~120 m) ...
[17:53:04]     irrigation-pull guard: 10,791 feather pixels had raw > baseline and were clipped in the blend
[17:53:04]     feather-band pixels (partial blend outside boundary): 48,111
[17:53:04]   -> wrote feather_weight.tif  (970x2853)
[17:53:04]     extent mask applied: 1,978 pixels outside original ETg extent set back to nodata
[17:53:04]   -> wrote 053_PineValley_ETg_final.tif  (970x2853)
[17:53:04]    7d . Computing per-pixel percent change (input -> final) ...
[17:53:04]   -> wrote 053_PineValley_ETg_pct_change.tif  (970x2853)
[17:53:04]     treatment-zone % change - mean: -35.8%  median: -37.6%  p10: -65.3%  p90: +0.0%
[17:53:06]   -> wrote diag_pct_change_map.png
[17:53:06]    7e . Writing run metadata ...
[17:53:06]   -> wrote 053_PineValley_run_metadata.txt
[17:53:06] 8 . Computing per-polygon summary ...
[17:53:06]     polygon_id = shapefile row number (no unique ID column found; add DRI_ID or UniqueID to label rows with your own IDs)
[17:53:08]   -> wrote 053_PineValley_polygon_summary.csv  (151 polygons)
[17:53:08] -- Summary -----------------------------------------
[17:53:08]   Outside treatment (training)              n= 165,828  mean=0.558  med=0.502  std=0.211
[17:53:08]   Treatment zones - original input          n=  47,614  mean=1.372  med=1.319  std=0.602
[17:53:08]   Treatment zones - model baseline          n=  49,592  mean=0.791  med=0.729  std=0.272
[17:53:08]   Treatment zones - final                   n=  47,614  mean=0.777  med=0.716  std=0.277
[17:53:08]   Total ETg volume change vs original input: -18.80%  (over 213,442 pixels valid in both rasters)
[17:53:08]   Treatment-zone ETg volume change:       -43.40%  (over 47,614 treatment pixels)
[17:53:08]   Elapsed: 11.1 s
[17:53:08] Done.  Outputs in:  /home/claude/repo/basins/053_PineValley/output
```

**Read this, don't just watch it scroll.** Four things tell you the run is sane:

1. **`valid training pixels: 165,811`.** Six figures for a basin this size. A
   few thousand means the training boundary is wrong.
2. **The class table is ordered sensibly.** Aspen and riparian at the top near
   1.5 and 0.8 ft, greasewood and sagebrush around 0.5, barren at the bottom
   at 0.25. If riparian came in below sagebrush, something is misaligned.
3. **Treatment-zone mean drops from 1.372 to 0.777 ft.** The irrigation signal
   is gone and what's left sits just above the 0.558 ft basin-wide natural
   mean, which is what you'd expect for ground that is wetter than average
   even without irrigation.
4. **Treatment-zone volume change is negative, -43.40%.** A positive number
   means the fill added water, which the downward-only cap should make
   impossible.

Watch for a class with a tiny `n`. `Great Basin Pinyon-Juniper Woodland` has
`n=4` training pixels here, so its 0.7222 ft mean carries no weight. That is
worth knowing but not worth fixing; the Gaussian window pulls from neighbours.

**Checkpoint.** `output/` now holds six rasters (`treatment_zone.tif`,
`BpS_matched.tif`, `feather_weight.tif`, and the three `053_PineValley_ETg_*`
files), `053_PineValley_polygon_summary.csv`, `053_PineValley_run.log`,
`053_PineValley_run_metadata.txt`, and one PNG.


## Step 6. Diagnostics

```bash
python diagnostics.py 053_PineValley
```

```
Study area: 053_PineValley
Loading rasters ...
Plotting histograms ...
  -> ...\output\053_PineValley_diag_histogram.png
Plotting scatter ...
  -> ...\output\053_PineValley_diag_scatter.png
Plotting BpS box-plots ...
  -> ...\output\053_PineValley_diag_bps_boxplots.png
Plotting map panels ...
  -> ...\output\053_PineValley_diag_map_panels.png
Plotting difference map ...
  -> ...\output\053_PineValley_diag_difference_map.png
Plotting treatment-zone map ...
  -> ...\output\053_PineValley_diag_treatment_map.png
Plotting feather weight map ...
  -> ...\output\053_PineValley_diag_feather_map.png

-- Distribution summary ------------------------------
  Outside treatment                    n= 165,828  mean=0.558  med=0.502  p10=0.376  p90=0.810
  Treatment zones - original           n=  47,614  mean=1.372  med=1.319  p10=0.607  p90=2.198
  Treatment zones - baseline pred      n=  49,592  mean=0.791  med=0.729  p10=0.499  p90=1.234
  Treatment zones - final              n=  47,614  mean=0.777  med=0.716  p10=0.486  p90=1.217
```

Seven PNGs. The eighth in the folder,
`053_PineValley_diag_pct_change_map.png`, came from step 5.

**Checkpoint.** Eight `*_diag_*.png` files in `output/`.


## Step 7. ET unit summary

```bash
python etunit_summary.py 053_PineValley
```

```
Study area: 053_PineValley
Reading ETg_final raster ...
  Pixel size: 30.0 x 30.0 m  ->  0.222395 ac
Reading treatment shapefile ...
Rasterizing ET units ...
  Found 4 ET units: ['Cropland', 'Meadow', 'Phreatophyte Shrubland', 'Riparian']
  ... one pixels= / area= / rate= / vol= line per unit ...

Wrote ...\output\053_PineValley_ETUNIT_SUMMARY.csv
  4 ET units + 1 totals row

-- Modeled ET Unit Summary --------------------------------------
  ET Unit                           Area (ac)   Vol (acft)  Rate (ft)       Low      High
  --------------------------------------------------------------------------------------
  Irrigated Cropland                  5682.63      4914.54     0.8648    0.5802    1.1494
  Meadow                              2462.36      1840.29     0.7474    0.4871    1.0077
  Phreatophyte Shrubland             36248.14     19892.83     0.5488    0.3593    0.7383
  Riparian                             779.27       683.57     0.8772    0.5771    1.1772
  TOTAL                              45172.40     27331.23
```

`Low` and `High` are the mean plus or minus one standard deviation of the
per-pixel ETg within each unit, floored at zero. They are a spread, not a
confidence interval.

**Checkpoint.** `053_PineValley_ETUNIT_SUMMARY.csv`, 4 units plus a totals row.
This table is the deliverable most people downstream actually want.


## Step 8. Look at it in QGIS

Load these four, in this order:

1. `output/053_PineValley_ETg_final.tif` (the product)
2. `output/053_PineValley_ETg_pct_change.tif` (styled diverging, centred on 0)
3. `input/BpS.tif` (should already carry LANDFIRE colours and names)
4. `source/NV_phreats_MASTER_v11_PineValley_053_w_ag.shp` (outlines)

Then check three things against the diagnostic PNGs:

- **`diag_map_panels.png`.** The filled fields should blend into the
  surrounding valley floor rather than reading as flat bright polygons.
- **`diag_bps_boxplots.png`.** Any class whose left box (outside treatment) is
  missing or thin exists mostly inside treatment, so its baseline came from
  the basin-wide or global mean. Note it; do not necessarily act on it.
- **`diag_feather_map.png`.** The 120 m blend collar around each polygon should
  look smooth. Hard rings mean `feather_width_px` is too small for the pixel
  size.

If a specific polygon's filled value is wrong on professional judgment, that is
what the expert adjustment is for. Add an `adj_fctr` column to the shapefile
(0.8 reduces that polygon's baseline by 20%) and re-run the fill, or set
`[adjustment] baseline_adjust` for the whole basin. Write down why.


## Where the rates are

Four files carry the modeled rates, at increasing aggregation:

| File | Granularity | The rate column |
|---|---|---|
| `{key}_ETg_baseline_pred.tif` | per pixel | the modeled natural rate everywhere in the basin |
| `{key}_ETg_final.tif` | per pixel | the deliverable: raw ETg with treatment zones replaced |
| `{key}_polygon_summary.csv` | per polygon | `mean_baseline_ETg` |
| `{key}_ETUNIT_SUMMARY.csv` | per ET unit | `ETg Rate (ft)`, with low and high |

`run_metadata.txt` holds the per-vegetation-class rates the whole thing is
built from, under `[bps_class_means]`. After a batch run,
`cross_basin_summary.csv` in the project root has one row per basin.

`mean_baseline_ETg` is the direct replacement for the old hand-picked
replacement rate. Where the treatment shapefile carries the legacy `rplc_rt`,
the summary also reports it plus the difference, so old and new sit side by
side:

```
polygon_id,n_pixels,treatment,adj_factor,mean_input_ETg,mean_baseline_ETg,mean_final_ETg,legacy_rplc_rt,baseline_minus_legacy,ET_unit
130,813,replaced,1.0,1.7806,0.8187,0.8187,1.5,-0.6813,cropland
```

On Pine Valley, 61 treated polygons carry a legacy rate. Basin totals agree
closely (legacy mean 0.821 ft/yr, modeled 0.814), but individual polygons
diverge by up to 0.68 ft/yr. The largest gaps are all polygons the analyst
assigned a flat 1.500; the model puts those eight between 0.82 and 1.07
according to the vegetation actually present. That is the uniform burn-in the tool exists to
replace, so a large negative `baseline_minus_legacy` on a flat-rate polygon is
the expected result, not a red flag. Sort by that column to find the polygons
worth a second look.


## Adjusting and scaling the ETg rates

One rule settles most confusion here:

> **The fill reads exactly one shapefile: whatever `[source] treatment_shp`
> names in that basin's `config.toml`.** That is the file you edit. Nothing
> else in `source/` is consulted.

For Pine Valley that line reads:

```toml
[source]
treatment_shp = "NV_phreats_MASTER_v11_PineValley_053_w_ag.shp"
```

Every run records the resolved path in `{key}_run_metadata.txt`, so you can
always confirm which file was actually used:

```
treatment_shp = ...\basins\053_PineValley\source\NV_phreats_MASTER_v11_PineValley_053_w_ag.shp
```

There are two ways to change the rates. Start with whichever matches the
scope of your disagreement.

### Option A: scale the whole basin (no shapefile editing)

Edit `config.toml`:

```toml
[adjustment]
baseline_adjust = 0.9        # every treated polygon's rate to 90%; 1.0 = no change
```

Re-run the fill. That is the entire procedure.

### Option B: adjust individual polygons

Every fill run writes `053_PineValley_rates_adjust.shp` into `source/`, next
to your treatment shapefile. It is the tuning surface: one polygon per feature,
this run's rates already attached, and an editable `adj_fctr` column already
there. No field creation, no edits to your master shapefile.

| Column | Meaning |
|---|---|
| `row_i`, `poly_id` | which polygon (matches `polygon_id` in the summary CSV) |
| `treated` | 1 = replaced by the fill, 0 = left as raw ETg |
| `etg_input`, `etg_base`, `etg_final` | this run's mean rates (ft/yr) |
| `lgcy_rt` | the analyst's legacy `rplc_rt`, for comparison |
| `adj_fctr` | **the column you edit** |

Open it in QGIS, style it by `etg_base` or `lgcy_rt`, and type overrides into
`adj_fctr`:

| `adj_fctr` | Effect on that polygon |
|---|---|
| `0` (the seeded value) | no override; the basin-wide `baseline_adjust` applies |
| `0.8` | cut that polygon's rate by 20% |
| `1.5` | raise it 50%, subject to the cap below |

Save, re-run the fill. Your edits round-trip: the next run reads `adj_fctr`
back from this file, applies it, and rewrites the file with refreshed rates
and your overrides intact. A per-polygon value beats `baseline_adjust`.

Two rules keep this unambiguous. If your treatment shapefile carries its own
`adj_fctr` column with values, that wins and the rates file is ignored as an
input (the log says so). And the rates file deliberately has no
`scale_fctr` / `rplc_rt` columns, so pointing `treatment_shp` at it by mistake
fails with a clear error instead of silently treating the wrong polygons.
It cannot change which polygons are treated, only their rates.

The old route still works too: add `adj_fctr` to the treatment shapefile
itself (rename via `[adjustment] attr_adjust`).

### Confirming it took

With no `adj_fctr` column present, the log says so and falls back:

```
   2b . Per-polygon adjustment column 'adj_fctr' not found in shapefile - using basin-wide default (1.0)
```

With one, you get the factors that were actually applied:

```
   2b . Rasterizing per-polygon adjustment factors (column 'adj_fctr') ...
    expert adjustment ACTIVE - basin default: 1.0
    adjustment factors in treatment zone - min: 0.500  max: 1.000  mean: 0.940
```

The `adj_factor` column in `{key}_polygon_summary.csv` then shows what each
polygon received.

### Two limits to know before you tune

**The downward-only cap cannot be overridden.** The adjusted rate can never
exceed the original input ETg. The cap is applied per pixel, after the
adjustment and before feathering. Setting `adj_fctr = 3.0` on three Pine Valley
cropland polygons tripled nothing: each pixel pinned at its own input value, so
the polygon mean rose toward but stayed under the input mean (polygon 14:
baseline 0.7551, tripled and capped to a mean of 1.7655 against an input of
1.8012). Capped pixels went from 6,052 to 9,776 and the basin figure moved from
-43.40% to -34.97%. A large `adj_fctr` is a blunt way of saying "barely change
this polygon"; if that is what you mean, use the next section instead.

**Adjustments are local.** `adj_fctr = 0.5` on three polygons moved exactly
those three, each landing at about half its previous value, and left the other
148 rows identical.

### Choosing which polygons get treated at all

A polygon is treated when `scale_fctr > 0` **or** `rplc_rt > 0`. Only the sign
matters.

> **The magnitude of `scale_fctr` and `rplc_rt` is ignored.** They are on/off
> triggers, nothing more. Multiplying both by ten across the whole Pine Valley
> shapefile left every raster, the log, the metadata and every modeled column
> identical, and the same -43.40%. This is the likeliest thing for someone
> coming from the legacy workflow to get wrong: `rplc_rt` used to be the value
> burned into the raster, and it no longer is. The fill value comes from the
> model, scaled only by `adj_fctr` and `baseline_adjust`. (The magnitude does
> still appear in the `legacy_rplc_rt` and `baseline_minus_legacy` review
> columns, which simply report it.)

To stop a polygon being replaced, set both columns to 0. It moves to the
`52 untouched` count and its interior keeps the raw ETg.

**An untouched polygon is not necessarily an unchanged one.** Feathering
reaches roughly 250 m outside each treated boundary, so a neighbour's collar
can still pull an untouched polygon's edge pixels down. In the Pine Valley run,
35 of the 51 `treatment = none` polygons have `mean_final_ETg` below
`mean_input_ETg` for exactly that reason (polygon 1: 0.9258 in, 0.7044 out).
Only the interior is guaranteed untouched. Set `feather_width_px = 0` if you
need a hard boundary.

You can also drive treatment off a different column entirely, with
`[treatment] attr_scale` and `attr_replace`. That is what the optional
auto-flag workflow below uses.

### When the problem is the model, not one polygon

If you find yourself adjusting many polygons the same way, change the baseline
instead. All of these live in `config.toml`.

| Setting | Default | When to change it |
|---|---|---|
| `[baseline] spatial_weight_radius_px` | `33` (about 1 km) | Raise it where a vegetation class is sparse and local means are noisy. `0` collapses to one flat rate per class, the most conservative and most explainable option |
| `[treatment] buffer_m` | `90.0` | Raise it where flood irrigation wets ground well beyond the field edge, so those pixels stop polluting the training set |
| `[treatment] feather_width_px` | `4` (about 120 m) | Raise it if the blend collar looks abrupt in `diag_feather_map.png`; `0` disables feathering |
| `[source] boundary_shp` | unset | Set it when the training boundary is wrong, which the fill warns about on custom basins |
| `[crs_overrides]` | empty | A raster whose stored CRS is malformed |

These change the baseline everywhere, including polygons you were happy with,
so re-check the whole basin afterward rather than just the one that prompted
the change.

### Recording what you did

`{key}_run_metadata.txt` captures every parameter used, including
`baseline_adjust`, `adjustment_active`, `per_polygon_overrides`, `buffer_m`,
and `spatial_weight_radius_px`, so a run is self-documenting as to *what* was
set. It cannot record *why*. Put that in a note in the basin folder or a commit
message. It is the difference between a defensible number and an unexplained
one.


## Optional. Auto-flag instead of hand-picking polygons

Use this only when you do not already have `scale_fctr` / `rplc_rt` filled in
and want a first pass to react to rather than a blank slate. If an analyst has
already set those columns, skip this section: you never need it, and skipping
it means there is only ever one shapefile in play.

**This is the step that creates a second shapefile.** It writes a copy,
`<your treatment shapefile>_autoflag.shp`, into the same `source/` folder,
leaving your original untouched. Two things follow from that:

- Nothing uses the copy until you point `[source] treatment_shp` at it.
- Keep `treatment_shp` on your **original** while you are iterating on flags.
  If you point it at the copy and re-run the flagger, you get
  `..._autoflag_autoflag.shp` and the sticky-override logic looks in the wrong
  place. Switch `treatment_shp` to the copy only when you run the fill.

The copy is also seeded with a `UniqueID` column if your source lacks one, so
summary rows trace back to features. Rate tuning is not done here: that
happens in `053_PineValley_rates_adjust.shp` (Option B above), regardless of
whether you use the auto-flagger.

```bash
python flag_irrigated.py 053_PineValley
```

Abridged; the per-BpS-class table between the CSV writes and the summary is
dropped here:

```
[18:04:36] === Auto-flag: 053_PineValley ===
[18:04:36]     rule: mean ETg >= 1.5x baseline AND >= 0.3 ft/yr above it; baseline = per-BpS p50 over in-basin pixels
[18:04:36]     basin boundary pixels (NWI): 2,138,982
[18:04:36]     valid in-basin pixels: 213,425   BpS classes: 15   global baseline p50: 0.546 ft
[18:04:38]   -> wrote NV_phreats_MASTER_v11_PineValley_053_w_ag_autoflag.shp  (152 polygons)
[18:04:38]   -> wrote 053_PineValley_autoflag_report.csv
[18:04:38]   -> wrote 053_PineValley_autoflag_class_summary.csv
...
[18:04:38]   polygons total          : 152
[18:04:38]   auto-detected (new)     : 8
[18:04:38]   carried existing manual : 100
[18:04:38]   analyst overrides kept  : 0
[18:04:38]   FLAGGED for treatment   : 108  (autoflag = 1)
[18:04:38]   WARNING: BpS 11 (Open Water) has 86% of its in-basin area inside flagged polygons - its p50
           baseline may be irrigation-inflated and cause under-flagging.
[18:04:38]   WARNING: BpS 1074 (Inter-Mountain Basins Montane Riparian Systems) has 57% ...
```

Note where things land: the shapefile goes to **`source/`**, next to the
original. The two CSVs go to `output/`.

Both warnings are expected on Pine Valley and are worth understanding. When
most of a class sits inside flagged polygons, its median is pulled up by the
irrigated pixels, so the screen is comparing against an inflated baseline and
under-flags that class. If you care about riparian specifically, re-run with
`--pctl 35 --reset`.

Review the `autoflag` column in QGIS, set it to 0 or 1 where you disagree, and
re-run. Your edits stick, because the script tracks its own raw suggestion
separately in `autoflag_a`.

To run the fill on the flags, either set in `config.toml`:

```toml
[source]
treatment_shp = "NV_phreats_MASTER_v11_PineValley_053_w_ag_autoflag.shp"

[treatment]
attr_replace = "autoflag"
```

or re-run with `--mirror-to rplc_rt`, which copies the decision into the
standard trigger column so you only need the `treatment_shp` line, not the
`attr_replace` one. Either way you must point `treatment_shp` at the
`_autoflag.shp` copy: the script never modifies your original shapefile.


## Reference numbers

Verified 2026-07-29 against the inputs named at the top, all parameters at
their defaults.

| Quantity | Expected |
|---|---|
| Grid | 2853 x 970, EPSG:32611, 30 m |
| Valid ETg pixels | 213,442 |
| Treatment polygons | 100 treated, 52 untouched |
| Treatment-zone pixels (after 90 m buffer) | 49,592 |
| NWI basin boundary pixels | 2,138,982 |
| Valid training pixels | 165,811 |
| BpS classes in training | 15 |
| Baseline range | 0.1509 to 1.9094 ft |
| Downward-only cap applied | 6,052 px |
| Treatment mean, original to final | 1.372 to 0.777 ft |
| Treatment-zone volume change | -43.40% |
| Basin-wide volume change | -18.80% |
| Total area / volume | 45,172.40 ac / 27,331.23 ac-ft |
| Runtime, fill only | 10 to 15 s |
| `output/` size | about 5.6 MB |

**Tolerance.** Differences in the last decimal place are floating-point noise
and fine. Differences of a few percent mean the inputs or parameters changed,
so check `run_metadata.txt`, which records every parameter used. A difference
of more than about tenfold in training pixels, or a sign flip on the volume
change, means something is actually wrong: work through the table below.


## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: config template not found at basins/_template/config.toml` | The template is missing from your clone. It was untracked before v1.0.1. | Pull the latest `main`, or copy `basins/_template/config.toml` from a colleague. |
| `ModuleNotFoundError: No module named 'osgeo'` | `gdal` bindings missing. `rasterio` does not supply them. | `conda install -c conda-forge gdal`. Only step 1 and the `BpS.tif` colour embed need it. |
| Class names print as `BpS 1073` throughout | `bps_lookup.json` was built without gdal, so it has no names in it. | Install gdal, delete `statewide/bps_lookup.json`, re-run `prep_statewide.py`. Or take the copy tracked in the repo. |
| `ERROR: Missing required inputs ... ETG_TIF, TREATMENT_SHP` | `config.toml` still holds `# PLACE ...` placeholders. | Put the files in `source/`, re-run `prep_basin.py 053_PineValley`, or type the filenames into `config.toml`. |
| `WARNING: that boundary covers only 22% of the valid ETg extent` | Custom basins only. The training boundary came from the treatment shapefile, which does not tile the basin. | Set `boundary_shp` in `config.toml` to a real basin outline, or re-prep with `--boundary`. |
| `valid training pixels` in the hundreds or low thousands | Same cause as above, or a CRS mismatch between the ETg raster and the boundary. | Check step 4 of the log for which boundary was used and how many pixels it covered. |
| `ERROR: attribute 'scale_fctr' not found` | The shapefile lacks the trigger columns. | Add `scale_fctr` and `rplc_rt`, or point `attr_replace` at the column you do have. |
| `053_PineValley_SKIPPED.txt` appears | Fewer than 50 training pixels survived. | Almost always a boundary or CRS problem, not a genuinely small basin. |
| Treatment-zone volume change is positive | The fill added ETg. The downward-only cap and the feather clip both run after the expert adjustment, so this should not be reachable. | Do not use the output. Check `run_metadata.txt` against the reference numbers and report it. |
| BpS colours don't load in QGIS | The `.tif` had no embedded colour table (no gdal at prep time). | Layer Properties, Symbology, Load Style, pick `input/BpS.qml`. |
| `UnicodeEncodeError: 'charmap' codec can't encode character` on Windows | A non-ASCII character reached stdout. Windows uses cp1252, not UTF-8, whenever output is redirected or captured, so this hits `pytest` and `python ... > log.txt` but not the interactive console. | Fixed in v1.0.2; the source is now pure ASCII and `pytest` guards it. If you see it in your own edit, replace the character with an ASCII equivalent. |
| `DeprecationWarning: Setting the shape on a NumPy array ... NumPy 2.5` | Raised from inside `rasterio` on `src.read()`, not from this code. | Harmless today. Update `rasterio`, or pin `numpy<2.5`, before it becomes an error in a later NumPy. |
| Re-running prep did not re-clip `BpS.tif` | Existing files are preserved by design. | Pass `--force`. |


## Doing this for another basin

Everything above except step 1, with the key swapped:

```bash
python prep_basin.py 042_MarysRiverArea
# drop the two files into basins/042_MarysRiverArea/source/
python prep_basin.py 042_MarysRiverArea
python etg_baseline_fill.py 042_MarysRiverArea
python diagnostics.py 042_MarysRiverArea
python etunit_summary.py 042_MarysRiverArea
```

Once several basins are staged, `python run_all.py` does prep, fill,
diagnostics, and summary for all of them and writes `cross_basin_summary.csv`
in the project root. Check readiness first with `python run_all.py --list`.

For study areas outside the NWI framework, see the custom-basin section of
`WALKTHROUGH.md`, and read the boundary-coverage caveat there before you rely
on the result.
