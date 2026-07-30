# bmm-etg-raster-fill-simplified: test run and documentation review

Date: 2026-07-29
Reviewed commit: `60842d4` ("code update"), clean working tree
Test environment: Linux, Python 3.11.15, rasterio 1.4.4, geopandas 1.1.4, scipy 1.17.1

## Summary

The science code is sound. A full re-run of Pine Valley reproduced the June 8
outputs exactly: `053_PineValley_polygon_summary.csv` is byte-identical,
`053_PineValley_run_metadata.txt` is identical apart from line endings, and
`ETUNIT_SUMMARY.csv` differs only in the last digit of one float. All 10 tests
pass when the template config is present.

The problem is what a coworker gets from `git clone`. `basins/_template/config.toml`
is not tracked, so every prep script exits immediately and 9 of 10 tests fail.
A second issue means they would silently lose all LANDFIRE class names. Both are
small fixes.

Findings are ordered by what blocks the coworker first.

---

## What was run

| Step | Command | Result |
|---|---|---|
| Tests | `pytest -q` | 10 passed |
| Basin list | `prep_basin.py --list` | 257 basins, matches docs |
| Prep | `prep_basin.py 053_PineValley` | BpS clipped, config generated |
| Fill | `etg_baseline_fill.py 053_PineValley` | 10.8 s, matches June 8 exactly |
| Diagnostics | `diagnostics.py 053_PineValley` | 7 PNGs |
| ET unit summary | `etunit_summary.py 053_PineValley` | 4 ET units, 45,172 ac, 27,331 ac-ft |
| Auto-flag | `flag_irrigated.py 053_PineValley` | 108 flagged of 152 |
| Custom basin | `prep_custom_basin.py --treatment ...` | ran, see finding 3 |
| Batch | `run_all.py` (2 basins) | 30.4 s, cross-basin CSV written |
| Statewide prep | `prep_statewide.py --bps ...` | ran, see finding 2 |
| Fresh clone | tracked files only | prep fails, 9 of 10 tests fail |

Reproduction check against the June 8 run:

```
Treatment zones - original input   n= 47,614  mean=1.372  med=1.319   (match)
Treatment zones - final            n= 47,614  mean=0.777  med=0.716   (match)
Treatment-zone ETg volume change:  -43.40%                            (match)
downward-only cap applied to 6,052 pixels                             (match)
```

---

## 1. BLOCKER: the config template is not in git

`.gitignore` line 4 is `basins/`, which excludes `basins/_template/config.toml`.
`git ls-files` confirms it is untracked. Every prep script renders new basin
configs from that file and hard-exits without it.

From a clean checkout of the 29 tracked files:

```
$ python prep_basin.py 053_PineValley
ERROR: config template not found at .../basins/_template/config.toml.

$ pytest -q
1 failed, 1 passed, 8 errors
```

The coworker cannot run anything. This is almost certainly why the workflow
"works on your machine": your `basins/_template/` exists locally and has never
been pushed.

**Proposed fix.** Add two negations to `.gitignore` under the data-directory
block, then force-add the file:

```gitignore
statewide/
basins/
# ...except the config template, which the prep scripts require.
!basins/_template/
!basins/_template/config.toml
```

```bash
git add -f basins/_template/config.toml
```

I would also add a one-line check to `tests/` that the template exists, so this
cannot regress silently.

---

## 2. HIGH: `gdal` is missing from `environment.yml`, and BpS class names are lost

`bps_utils.py` reads the LANDFIRE raster attribute table through
`from osgeo import gdal` in two places. conda-forge `rasterio` and `geopandas`
pull in `libgdal` but not the `osgeo` Python module, and `environment.yml` does
not list it. Both call sites swallow the failure.

I confirmed the consequence by running `prep_statewide.py` in the documented
environment. It completes, but the lookup falls through to the last-resort
branch:

```
289 BpS classes extracted -> statewide/bps_lookup.json

11  [50, 50, 50, "BpS 11"]
31  [51, 51, 51, "BpS 31"]
```

Compare your shipped `bps_lookup.json`, built on a machine that had gdal:

```
1073 -> "Inter-Mountain Basins Greasewood Flat"
```

