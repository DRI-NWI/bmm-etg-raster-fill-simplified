# config.toml, explained

Every basin folder (`basins/<basin_key>/`) has a `config.toml`. The prep scripts
generate it from the template in this folder and never overwrite it afterward,
so you can edit it freely. This guide explains each setting in plain terms.
The same file and the same settings are used for NWI basins and for custom
study areas; the only difference is where the training boundary comes from
(see `boundary_shp`).

## The short version

For most basins you never touch this file. The prep script fills in the two
filenames and the defaults are tuned for 30 m ETg rasters in Nevada. The
settings people actually change, in rough order of how often:

| Setting | Change it when |
|---|---|
| `boundary_shp` | The fill warns that the training boundary is too small (custom areas where the ET-unit shapefile covers only the irrigated ground). |
| `buffer_m` | Flood irrigation wets ground well past the field edge and those wet pixels are polluting the training set. |
| `baseline_adjust` | Expert judgement says the modeled baseline is too high or too low across the whole basin. |
| `attr_treat` | You want the fill to also treat on `autoflag` from `flag_irrigated.py`, or your shapefile uses different trigger column names. |
| `attr_fixed` | Your open-water or other hand-rated polygons use a column other than `fixed_rt`, or you want the feature off (`""`). |
| `spatial_weight_radius_px` | A class is sparse and its local means are noisy (raise it), or you want one flat value per class (set to 0). |

Everything else is either filled in for you or rarely needs changing.

## How values are written

- Text values must be in quotes: `etg_tif = "my_raster.tif"`.
- Numbers are not quoted: `buffer_m = 90.0`.
- A line starting with `#` is a comment and is ignored.
- Filenames are looked up in the basin's `source/` folder first, then `input/`.
  A full path also works. On Windows, either use forward slashes
  (`"C:/data/my_etg.tif"`) or single quotes (`'C:\data\my_etg.tif'`), because
  backslashes inside double quotes are read as escape characters.

## `[basin]`

Identity of the basin. Filled in by the prep script. Leave alone.

| Setting | What it is |
|---|---|
| `basin_key` | The folder name and the name you pass on the command line, e.g. `053_PineValley` or `SierraValley`. |
| `basin_id` | The NWI hydrographic area number (`053`). Blank or a copy of the key for custom areas. |
| `basin_name` | Display name used in logs and figures. |

## `[source]`

The files you supply. Drop them in `basins/<basin_key>/source/` and re-run the
prep script; it fills in the first two names for you.

| Setting | What it is |
|---|---|
| `etg_tif` | The ETg raster in feet per year. Its grid (extent, cell size, CRS) becomes the grid of every output. Required. |
| `treatment_shp` | The polygon shapefile that says which areas get filled. Polygons are "treated" when their `scale_fctr` or `rplc_rt` value is greater than 0 (see `[treatment]`). If it has an `ET_unit` column, `etunit_summary.py` groups by it. Required. |
| `boundary_shp` | Optional outline of the area the model is allowed to learn from (the training boundary). Leave it commented out unless you need it. |

How the training boundary is chosen when `boundary_shp` is not set:

1. NWI basins (key looks like `053_PineValley`): the matching polygon from
   `NWI_Investigations_EPSG_32611.shp`.
2. Custom areas: the outline of all the treatment polygons merged together.
   This works when the ET units tile the whole study area. It does not work
   when the shapefile only covers the irrigated fields, because then almost
   nothing is left to train on. The fill warns you when the boundary covers
   less than a quarter of the ETg raster; that warning means set
   `boundary_shp` to a real basin outline.

## `[inputs]`

| Setting | What it is |
|---|---|
| `bps_tif` | The LANDFIRE Biophysical Settings raster clipped to this basin. The prep script writes it to `input/BpS.tif`. The only vegetation covariate in this workflow. Leave alone. |

## `[treatment]`

Controls which polygons are filled and how the edges are blended.

