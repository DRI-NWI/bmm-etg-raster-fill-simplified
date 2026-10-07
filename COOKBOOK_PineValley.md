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
| `HA053_..._etg_adj_long_term_median_ft_1984_2025.tif` | Ships with the repo in `basins/053_PineValley/source/`. The BMM ETg raster for HA 053, ft/yr, 30 m, EPSG:32611 |
| `NV_phreats_MASTER_v11_PineValley_053_w_ag.shp` | Ships with the repo in the same folder. ET-unit polygons with `scale_fctr` and `rplc_rt` columns |

The LANDFIRE raster is the only download. The Pine Valley data is in the repo
so the cookbook runs straight after cloning.

The one-time CONUS clip in step 1 is the slow part: a few minutes, and the
LANDFIRE download is a couple of GB. It leaves a 96 MB `statewide/` folder.
Pine Valley itself then takes under a minute and 6 MB.


## Step 0. Environment check

> **Which window to type in.** On Windows, open the **Anaconda Prompt** (or
> Miniforge Prompt) from the Start menu. On a Mac, open **Terminal**. Every
> command in this guide is typed the same way in both. Type one line at a
> time and press Enter. Example paths are shown in Windows form
> (`C:\path\to\file.tif`); on a Mac, use your own path instead
> (`/Users/you/Downloads/file.tif`).

```
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

```
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

```
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

```
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

Ignore that last line for Pine Valley: the two files are already in `source/`
because they ship with the repo, and prep found them.

**Checkpoint.** You now have:

```
basins/053_PineValley/
    config.toml
    input/          BpS.clr  BpS.qml  BpS.tif    (1.6 MB)
    output/         (empty)
    source/         HA053_..._etg_adj_long_term_median_ft_1984_2025.tif
                    NV_phreats_MASTER_v11_PineValley_053_w_ag.shp  (+ .shx .dbf .prj .cpg)
```

and `basins/053_PineValley/config.toml` reads:

```toml
[source]
etg_tif       = "HA053_NV_phreats_MASTER_v11_PineValley_053_w_ag_etg_adj_long_term_median_ft_1984_2025.tif"
treatment_shp = "NV_phreats_MASTER_v11_PineValley_053_w_ag.shp"
```

If either says `# PLACE ...` instead, the `source/` folder did not come through
the clone. Check that `.gitignore` was not edited and that the six files listed
above are present.


## Step 3. Placing your own data (skip for Pine Valley)

This is what Step 2 looks like for a basin whose data does not ship with the
repo. Read it now so the two-pass flow makes sense later; nothing to do for the
reference run.

The first `prep_basin.py` run on an empty basin writes `config.toml` with two
placeholders, `# PLACE ETg RASTER HERE` and `# PLACE TREATMENT SHP HERE`. Copy
the ETg raster and the treatment shapefile, including every sidecar (`.shx`,
`.dbf`, `.prj`, `.cpg`), into `basins\<basin_key>\source\`, then run the
exact same prep command again:

```
python prep_basin.py <basin_key>
```

```
[18:04:09]     -> BpS.tif already present (1.6 MB) - skipping (pass --force to rebuild)
[18:04:09]   config.toml already exists - filled in etg_tif, treatment_shp (your other edits are untouched)
```

That second line is the point of re-running. It fills the two placeholders and
leaves every other value alone.

If either placeholder is still there afterward, the file is not where prep
looked, or its name does not match the patterns prep searches for
(`*etg*median*.tif` / `*ETg*.tif` for the raster; a stem containing `etunit`,
`et_unit`, `phreats`, `treatment`, `w_ag`, or `master` for the shapefile). Type
the filename in by hand.


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


## Step 4b (optional). Auto-flag the polygons that need treatment

The Pine Valley shapefile already has `scale_fctr` and `rplc_rt` filled in by
an analyst, so for the reference run **skip this step** and go to Step 5. Come
back to it when you have a basin where nobody has picked the polygons yet, or
you want a machine first pass to check the hand-picked set against.

`flag_irrigated.py` compares each polygon's mean ETg against what its BpS
classes would produce without irrigation, and flags the ones that stand out.
The rule, from `[flag]` in `config.toml`: mean ETg at least 1.5x the class
baseline **and** at least 0.3 ft/yr above it.

```
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
[18:04:38]   suggested by thresholds : 7
[18:04:38]   already flagged by hand : 110
[18:04:38]   decided by analyst col  : 0
[18:04:38]   FLAGGED for treatment   : 117  (autoflag = 1)
[18:04:38]   WARNING: BpS 11 (Open Water) has 86% of its in-basin area inside flagged polygons - its p50
           baseline may be irrigation-inflated and cause under-flagging.