Because `statewide/` is gitignored, the coworker must regenerate this file, so
they will hit it. Downstream effect: every run log and `run_metadata.txt` shows
`BpS 1073` instead of the class name, and the QGIS symbology is a grey ramp.

The `.tif` color table and RAT that WALKTHROUGH.md lines 280-282 promise are
also never embedded. `embed_bps_colortable_and_rat` returns `False` on the
missing import, and prep logs "GDAL embed skipped".

**Proposed fix, two parts.**

1. Track `statewide/bps_lookup.json` in git. It is 180 KB of class names and
   colors, not data, and it removes the dependency for anyone who does not need
   to rebuild the statewide clip:

   ```gitignore
   statewide/
   !statewide/bps_lookup.json
   ```

2. Add `gdal` to `environment.yml` so a rebuild produces real names:

   ```yaml
     - gdal            # osgeo bindings: reads the LANDFIRE BpS attribute table
   ```

   And make the skip message say which reason applies, rather than
   "non-integer dtype or GDAL missing".

---

## 3. HIGH: custom-basin boundary fallback can shrink training tenfold with no warning

When no `boundary_shp` is set and the key is not an NWI basin, the fill derives
the training boundary from the treatment shapefile. README.md line 424 and
WALKTHROUGH.md line 245 justify this with "the ET units tile the basin, so the
file defines it".

That is not true for the NV_phreats master shapefiles. I ran Pine Valley both
ways on identical inputs:

| Route | Training boundary | Training px | Treatment-zone volume change |
|---|---|---|---|
| NWI polygon | 2,138,982 px | 165,811 | **-43.40%** |
| `--treatment` fallback | 47,453 px | **13,688** | **-31.74%** |

The ET units cover about 2% of the basin, and most of them are treated, so the
fallback trains on the leftovers. The run reports no warning; the answer is just
different by 12 percentage points.

**Proposed fix.** Add a warning in step 4 of `etg_baseline_fill.py` when the
derived boundary covers less than some fraction (say 25%) of the valid ETg
extent:

```
4 . ... using the treatment shapefile extent as the training boundary (47,453 px)
    WARNING: that boundary covers 22% of the valid ETg extent, and 13,688
    training pixels remain. If the ET units do not tile the basin, set
    boundary_shp in config.toml to a basin outline.
```

And soften the doc claim to say the fallback assumes the ET units tile the
basin, and to check the training-pixel count when they do not.

---

## 4. MEDIUM: WALKTHROUGH step 5 promises a config backfill that does not happen

WALKTHROUGH.md lines 67-68:

> Then re-run `python prep_basin.py 053_PineValley`. It preserves the existing
> `config.toml` and just fills in the detected filenames if they were placeholders.

`prep_basin.py` line 151 returns as soon as `config.toml` exists. The
placeholders survive, and the next step fails:

```
$ python etg_baseline_fill.py 053_PineValley
ERROR: Missing required inputs for basin '053_PineValley':
  - ETG_TIF: check config.toml and files in .../source
  - TREATMENT_SHP: ...
```

A coworker following the walkthrough verbatim stops here.

**Proposed fix.** Make the code match the doc rather than the reverse, since the
doc describes the friendlier behavior. `prep_humboldt.py` already has
`_replace_toml_field`; move it into `basin_config.py` and have
`_generate_default_config` backfill only values that still start with
`# PLACE`. Roughly ten lines, and it leaves every user edit untouched.

---

## 5. MEDIUM: smaller doc and code mismatches

