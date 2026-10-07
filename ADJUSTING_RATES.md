# Adjusting rates by hand

A plain-language guide to telling the fill what to do with a polygon. No code,
no config editing. You open a shapefile in QGIS or ArcGIS, type a number into
one column, save, and re-run.

If you only read one section, read **The short version**.

## The short version

Ask yourself one question about the polygon: **what do I want its ETg to be?**

| I want this polygon to be... | Column to set | Value | Where |
|---|---|---|---|
| Replaced with the modeled natural rate (the default treatment) | `rplc_rt` or `scale_fctr` | any number above 0 | master shapefile |
| Replaced with one flat basin-wide rate | `bsnAv_flag` | `1` | master shapefile |
| Set to a number I choose, no modeling (open water, a known rate) | `fixed_rt` | the rate in ft/yr, e.g. `4.0` | master shapefile **or** `rates_adjust.shp` |
| Treated as before, but scaled up or down | `adj_fctr` | a multiplier, e.g. `0.8` cuts it 20% | `rates_adjust.shp` |
| Left alone, exactly as the input raster has it | all of the above | `0` | wherever they were set |

Then re-run the fill:

```
python etg_baseline_fill.py 028_BlackRockDesert
```

That's it. The rest of this guide explains the details.

## The two files you edit

There are two shapefiles involved, and they have different jobs.