[18:04:38]   WARNING: BpS 1074 (Inter-Mountain Basins Montane Riparian Systems) has 58% ...
```

**Checkpoint.** A new shapefile,
`NV_phreats_MASTER_v11_PineValley_053_w_ag_autoflag.shp`, sits in `source/`
next to your original, which is untouched. The two CSVs are in `output/`. On
Pine Valley the flagger carries the 110 existing hand picks (100 via
`scale_fctr` / `rplc_rt`, 10 via `bsnAv_flag`) and suggests 7 more.

Both warnings are expected on Pine Valley. When most of a class sits inside
flagged polygons, its median is pulled up by the irrigated pixels, so the
screen is comparing against an inflated baseline and under-flags that class.
If you care about riparian specifically, re-run with `--pctl 35 --reset`.

**Review the flags.** Open the `_autoflag.shp` copy in QGIS. Three columns
matter: `suggested` is the machine's call (1 = treat), `analyst` is yours, and
`autoflag` is the result the fill will use. Type 0 or 1 into `analyst` where you
disagree (leave it at -1 to go with the suggestion) and re-run the command
above. `analyst` is carried over as typed; `suggested` and `autoflag` are
recomputed, so do not edit those. Pass `--reset` to clear `analyst` and start
over. The per-polygon diagnostics (`etg_ratio`, `etg_excs`, `bps_base`)
explain each suggestion.

**Point the fill at the flags.** Nothing uses the copy until you tell the fill
about it. Edit `config.toml`:

```toml
[source]
treatment_shp = "NV_phreats_MASTER_v11_PineValley_053_w_ag_autoflag.shp"