| # | Where | Claim | Reality | Suggested fix |
|---|---|---|---|---|
| 5a | WALKTHROUGH.md:121 | "`diagnostics.py` writes eight PNGs" | It writes seven. `{key}_diag_pct_change_map.png` is written by `etg_baseline_fill.py:763`. | Say seven, note the eighth comes from the fill |
| 5b | README.md:371 | "File names are prefixed with the basin key" | `treatment_zone.tif`, `feather_weight.tif`, `BpS_matched.tif` are not. The table just below lists them correctly. | Add "except the three intermediate rasters below" |
| 5c | README.md:300, WALKTHROUGH.md:174 | `<treatment>_autoflag.shp` written, folder unstated, under a heading that says all output goes to `output/` | It goes to `source/`, next to the treatment shapefile (`flag_irrigated.py:269`). The two report CSVs do go to `output/`. | State the folder in both docs |
| 5d | `basins/_template/config.toml:60` | `trigger_attr = "autoflag"`, "attribute the flag decision is written into" | Read into `FLAG_TRIGGER_ATTR` and never used. `flag_irrigated.py:76` hardcodes `"autoflag"`. Editing it does nothing. | Delete the key and its `basin_config.py` reader (simpler than wiring it up) |
| 5e | `diagnostics.py:19-20`, `etunit_summary.py:20-21` | Usage shows `python diagnostics.py` with no argument | Both exit with a usage error. | Add `<basin_key>` to both docstrings |
| 5f | `prep_humboldt.py:23,197-199` | Renders a missing config from the template; "prep_basin.py can overwrite the [inputs] section later" | `TEMPLATE_TOML` is declared and never read; it writes a hardcoded 5-line stub. `prep_basin.py` returns early on an existing config and never completes it. | Render from the template, or correct the docstring |
| 5g | `basins/_template/config.toml:8-9` | "the prep scripts NEVER overwrite an existing config.toml" | True for `prep_basin` and `prep_custom_basin`; `prep_humboldt.patch_config_toml` rewrites `etg_tif` and `treatment_shp` in place. | Say "prep_basin.py / prep_custom_basin.py never overwrite" |
| 5h | README.md:122-156 | Repository structure block | Omits `tests/`, `Sample_Commands.txt`, and `ETg_fill_methodology.docx` (all three are tracked) | Add the three lines |
| 5i | README.md:356 | The test asserts "the shipped code carries no machine-learning dependencies" | `tests/test_pipeline_smoke.py:34-38` scans 9 files; `prep_statewide.py` and `prep_humboldt.py` are not among them | Add both to `CODE_FILES` |
| 5j | All docs | Batch flags | `etg_baseline_fill.py`, `diagnostics.py`, `etunit_summary.py`, and `flag_irrigated.py` each accept `--all / --only / --skip / --list / --stop-on-error`; almost none are documented. `prep_basin.py --force` and `--only-missing`, `prep_custom_basin.py --buffer-m / --force`, and `prep_statewide.py --buffer-m` are also undocumented. | One short "Batch and utility flags" table in README |
| 5k | Sample_Commands.txt | Covers the NWI and custom workflows | Never mentions `flag_irrigated.py`, which README documents as a workflow step | Add two lines |

---

## 6. LOW: cosmetic

- **`diagnostics.py` prints paths that do not exist.** Seven `print` calls
  (lines 135, 154, 184, 203, 221, 242, 270) report the unprefixed name while
  `savefig` writes the prefixed one. Console says `diag_histogram.png`, disk has
  `053_PineValley_diag_histogram.png`. Fix: interpolate `{sa}_` in the print.
- **A NumPy warning on every run.** `etg_baseline_fill.py:220` triggers
  `RuntimeWarning: invalid value encountered in divide`, because `np.where`
  evaluates `vals_smooth / counts_smooth` before selecting. Harmless, but it
  looks like an error in the log. Fix: `np.divide(vals_smooth, counts_smooth,
  out=..., where=has_local)`.
- **Stale file.** `basins/053_PineValley/config.toml.bak` is sitting in the
  basin folder. Untracked, but worth deleting.

---

## What I did not test

- `prep_basin.py --all` across all 257 basins (time, not correctness).
- `prep_humboldt.py`, which needs the `Humboldt_Data/` tree. Findings 5f and 5g
  come from reading it, not running it.
- The real CONUS `LF2020_BPS_CONUS.tif`. `prep_statewide.py` was exercised with
  `BpS_statewide.tif` as a stand-in source, which covers the clip, reproject,
  and lookup-extraction paths but not a CONUS-scale read.
- Windows and conda specifically. Everything ran on Linux with pip.

---

## Suggested order of work

1. Finding 1, `.gitignore` plus `git add -f`. Unblocks the coworker.
2. Finding 2, ship `bps_lookup.json` and add `gdal`. Prevents silent loss of
   class names.
3. Finding 4, config backfill. Removes the one step where the walkthrough
   dead-ends.
4. Finding 3, boundary warning. Prevents a quietly wrong number.
5. Findings 5 and 6, doc and cosmetic edits in one pass.

Items 1 through 3 are what I would do before the coworker's next clone.