| Setting | Default | What it does |
|---|---|---|
| `buffer_m` | `90.0` | Distance in meters to grow each treated polygon before masking it out of the training data. Irrigation effects bleed past field edges, and this keeps those edge pixels from teaching the model what "natural" looks like. Raise it for flood-irrigated ground; 0 turns it off. The buffered zone is also what gets filled. |
| `feather_width_px` | `4` | Width of the blend zone just outside the treated area, in pixels (it is the sigma of a Gaussian, so the visible blend is about three times this). Prevents a hard seam between filled and untouched pixels. 4 px is about 120 m at 30 m resolution. 0 disables feathering. |
| `attr_treat` | `["scale_fctr", "rplc_rt"]` | List of shapefile columns that mark a polygon for the modeled baseline fill. Any value above 0 in any listed column means "fill this polygon." The values themselves are not used by the model. `rplc_rt` is the legacy BMM hand-picked replacement rate; it is carried into the polygon summary so you can compare it with the modeled baseline. Add `"autoflag"` to run the fill on the polygons flagged by `flag_irrigated.py`. Older configs with `attr_scale` / `attr_replace` instead of this list still work. |
| `attr_basin_avg` | `"bsnAv_flag"` | Column that marks a polygon for the legacy "basin average" fill: every pixel gets the mean of all training pixels (valid pixels outside the treatment zones, within the basin). No BpS modeling. Buffer, adjustment, cap and feathering apply as for a baseline fill. Set to `""` to turn it off. |
| `attr_fixed` | `"fixed_rt"` | Column holding a rate (ft/yr) to burn in as-is. Above 0 means "set every pixel of this polygon to this value, full stop": no model, no adjustment factor, no downward cap, no buffer, no feathering around it. Meant for open water and similar hand-assigned rates that the model has no way to reproduce. Wins over the other two columns. Set to `""` to turn it off. |

Where a polygon has values in more than one column, `attr_fixed` beats
`attr_basin_avg`, which beats `attr_treat`. The polygon summary's `treatment`
and `trigger` columns show which one applied.

To stop one polygon from being filled, set all its trigger columns to 0.
It moves to the untouched group. Its edge pixels can still be pulled down a
little by feathering from a treated neighbour.

## `[adjustment]`

Expert overrides on the modeled baseline. The baseline is multiplied by these
factors before it is written into the treated polygons. The fill also never
raises a pixel above its original ETg value (the "downward-only cap"), so a
factor above 1.0 can only take effect where the baseline is below the input.

| Setting | Default | What it does |
|---|---|---|
| `baseline_adjust` | `1.0` | One multiplier for the whole basin. `0.8` cuts every filled value by 20 percent. `1.0` means no change. |
| `attr_adjust` | `"adj_fctr"` | Name of an optional shapefile column that overrides `baseline_adjust` polygon by polygon. A value of 0 (or a missing column) means "use the basin-wide value." `0.5` halves that polygon's baseline. |

You do not need to add the column yourself. Every run writes
`<basin_key>_rates_adjust.shp` next to the treatment shapefile with `adj_fctr`
and `fixed_rt` columns already in it. Edit either in QGIS and re-run; the fill
picks them up. If the treatment shapefile itself has that column with any value
above 0, the shapefile wins and the review file is ignored for that column.

## `[baseline]`

How the natural (non-irrigated) ETg is estimated for each vegetation class.

| Setting | Default | What it does |
|---|---|---|
| `spatial_weight_radius_px` | `33` | Radius in pixels of the window used to compute each pixel's baseline. For each BpS class, the baseline at a pixel is the mean ETg of nearby non-irrigated pixels of that same class, with closer pixels weighted more (Gaussian). 33 px is about 1 km at 30 m. Larger values give smoother, more stable means and help where a class is sparse; smaller values follow local variation more closely. `0` skips the window and uses one flat basin-wide mean per class. Where a window contains no training pixels of a class, the basin-wide mean for that class is used. |

## `[flag]`

Only used by `flag_irrigated.py`, the optional pre-screen that proposes which
polygons look irrigation-influenced. Ignored by the fill itself. A polygon is
flagged when both tests pass. Command-line options (`--ratio`, `--min-excess`,
`--pctl`) override these for a single run.

| Setting | Default | What it does |
|---|---|---|
| `ratio_thresh` | `1.5` | Flag if the polygon's mean ETg is at least this many times its BpS class baseline. |
| `min_excess_ft` | `0.3` | And the polygon's mean ETg is at least this many feet per year above that baseline. Stops tiny absolute differences on low-ETg classes from being flagged. |
| `baseline_pctl` | `50.0` | Which percentile of in-basin ETg, per BpS class, counts as the "natural" baseline for the flag test. 50 is the median. Lower it (30 to 40) when the script warns that a class is mostly inside flagged polygons, because then the median itself is irrigation-inflated. |

The script writes three columns to a copy of the treatment shapefile:
`suggested` (the machine's call, recomputed every run), `analyst` (yours: -1 =
go with the suggestion, 0 = leave, 1 = treat; the only column to edit) and
`autoflag` (the result the fill triggers on, recomputed every run). `analyst`
survives re-runs unless you pass `--reset`.

## `[crs_overrides]`

Repair for rasters whose stored coordinate system is wrong or unreadable.
Normally empty. Each line is `filestem = "EPSG code"`, for example
`BpS = "EPSG:5070"`, and applies when that raster is reprojected onto the ETg
grid. Use it only when the log shows a CRS error or the BpS clearly does not
line up with the ETg raster.