[treatment]
attr_treat = ["scale_fctr", "rplc_rt", "autoflag"]
```

Or run `python flag_irrigated.py 053_PineValley --mirror-to rplc_rt`, which
copies the decision into the standard `rplc_rt` trigger column so you only need
the `treatment_shp` line. Either way, `treatment_shp` must point at the
`_autoflag.shp` copy.

Two things to keep straight:

- Keep `treatment_shp` on your **original** while you are still iterating on
  flags. If it points at the copy and you re-run the flagger, you get
  `..._autoflag_autoflag.shp` and the `analyst` column is read from the wrong
  file.
  Switch to the copy only when you are ready to run the fill.
- Flagging decides **which** polygons are filled. It does not decide the fill
  value. Rate tuning happens after the fill, in
  `053_PineValley_rates_adjust.shp` (see [Adjusting and scaling the ETg
  rates](#adjusting-and-scaling-the-etg-rates)).

The copy is also seeded with a `UniqueID` column if your source lacks one, so
summary rows trace back to features.

If you ran this step on Pine Valley and pointed the fill at the flags, the
reference numbers in Step 5 onward will not match, because 8 extra polygons are
treated. Put `treatment_shp` back on the original for the reference run.


## Step 5. Run the fill

```
python etg_baseline_fill.py 053_PineValley
```

The console output. The same run is also written to
`basins/053_PineValley/output/053_PineValley_run.log`, with full timestamps
(`2026-07-29 18:04:10  1 . Reading ETg raster ...`) and starting one line
later, at step 1:

```
[15:43:13] === Study area: 053_PineValley ===
[15:43:13] 1 . Reading ETg raster (template grid) ...
[15:43:14]     shape=(2853, 970)  CRS=EPSG:32611  valid px=213,442
[15:43:14] 2 . Rasterizing treatment zones ...
[15:43:14]     polygons:  110 treatment  |  42 untouched
[15:43:14]       baseline fill (scale_fctr, rplc_rt): 100
[15:43:14]       basin average ('bsnAv_flag'): 10
[15:43:14]       fixed rate ('fixed_rt'): 0   (column absent)
[15:43:14]     buffering baseline / basin-average polygons by 90.0 CRS-units
[15:43:14]    2c . Per-polygon adjustment column 'adj_fctr' not found in shapefile - using basin-wide default (1.0)
[15:43:14]         To tune single polygons, edit the 'adj_fctr' column in 053_PineValley_rates_adjust.shp (written to the treatment shapefile's folder at the end of this run; 0 = no override, 0.8 = cut that polygon's baseline 20%) and re-run.
[15:43:14]   -> wrote treatment_zone.tif  (970x2853)
[15:43:14]     treatment-zone pixels: 52,616  (baseline 49,333, basin-average 3,283, fixed 0)
[15:43:14]    2d . Building training ETg (NaN-ing all treatment pixels) ...
[15:43:14]     masked 52,616 treatment-zone pixels as NaN
[15:43:14] 3 . Matching BpS to ETg grid ...
[15:43:14]   -> matched BpS.tif -> BpS_matched.tif
[15:43:14]   4 . Rasterizing basin boundary (NWI) for training mask ...
[15:43:14]     basin boundary pixels: 2,138,982
[15:43:14] 5 . Assembling training data ...
[15:43:14]     basin boundary filter: 163,015 -> 162,998 (17 out-of-basin pixels excluded)
[15:43:14]     valid training pixels: 162,998
[15:43:14]    5a . Computing per-BpS mean ETg ...
[15:43:14]     BpS classes in training data: 15
[15:43:14]       Rocky Mountain Aspen Forest and Woodland            code=1048    mean=1.4787 ft  std=0.3885  n=35
[15:43:14]       Inter-Mountain Basins Semi-Desert Grassland         code=1071    mean=0.9935 ft  std=0.2219  n=13
[15:43:14]       Inter-Mountain Basins Montane Sagebrush Steppe      code=1069    mean=0.9293 ft  std=0.3577  n=61
[15:43:14]       Open Water                                          code=11      mean=0.8942 ft  std=0.4261  n=26
[15:43:14]       Inter-Mountain Basins Montane Riparian Systems      code=1074    mean=0.8075 ft  std=0.3987  n=11,844
[15:43:14]       Great Basin Xeric Mixed Sagebrush Shrubland         code=1060    mean=0.6941 ft  std=0.1789  n=2,808
[15:43:14]       Great Basin Pinyon-Juniper Woodland                 code=1050    mean=0.6764 ft  std=0.0948  n=3
[15:43:14]       Inter-Mountain Basins Big Sagebrush Shrubland-Upland  code=2703    mean=0.5908 ft  std=0.1836  n=51,579
[15:43:14]       Inter-Mountain Basins Semi-Desert Shrub-Steppe      code=1070    mean=0.5834 ft  std=0.1609  n=186
[15:43:14]       Inter-Mountain Basins Big Sagebrush Steppe          code=1068    mean=0.5270 ft  std=0.1485  n=24,762
[15:43:14]       Inter-Mountain Basins Mixed Salt Desert Scrub       code=1062    mean=0.5086 ft  std=0.1684  n=4,127
[15:43:14]       Inter-Mountain Basins Big Sagebrush Shrubland-Semi-Desert  code=2702    mean=0.5056 ft  std=0.1284  n=7,098
[15:43:14]       Inter-Mountain Basins Greasewood Flat               code=1073    mean=0.4924 ft  std=0.1420  n=57,551
[15:43:14]       Inter-Mountain Basins Sparsely Vegetated Systems    code=1045    mean=0.4026 ft  std=0.2085  n=1,761
[15:43:14]       Barren-Rock/Sand/Clay                               code=31      mean=0.2486 ft  std=0.0662  n=1,144
[15:43:14] 6 . Predicting baseline ETg (spatially weighted per-BpS mean) ...
[15:43:14]    6a . Spatially weighted BpS means (radius = 33 px ~ 990 m) ...
[15:43:20]     baseline BpS-mean range: 0.1509 - 1.9094 ft
[15:43:20]    6b . Basin-average fill: 3,283 pixels set to the training mean 0.5541 ft
[15:43:20]   -> wrote 053_PineValley_ETg_baseline_pred.tif  (970x2853)
[15:43:20] 7 . Building final ETg raster ...
[15:43:20]     downward-only cap applied to 6,444 pixels (baseline exceeded original input ETg)
[15:43:20]     treatment pixels filled with baseline: 52,616  /  52,616
[15:43:20]    7b . Gaussian feathering OUTSIDE treatment boundary (sigma=4 px, ~120 m) ...
[15:43:20]     irrigation-pull guard: 11,124 feather pixels had raw > baseline and were clipped in the blend
[15:43:20]     feather-band pixels (partial blend outside boundary): 50,527
[15:43:20]   -> wrote feather_weight.tif  (970x2853)
[15:43:20]     extent mask applied: 2,189 pixels outside original ETg extent set back to nodata
[15:43:20]   -> wrote 053_PineValley_ETg_final.tif  (970x2853)
[15:43:20]    7d . Computing per-pixel percent change (input -> final) ...
[15:43:20]   -> wrote 053_PineValley_ETg_pct_change.tif  (970x2853)
[15:43:20]     treatment-zone % change - mean: -35.3%  median: -36.8%  p10: -65.2%  p90: +0.0%
[15:43:21]   -> wrote diag_pct_change_map.png
[15:43:21]    7e . Writing run metadata ...
[15:43:21]   -> wrote 053_PineValley_run_metadata.txt
[15:43:21] 8 . Computing per-polygon summary ...
[15:43:21]     polygon_id = shapefile row number (no unique ID column found; add DRI_ID or UniqueID to label rows with your own IDs)
[15:43:22]   -> wrote 053_PineValley_polygon_summary.csv  (151 polygons)
[15:43:22]   -> wrote 053_PineValley_rates_adjust.shp  (151 polygons, 0 adj_fctr and 0 fixed_rt override(s) carried forward)
[15:43:22]      To tune rates: edit 'adj_fctr' (0 = no override, 0.8 = cut that polygon 20%) or 'fixed_rt' (ft/yr to burn in as-is) in that file in QGIS, then re-run.
[15:43:22] -- Summary -----------------------------------------
[15:43:23]   Outside treatment (training)              n= 163,015  mean=0.554  med=0.499  std=0.209
[15:43:23]   Treatment zones - original input          n=  50,427  mean=1.339  med=1.247  std=0.603
[15:43:23]   Treatment zones - model baseline          n=  52,616  mean=0.776  med=0.709  std=0.274
[15:43:23]   Treatment zones - final                   n=  50,427  mean=0.763  med=0.693  std=0.279
[15:43:23]     of which basin-average - final          n=   3,066  mean=0.544  med=0.554  std=0.032
[15:43:23]   Total ETg volume change vs original input: -19.25%  (over 213,442 pixels valid in both rasters)
[15:43:23]   Treatment-zone ETg volume change:       -43.05%  (over 50,427 treatment pixels)
[15:43:23]   Elapsed: 9.1 s
[15:43:23] Done.  Outputs in:  ...\basins\053_PineValley\output
```

**Read this, don't just watch it scroll.** Five things tell you the run is sane:

1. **`polygons:  110 treatment  |  42 untouched`, broken out by mode.** 100
   polygons carry `scale_fctr` or `rplc_rt` and get the modeled fill; 10
   cropland polygons carry only `bsnAv_flag` and get the basin-average fill
   (step `6b`, every pixel set to the training mean, 0.5541 ft). No
   `fixed_rt` column exists in this shapefile, so that line reads 0. Before
   1.1.0 those 10 were silently left untouched; if you see `100 treatment |
   52 untouched`, you are on old code.
2. **`valid training pixels: 162,998`.** Six figures for a basin this size. A
   few thousand means the training boundary is wrong.
3. **The class table is ordered sensibly.** Aspen and riparian at the top near
   1.5 and 0.8 ft, greasewood and sagebrush around 0.5, barren at the bottom
   at 0.25. If riparian came in below sagebrush, something is misaligned.
4. **Treatment-zone mean drops from 1.339 to 0.763 ft.** The irrigation signal
   is gone and what's left sits just above the 0.554 ft basin-wide natural
   mean, which is what you'd expect for ground that is wetter than average
   even without irrigation. The `of which basin-average` line shows the 10
   flat-filled polygons landing on the training mean, as they should.
5. **Treatment-zone volume change is negative, -43.05%.** A positive number
   means the fill added water, which the downward-only cap should make
   impossible for modeled and basin-average fills (a `fixed_rt` polygon is the
   one thing that can raise it).

Watch for a class with a tiny `n`. `Great Basin Pinyon-Juniper Woodland` has
`n=3` training pixels here, so its 0.6764 ft mean carries no weight. That is
worth knowing but not worth fixing; the Gaussian window pulls from neighbours.

**Checkpoint.** `output/` now holds six rasters (`treatment_zone.tif`,
`BpS_matched.tif`, `feather_weight.tif`, and the three `053_PineValley_ETg_*`
files), `053_PineValley_polygon_summary.csv`, `053_PineValley_run.log`,
`053_PineValley_run_metadata.txt`, and one PNG.


## Step 6. Diagnostics

```
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
  Outside treatment                    n= 163,015  mean=0.554  med=0.499  p10=0.374  p90=0.799
  Treatment zones - original           n=  50,427  mean=1.339  med=1.247  p10=0.597  p90=2.185
  Treatment zones - baseline pred      n=  52,616  mean=0.776  med=0.709  p10=0.503  p90=1.226
  Treatment zones - final              n=  50,427  mean=0.763  med=0.693  p10=0.488  p90=1.208