**1. The master treatment shapefile** (your `..._w_ag.shp` or similar, in the
basin's `source\` folder). This decides **which** polygons get treated and
**how**. It is your file; the workflow never changes it.

**2. `<basin>_rates_adjust.shp`** (written into the same `source\` folder by
every fill run). This is for **tuning** after you have seen a result. It is a
copy of your polygons with that run's numbers attached and two columns you can
edit: `adj_fctr` and `fixed_rt`. It is regenerated every run, but your edits in
those two columns are kept.

A simple rule: set the flags (`rplc_rt`, `scale_fctr`, `bsnAv_flag`) in the
master file. Do rate tuning (`adj_fctr`, `fixed_rt`) in `rates_adjust.shp`,
because it already has `etg_input`, `etg_base` and `etg_final` sitting next to
each polygon, so you can see what you are changing.

`fixed_rt` works in either file. If both have a value for the same polygon, the
master file wins and the log tells you.

## What each column means

| Column | Plain meaning | Values |
|---|---|---|
| `rplc_rt` | "Treat this polygon with the model." The number itself is not used, only whether it is above 0. (Historically it held a hand-picked rate; that is now reported next to the modeled rate so you can compare.) | 0 = no, above 0 = yes |
| `scale_fctr` | Same as `rplc_rt`. Second trigger column, same rule. | 0 = no, above 0 = yes |
| `bsnAv_flag` | "Treat this polygon with the basin average." Every pixel gets the mean of all untreated pixels in the basin. No vegetation modeling. The old BMM method. | 0 = no, 1 = yes |
| `fixed_rt` | "Set this polygon to exactly this number." Nothing else applies: no model, no scaling, no cap, no buffer, no edge blending. | 0 = not set, otherwise ft/yr |
| `adj_fctr` | "Scale the modeled or basin-average rate by this." Only matters for polygons that are already treated. | 0 = no change, `0.8` = cut 20%, `1.2` = raise 20% |

**When a polygon has more than one set**, the fill picks in this order:
`fixed_rt`, then `bsnAv_flag`, then `rplc_rt` / `scale_fctr`. So a `fixed_rt`
always wins, and `adj_fctr` is ignored on a fixed polygon.

## The three kinds of fill, in one picture

```
  input raster          what the fill writes
  ------------          --------------------
  irrigated field  -->  modeled natural rate for that vegetation class
  (rplc_rt > 0)         scaled by adj_fctr, never higher than the input,
                        edges blended into the surroundings

  irrigated field  -->  one flat number: the basin-wide mean of untreated
  (bsnAv_flag = 1)      pixels, scaled by adj_fctr, same cap and blending

  open water       -->  exactly the number in fixed_rt, hard edge
  (fixed_rt = 4.0)
```

## Step by step in QGIS

1. Run the fill once so `<basin>_rates_adjust.shp` exists in `source\`.
2. Open `<basin>_rates_adjust.shp` in QGIS. Style it by `etg_final` or `mode`
   to see what happened.
3. Find the polygon. The `mode` column says how it was treated (`baseline`,
   `basin_avg`, `fixed`, or `none`) and `trigger` says which column caused
   that. `etg_input`, `etg_base`, `etg_final` are its mean rates in ft/yr.
4. Toggle editing, type your value into `adj_fctr` or `fixed_rt`, save.
   - To change **whether** a polygon is treated, edit `rplc_rt`,
     `scale_fctr` or `bsnAv_flag` in the **master** shapefile instead.
5. Re-run the fill. The log reports how many overrides it read.
6. Check `output\<basin>_polygon_summary.csv`. Find your polygon and look at
   `treatment`, `trigger`, `fixed_rate`, `adj_factor` and `mean_final_ETg`.

## Worked examples

**A center pivot in phreatophytes is still irrigated in the final raster.**
Its `rplc_rt`, `scale_fctr` and `bsnAv_flag` are probably all 0, so nothing told
the fill to treat it. Set `rplc_rt = 1` (modeled rate) or `bsnAv_flag = 1`
(basin average) in the master shapefile and re-run.

**A lake came out at 0.05 ft/yr.** The model thinks it is shrubland because
that is what the vegetation layer says. Type `4.0` (or your number) into
`fixed_rt` for that polygon in `rates_adjust.shp` and re-run. It will come out
at exactly 4.0.

**The modeled rate for one field looks 20% too high.** In `rates_adjust.shp`,
set `adj_fctr = 0.8` for that polygon and re-run.

**Everything in the basin looks a bit high.** That is a basin-wide setting,
not a per-polygon edit: `baseline_adjust` in `config.toml`. A per-polygon
`adj_fctr` still overrides it for that polygon.

**I want to undo an edit.** Set the column back to `0` and re-run.

## Rules that catch people

- **Numbers, not text.** A `"1"` typed into a text field does nothing. The
  columns must be numeric. If you add a column, make it a decimal number
  (double/real).
- **Names are case-sensitive and must match exactly.** `fixed_rt`, not
  `Fixed_rt` or `fixed_rate`. If your shapefile uses other names, they can be
  changed in `config.toml`, but ask before doing that.
- **0 means "not set."** It never means "set to zero." To push a polygon's rate
  to zero you would use `fixed_rt` with a very small number, but think twice:
  that is rarely what you want.
- **The downward-only cap.** A modeled or basin-average fill never raises a
  pixel above its input value. If you want a polygon *higher* than the input,
  only `fixed_rt` can do that.
- **Edges.** Modeled and basin-average polygons are buffered outward (90 m by
  default) and blended into their surroundings. Fixed-rate polygons are not;
  the edge is hard and nothing outside the polygon changes.
- **The master file wins.** If the same polygon has `fixed_rt` or `adj_fctr`
  set in both the master shapefile and `rates_adjust.shp`, the master value is
  used and the `rates_adjust.shp` value is ignored for that column.
- **Don't point the fill at `rates_adjust.shp`.** It is a review and tuning
  file. It deliberately lacks the trigger columns, so if `config.toml` ever
  names it as `treatment_shp`, the run stops with an error instead of treating
  the wrong polygons.

## The auto-flagger (optional, separate)

`flag_irrigated.py` is a **suggestion** tool. It looks at each polygon's ETg
against what is normal for its vegetation and proposes which ones look
irrigated. It does **not** change what the fill does unless you connect the
two.

It writes `<treatment>_autoflag.shp` next to your master file, with three
columns:

| Column | Meaning | Edit it? |
|---|---|---|
| `suggested` | the script's call, 1 = looks irrigated | no, recomputed every run |
| `analyst` | your call: `-1` = go with the suggestion, `1` = treat, `0` = leave alone | **yes, this is the one** |
| `autoflag` | the result (`analyst` where set, otherwise `suggested`) | no, recomputed every run |

To make the fill act on `autoflag`, two lines in `config.toml`:

```toml
[source]
treatment_shp = "<master name>_autoflag.shp"

[treatment]
attr_treat = ["scale_fctr", "rplc_rt", "autoflag"]
```

Without those lines, the flagger's output is for your eyes only. That is the
most common reason a polygon "was flagged but didn't get filled."

## Quick checklist when something didn't change

1. Did you re-run the fill after editing? Edits only apply on the next run.
2. Did you edit the right file? Flags in the master shapefile; tuning in
   `rates_adjust.shp`.
3. Is the column numeric and spelled exactly right?
4. Open `output\<basin>_polygon_summary.csv` and find the polygon. What does
   `treatment` say? If it says `none`, no trigger column was above 0.
5. If it says `baseline` or `basin_avg` but the value barely moved, check
   `mean_input_ETg` against `mean_baseline_ETg`. If the model's rate is
   higher than the input, the cap kept the input. Use `fixed_rt` if you really
   need a higher number.
6. Still stuck? Send the row from `polygon_summary.csv` and the step 2 lines
   from the run log.