```

Seven PNGs. The eighth in the folder,
`053_PineValley_diag_pct_change_map.png`, came from step 5.

**Checkpoint.** Eight `*_diag_*.png` files in `output/`.


## Step 7. ET unit summary

```
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
  Irrigated Cropland                  5682.63      4807.60     0.8460    0.5475    1.1445
  Meadow                              2462.36      1840.27     0.7474    0.4870    1.0077
  Phreatophyte Shrubland             36248.14     19850.70     0.5476    0.3590    0.7363
  Riparian                             779.27       676.74     0.8684    0.5639    1.1730
  TOTAL                              45172.40     27175.31
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
4. `source/053_PineValley_rates_adjust.shp` (outlines, with `mode`, `trigger`
   and this run's rates per polygon; style by `mode` to see the 10
   basin-average polygons against the 100 modeled ones)

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
| `{key}_polygon_summary.csv` | per polygon | `mean_baseline_ETg`; `treatment` and `trigger` say how each polygon was filled and which column chose it |
| `{key}_ETUNIT_SUMMARY.csv` | per ET unit | `ETg Rate (ft)`, with low and high |

`run_metadata.txt` holds the per-vegetation-class rates the whole thing is
built from, under `[bps_class_means]`. After a batch run,
`cross_basin_summary.csv` in the project root has one row per basin.

`mean_baseline_ETg` is the direct replacement for the old hand-picked
replacement rate. Where the treatment shapefile carries the legacy `rplc_rt`,
the summary also reports it plus the difference, so old and new sit side by
side:

```
polygon_id,n_pixels,treatment,trigger,adj_factor,fixed_rate,mean_input_ETg,mean_baseline_ETg,mean_final_ETg,legacy_rplc_rt,baseline_minus_legacy,ET_unit
130,813,baseline,rplc_rt,1.0,,1.7806,0.8204,0.8204,1.5,-0.6796,cropland
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

There are three ways to change the rates. Start with whichever matches the
scope of your disagreement: the whole basin (A), one polygon's modeled rate
(B), or a number you already know (C).

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
| `mode`, `trigger` | how it was filled (`baseline`, `basin_avg`, `fixed`, `none`) and which column selected it |
| `etg_input`, `etg_base`, `etg_final` | this run's mean rates (ft/yr) |
| `lgcy_rt` | the analyst's legacy `rplc_rt`, for comparison |
| `adj_fctr` | **the column you edit** to scale a polygon's modeled rate |
| `fixed_rt` | **or this one**, to burn in a rate (ft/yr) as-is, e.g. `4.0` for open water. No model, no cap, no feather. |

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
input (the log says so). The same two rules apply to `fixed_rt`. And the
rates file deliberately has no `scale_fctr` / `rplc_rt` columns, so pointing
`treatment_shp` at it by mistake fails with a clear error instead of silently
treating the wrong polygons. Through `adj_fctr` it cannot change which
polygons are treated, only their rates; through `fixed_rt` it can add a
burned-in polygon, which is the point.

The old route still works too: add `adj_fctr` to the treatment shapefile
itself (rename via `[adjustment] attr_adjust`).

### Option C: burn in a rate you already know

Sometimes the model has no business deciding. Pine Valley's open water is the
usual example: LANDFIRE classes it as the surrounding shrubland, so the modeled
rate comes out near the shrubland mean and the downward-only cap then keeps
whichever is lower. If you know the rate, type it into `fixed_rt` in the same
`053_PineValley_rates_adjust.shp` (or add a `fixed_rt` column to the master
shapefile) and re-run:

| `fixed_rt` | Effect on that polygon |
|---|---|
| `0` (the seeded value) | no override |
| `4.0` | every pixel set to 4.0 ft/yr, full stop |

Nothing else touches a fixed polygon: no `adj_fctr`, no `baseline_adjust`, no
cap, no 90 m buffer, and no feathering at its edge. The log reports it under
`7a . Fixed-rate burn-in`, the polygon summary says `treatment = fixed`, and
`mean_baseline_ETg` still shows what the model would have given, so the two
can be compared. A `fixed_rt` beats `bsnAv_flag`, which beats `scale_fctr` /
`rplc_rt`, if a polygon has more than one set.

### Confirming it took

With no `adj_fctr` column present, the log says so and falls back:

```
   2c . Per-polygon adjustment column 'adj_fctr' not found in shapefile - using basin-wide default (1.0)
```

With overrides in the rates file, step `2a` says how many it read and step
`2c` reports the factors that were actually applied:

```
   2a . Read 3 'adj_fctr' override(s) from 053_PineValley_rates_adjust.shp
   2c . Rasterizing per-polygon adjustment factors (column 'adj_fctr') ...
    expert adjustment ACTIVE - basin default: 1.0
    adjustment factors in treatment zone - min: 0.500  max: 1.000  mean: 0.943
```

The `adj_factor` column in `{key}_polygon_summary.csv` then shows what each
polygon received.

### Two limits to know before you tune

**The downward-only cap cannot be overridden.** The adjusted rate can never
exceed the original input ETg. The cap is applied per pixel, after the
adjustment and before feathering. Setting `adj_fctr = 3.0` on three Pine Valley
cropland polygons (14, 15 and 27) tripled nothing: each pixel pinned at its
own input value, so the polygon mean rose toward but stayed under the input
mean (polygon 14: baseline 0.7579, tripled and capped to a mean of 1.7655
against an input of 1.8012). Capped pixels went from 6,444 to 10,168 and the
basin figure moved from -43.05% to -34.90%. A large `adj_fctr` is a blunt way
of saying "barely change this polygon"; if that is what you mean, use
`fixed_rt` instead, which is the one override the cap does not apply to.

**Adjustments are local.** `adj_fctr = 0.5` on the same three polygons moved
exactly those three, each landing at half its previous value (polygon 14:
0.7579 to 0.3790), and left the other 148 rows identical.

### Choosing which polygons get treated at all

A polygon is treated when any of three columns is above 0. `fixed_rt` burns
that value in as-is; `bsnAv_flag` fills with the basin-wide training mean; and
`scale_fctr` or `rplc_rt` (the `attr_treat` list) fill with the modeled rate.
`fixed_rt` wins over `bsnAv_flag`, which wins over the other two. For the two
legacy columns only the sign matters.

> **The magnitude of `scale_fctr` and `rplc_rt` is ignored.** They are on/off
> triggers, nothing more. Multiplying both by ten across the whole Pine Valley
> shapefile left every raster, the log, the metadata and every modeled column
> identical, and the same -43.05%. This is the likeliest thing for someone
> coming from the legacy workflow to get wrong: `rplc_rt` used to be the value
> burned into the raster, and it no longer is. The fill value comes from the
> model, scaled only by `adj_fctr` and `baseline_adjust`. (The magnitude does
> still appear in the `legacy_rplc_rt` and `baseline_minus_legacy` review
> columns, which simply report it.)

To stop a polygon being replaced, set every one of those columns to 0. It
moves to the `42 untouched` count and its interior keeps the raw ETg.

**An untouched polygon is not necessarily an unchanged one.** Feathering
reaches roughly 250 m outside each treated boundary, so a neighbour's collar
can still pull an untouched polygon's edge pixels down. In the Pine Valley run,
32 of the 41 `treatment = none` polygons have `mean_final_ETg` below
`mean_input_ETg` for exactly that reason (polygon 1: 0.9258 in, 0.7044 out).
Only the interior is guaranteed untouched. Set `feather_width_px = 0` if you
need a hard boundary.

You can also drive treatment off different columns entirely, with the
`[treatment] attr_treat` list. That is what the optional auto-flag step
(Step 4b) uses. Two more columns select a different kind of fill:
`bsnAv_flag` (basin-average replacement) and `fixed_rt` (a rate burned in
as-is, for open water and the like). See CONFIG_GUIDE.md.

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


## Reference numbers

Verified 2026-10-07 with version 1.1.0 against the inputs named at the top,
all parameters at their defaults. (Runs before 1.1.0 treated 100 polygons, not
110, because `bsnAv_flag` was ignored; every number below moved a little when
that changed.)

| Quantity | Expected |
|---|---|
| Grid | 2853 x 970, EPSG:32611, 30 m |
| Valid ETg pixels | 213,442 |
| Treatment polygons | 110 treated (100 modeled, 10 basin-average), 42 untouched |
| Treatment-zone pixels (after 90 m buffer) | 52,616 (49,333 modeled, 3,283 basin-average) |
| NWI basin boundary pixels | 2,138,982 |
| Valid training pixels | 162,998 |
| BpS classes in training | 15 |
| Baseline range | 0.1509 to 1.9094 ft |
| Basin-average fill value | 0.5541 ft |
| Downward-only cap applied | 6,444 px |
| Treatment mean, original to final | 1.339 to 0.763 ft |
| Treatment-zone volume change | -43.05% |
| Basin-wide volume change | -19.25% |
| Total area / volume | 45,172.40 ac / 27,175.31 ac-ft |
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
| `ERROR: none of the attr_treat columns [...] found` | The shapefile lacks every trigger column. | Add `scale_fctr` or `rplc_rt`, or list the column you do have in `[treatment] attr_treat`. |
| `053_PineValley_SKIPPED.txt` appears | Fewer than 50 training pixels survived. | Almost always a boundary or CRS problem, not a genuinely small basin. |
| Treatment-zone volume change is positive | The fill added ETg. For modeled and basin-average fills the downward-only cap and the feather clip make this unreachable; a `fixed_rt` polygon can raise it on purpose. | If `polygons_fixed` in `run_metadata.txt` is 0, do not use the output; check the metadata against the reference numbers and report it. Otherwise look at the fixed rates in the polygon summary. |
| A polygon was flagged by `flag_irrigated.py` but came out untouched | The fill reads the master shapefile, not the `_autoflag.shp` copy, unless `config.toml` points at the copy and lists `autoflag` in `attr_treat`. | Either make those two config changes, or set `rplc_rt` / `bsnAv_flag` on the polygon in the master shapefile. See ADJUSTING_RATES.md. |
| A lake or other hand-rated polygon came out near 0 | The modeled fill uses the BpS class, and LANDFIRE often calls open water shrubland. | Put the rate in `fixed_rt` (master shapefile or `rates_adjust.shp`) and re-run. |
| BpS colours don't load in QGIS | The `.tif` had no embedded colour table (no gdal at prep time). | Layer Properties, Symbology, Load Style, pick `input/BpS.qml`. |
| `UnicodeEncodeError: 'charmap' codec can't encode character` on Windows | A non-ASCII character reached stdout. Windows uses cp1252, not UTF-8, whenever output is redirected or captured, so this hits `pytest` and `python ... > log.txt` but not the interactive console. | Fixed in v1.0.2; the source is now pure ASCII and `pytest` guards it. If you see it in your own edit, replace the character with an ASCII equivalent. |
| `DeprecationWarning: Setting the shape on a NumPy array ... NumPy 2.5` | Raised from inside `rasterio` on `src.read()`, not from this code. | Harmless today. Update `rasterio`, or pin `numpy<2.5`, before it becomes an error in a later NumPy. |
| Re-running prep did not re-clip `BpS.tif` | Existing files are preserved by design. | Pass `--force`. |


## Doing this for another basin

Everything above except step 1, with the key swapped. This time the data does
not ship with the repo, so prep runs twice (Step 3):

```
python prep_basin.py 042_MarysRiverArea
```

Drop the two files into `basins/042_MarysRiverArea/source/`, then:

```
python prep_basin.py 042_MarysRiverArea
```

If nobody has filled in `scale_fctr` / `rplc_rt` for this basin yet, this is
where Step 4b earns its keep:

```
python flag_irrigated.py 042_MarysRiverArea
```

Review the flags, point `treatment_shp` at the `_autoflag.shp` copy, then:

```
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
