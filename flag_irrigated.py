#!/usr/bin/env python3
"""
flag_irrigated.py
=================
Pre-screening helper for the ETg raster-fill workflow.  It compares the raw ETg
in each treatment-shapefile polygon against the natural ETg of that polygon's
LANDFIRE Biophysical Settings (BpS) vegetation class, and flags polygons whose
ETg is elevated enough to suggest the feature is benefiting from irrigation.

The result goes into three columns on a copy of the shapefile:

    suggested   0/1   what the thresholds say.  Recomputed every run.
    analyst    -1/0/1 THE ONLY COLUMN YOU EDIT.  -1 (the seeded value) means
                      "go with the suggestion"; 1 = treat this polygon;
                      0 = leave it alone.  Carried over run to run.
    autoflag    0/1   the result: ``analyst`` where it is 0 or 1, else
                      ``suggested``.  This is what the fill triggers on.

A GIS analyst reviews in QGIS/ArcGIS and types 0 or 1 into ``analyst`` for the
polygons they disagree with.  Nothing is inferred: re-running recomputes
``suggested`` and ``autoflag`` and keeps ``analyst`` as typed (``--reset``
clears it back to -1).  Polygons already marked by hand in the source
shapefile (scale_fctr, rplc_rt, bsnAv_flag or fixed_rt above 0) are always
``autoflag = 1``.

How a polygon is flagged
------------------------
For each BpS class, a robust natural baseline ETg is taken as a percentile
(default: the median) of the raw ETg over all in-basin pixels of that class -
the median is resistant to the elevated minority of irrigated pixels.  Each
polygon's expected baseline is the pixel-count-weighted average of the
baselines of the BpS classes it covers.  A polygon is auto-flagged when

    mean ETg  >=  ratio_thresh x expected_baseline      (default 1.5x)
        AND
    mean ETg  -  expected_baseline  >=  min_excess_ft   (default 0.3 ft/yr)

The min-excess guard prevents flagging trivial differences in low-ET classes.
Thresholds come from the basin's config.toml ``[flag]`` section and can be
overridden on the command line.

Acting on the flags
--------------------
The output shapefile keeps every original attribute and adds ``suggested``,
``analyst``, ``autoflag`` and per-polygon diagnostics.  To
run the fill on the flagged polygons, either add ``"autoflag"`` to the
``attr_treat`` list in config.toml [treatment] and point ``treatment_shp`` at
this file, or pass
``--mirror-to rplc_rt`` here to copy the flag into the rplc_rt trigger column.

Usage
-----
    python flag_irrigated.py 053_PineValley
    python flag_irrigated.py 053_PineValley --ratio 1.4 --min-excess 0.25
    python flag_irrigated.py --all
    python flag_irrigated.py 053_PineValley --reset          # clear the analyst column
    python flag_irrigated.py 053_PineValley --mirror-to rplc_rt

License: MIT (see LICENSE)
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.features import rasterize
    from rasterio.warp import reproject
    import geopandas as gpd
except ImportError as e:
    sys.exit(
        f"Missing dependency: {e}\n"
        "Install with:  pip install rasterio geopandas fiona shapely pyproj"
    )

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
cfg = None  # set by _load_cfg()

# Output attribute names (kept <= 10 chars for ESRI Shapefile / DBF).
F_DECIDE  = "autoflag"     # result (0/1): what the fill triggers on; recomputed
F_SUGGEST = "suggested"    # machine suggestion (0/1); recomputed every run
F_ANALYST = "analyst"      # analyst's call: -1 = defer to suggestion, 0 = no, 1 = yes
F_AUTO_LEGACY = "autoflag_a"   # pre-1.1.0 name of the suggestion column
NO_OPINION = -1
F_MEAN   = "etg_mean"      # polygon mean raw ETg
F_BASE   = "bps_base"      # expected natural baseline for the polygon
F_RATIO  = "etg_ratio"     # etg_mean / bps_base
F_EXCESS = "etg_excs"      # etg_mean - bps_base
F_DOM    = "bps_dom"       # dominant BpS class code in the polygon
F_NPIX   = "n_pix"         # valid pixels in the polygon

# A BpS class with at least this much of its in-basin area inside flagged
# polygons is likely majority-irrigated, which inflates its median baseline and
# causes the screen to under-flag.  Such classes get a warning.
CONTAM_WARN_PCT = 50.0


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_cfg(study_area: str):
    global cfg
    basins_dir = _here / "basins"
    toml_path = basins_dir / study_area / "config.toml"
    if not toml_path.exists():
        import basin_config as _bc
        available = _bc.available_areas()
        sys.exit(
            f"ERROR: no config.toml found for '{study_area}' at {toml_path}.\n"
            f"  Run prep_basin.py (or prep_custom_basin.py) first.\n"
            f"  Available basins: {', '.join(available) if available else '(none)'}"
        )
    import basin_config as _cfg
    _cfg.load_basin(study_area)
    cfg = _cfg


def _read_etg(path: Path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        nodata = src.nodata
    if nodata is not None:
        arr[arr == np.float32(nodata)] = np.nan
    return arr, profile


def _match_bps(src_path: Path, ref_profile: dict) -> np.ndarray:
    """Reproject the BpS raster onto the ETg grid (nearest, integer)."""
    with rasterio.open(src_path) as src:
        src_crs = src.crs
        stem = src_path.stem
        if stem in cfg.CRS_OVERRIDES:
            from rasterio.crs import CRS as _CRS
            src_crs = _CRS.from_string(cfg.CRS_OVERRIDES[stem])
            _log(f"    CRS override for {stem}: -> {src_crs}")
        src_arr = src.read(1)
        src_transform = src.transform
        src_nodata = src.nodata
    dst = np.zeros((ref_profile["height"], ref_profile["width"]), dtype=np.int32)
    reproject(
        source=src_arr, destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=ref_profile["transform"], dst_crs=ref_profile["crs"],
        resampling=Resampling.nearest, src_nodata=src_nodata, dst_nodata=0,
    )
    return dst


def _build_basin_mask(grid_shape, grid_transform, etg_crs, treatment_gdf):
    """Return a boolean in-basin mask.

    Resolution order: explicit boundary_shp -> NWI polygon -> dissolved extent
    of the treatment shapefile (the ET units tile the basin) -> None (all pixels).
    """
    from shapely.ops import unary_union
    boundary_shp = getattr(cfg, "BOUNDARY_SHP", None)
    boundary_configured = getattr(cfg, "BOUNDARY_SHP_CONFIGURED", False)
    boundary_missing = getattr(cfg, "BOUNDARY_SHP_MISSING", False)
    nwi_path = _here / "NWI_Investigations_EPSG_32611.shp"
    key = cfg.STUDY_AREA_NAME
    looks_like_nwi = "_" in key and key.split("_", 1)[0].isdigit()

    def _from_treatment(reason):
        geoms = [g for g in treatment_gdf.geometry if g is not None and g.is_valid]
        if not geoms:
            _log(f"    {reason}; treatment shapefile has no usable geometry - "
                 f"using all valid pixels")
            return None
        m = rasterize([(unary_union(geoms), 1)], out_shape=grid_shape,
                      transform=grid_transform, fill=0, dtype=np.uint8).astype(bool)
        _log(f"    {reason}; using the treatment shapefile extent as the "
             f"boundary ({int(m.sum()):,} px)")
        return m

    if boundary_shp is not None and Path(boundary_shp).exists():
        gdf_bnd = gpd.read_file(boundary_shp)
        if len(gdf_bnd) == 0:
            return _from_treatment("configured boundary_shp is empty")
        geom = unary_union(gdf_bnd.geometry)
        if gdf_bnd.crs is not None and not gdf_bnd.crs.equals(etg_crs):
            geom = gpd.GeoSeries([geom], crs=gdf_bnd.crs).to_crs(etg_crs).iloc[0]
        mask = rasterize([(geom, 1)], out_shape=grid_shape,
                         transform=grid_transform, fill=0, dtype=np.uint8).astype(bool)
        _log(f"    basin boundary pixels (custom): {int(mask.sum()):,}")
        return mask

    if boundary_configured and boundary_missing:
        return _from_treatment("boundary_shp configured but file missing")

    if looks_like_nwi and nwi_path.exists():
        gdf_nwi = gpd.read_file(nwi_path)
        m = gdf_nwi[gdf_nwi["Basin"] == key]
        if len(m) == 0:
            ck = key.split("_", 1)[-1] if "_" in key else key
            m = gdf_nwi[gdf_nwi["BasinName"].str.replace(" ", "") == ck]
        if len(m) > 0:
            geom = m.iloc[0].geometry
            if m.crs is not None and not m.crs.equals(etg_crs):
                geom = gpd.GeoSeries([geom], crs=m.crs).to_crs(etg_crs).iloc[0]
            mask = rasterize([(geom, 1)], out_shape=grid_shape,
                             transform=grid_transform, fill=0, dtype=np.uint8).astype(bool)
            _log(f"    basin boundary pixels (NWI): {int(mask.sum()):,}")
            return mask
        return _from_treatment(f"'{key}' not found in NWI shapefile")

    return _from_treatment("no boundary_shp configured and not an NWI basin")


def _pick_id_column(gdf):
    for cand in ("DRI_ID", "UniqueID", "ET_unit", "FID"):
        if cand in gdf.columns:
            return cand
    return None


def flag_one(study_area: str, ratio_thresh: float, min_excess: float,
             pctl: float, reset: bool, mirror_to: str | None) -> None:
    _load_cfg(study_area)
    _log(f"=== Auto-flag: {cfg.STUDY_AREA_NAME} ===")
    ratio_thresh = ratio_thresh if ratio_thresh is not None else cfg.FLAG_RATIO_THRESH
    min_excess   = min_excess   if min_excess   is not None else cfg.FLAG_MIN_EXCESS_FT
    pctl         = pctl         if pctl         is not None else cfg.FLAG_BASELINE_PCTL
    _log(f"    rule: mean ETg >= {ratio_thresh}x baseline AND >= {min_excess} ft/yr above it; "
         f"baseline = per-BpS p{pctl:g} over in-basin pixels")

    out_dir = cfg.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- Read ETg (template grid) + BpS --------------------------------------
    etg, prof = _read_etg(cfg.ETG_TIF)
    grid_shape = (prof["height"], prof["width"])
    grid_transform = prof["transform"]
    etg_crs = prof["crs"]
    bps = _match_bps(cfg.BPS_TIF, prof)

    # -- Read treatment polygons (also the boundary fallback source) ---------
    gdf = gpd.read_file(cfg.TREATMENT_SHP)
    if gdf.crs is not None and not gdf.crs.equals(etg_crs):
        gdf = gdf.to_crs(etg_crs)

    # -- In-basin valid mask + per-BpS-class baseline ------------------------
    basin = _build_basin_mask(grid_shape, grid_transform, etg_crs, gdf)
    valid = np.isfinite(etg) & (etg > 0) & (bps > 0)
    if basin is not None:
        valid &= basin
    n_valid = int(valid.sum())
    if n_valid == 0:
        sys.exit("ERROR: no valid in-basin ETg pixels - check inputs / boundary.")

    global_base = float(np.percentile(etg[valid], pctl))
    class_base = {}
    for c in np.unique(bps[valid]):
        class_base[int(c)] = float(np.percentile(etg[valid & (bps == c)], pctl))
    _log(f"    valid in-basin pixels: {n_valid:,}   BpS classes: {len(class_base)}   "
         f"global baseline p{pctl:g}: {global_base:.3f} ft")

    try:
        from bps_utils import load_bps_lookup, bps_name as _bps_name
        _lut = load_bps_lookup()
    except Exception:
        _lut = {}
        def _bps_name(code, lut=None):
            return f"BpS {code}"

    # -- Treatment attributes -----------------------------------------------
    # Every column that already marks a polygon for treatment in the fill:
    # the attr_treat list plus the basin-average and fixed-rate columns.
    attr_treat = list(getattr(cfg, "ATTR_TREAT", [cfg.ATTR_SCALE, cfg.ATTR_REPLACE]))
    manual_cols = [c for c in attr_treat
                   + [getattr(cfg, "ATTR_BASIN_AVG", ""), getattr(cfg, "ATTR_FIXED", "")]
                   if c and c in gdf.columns]
    id_col = _pick_id_column(gdf)

    # -- Load the analyst column from a previous run (if any) ----------------
    # Matched by polygon ID when both files have a unique one, else by row
    # position when the row counts agree.  Each prior entry is
    # (analyst, autoflag, suggested) from the last run; the hand-edit rescue
    # and the pre-1.1.0 migration are decided in the loop below, where the
    # polygon's manual flag is known.
    orig_stem = Path(cfg.TREATMENT_SHP).stem
    out_shp = Path(cfg.TREATMENT_SHP).parent / f"{orig_stem}_autoflag.shp"
    NONE_PRIOR = (NO_OPINION, None, None)
    prior = {}          # id -> entry
    prior_by_pos = []   # positional fallback
    legacy_file = False
    if out_shp.exists() and not reset:
        try:
            pg = gpd.read_file(out_shp)
            n = len(pg)
            if F_ANALYST in pg.columns:
                a_prev = pg[F_ANALYST].fillna(NO_OPINION).astype(int).tolist()
                d_prev = (pg[F_DECIDE].fillna(0).astype(int).tolist()
                          if F_DECIDE in pg.columns else [None] * n)
                s_prev = (pg[F_SUGGEST].fillna(0).astype(int).tolist()
                          if F_SUGGEST in pg.columns else [None] * n)
            elif F_DECIDE in pg.columns and F_AUTO_LEGACY in pg.columns:
                # Pre-1.1.0 layout: no analyst column.  Wherever autoflag
                # differs from autoflag_a the analyst changed it.
                legacy_file = True
                a_prev = [NO_OPINION] * n
                d_prev = pg[F_DECIDE].fillna(0).astype(int).tolist()
                s_prev = pg[F_AUTO_LEGACY].fillna(0).astype(int).tolist()
            else:
                a_prev = None
            if a_prev is not None:
                entries = [(a if a in (0, 1) else NO_OPINION, d, s_)
                           for a, d, s_ in zip(a_prev, d_prev, s_prev)]
                if id_col and id_col in pg.columns and pg[id_col].is_unique \
                        and gdf[id_col].is_unique:
                    prior = dict(zip(pg[id_col].tolist(), entries))
                elif n == len(gdf):
                    prior_by_pos = entries
                else:
                    _log(f"    (cannot match rows of {out_shp.name} to the "
                         f"treatment shapefile - analyst column not carried over)")
        except Exception as e:
            _log(f"    (could not read prior '{F_ANALYST}' values from "
                 f"{out_shp.name}: {e})")

    def _prior_for(i, row):
        if prior and id_col is not None:
            return prior.get(row[id_col], NONE_PRIOR)
        if prior_by_pos:
            return prior_by_pos[i]
        return NONE_PRIOR

    # -- Per-polygon screening ----------------------------------------------
    gdf_r = gdf.reset_index(drop=True)
    dec, sugg, analyst, means, bases, ratios, excs, doms, npix = ([] for _ in range(9))
    rows_report = []
    n_auto = n_manual = n_override = 0
    n_edited_result = n_migrated = 0

    for i, row in gdf_r.iterrows():
        geom = row.geometry
        af_a = 0
        emean = ebase = eratio = eexc = float("nan")
        dom = 0
        n = 0
        if geom is not None and geom.is_valid:
            mini = rasterize([(geom, 1)], out_shape=grid_shape,
                             transform=grid_transform, fill=0, dtype=np.uint8)
            px = (mini == 1) & np.isfinite(etg) & (etg > 0)
            n = int(px.sum())
            if n > 0:
                emean = float(np.mean(etg[px]))
                pcls = bps[px & (bps > 0)]
                if pcls.size:
                    codes, counts = np.unique(pcls, return_counts=True)
                    dom = int(codes[np.argmax(counts)])
                    ebase = float(np.sum([counts[k] * class_base.get(int(codes[k]), global_base)
                                          for k in range(len(codes))]) / counts.sum())
                else:
                    ebase = global_base
                eexc = emean - ebase
                if ebase > 0:
                    eratio = emean / ebase
                    af_a = int(eratio >= ratio_thresh and eexc >= min_excess)
                else:
                    af_a = int(eexc >= min_excess)

        # Result: analyst (0/1) > existing manual flag > suggestion.
        manual_flag = any(float(row.get(c, 0) or 0) > 0 for c in manual_cols)
        a_val, d_prev, s_prev = _prior_for(i, row) if not reset else NONE_PRIOR
        if a_val not in (0, 1):
            a_val = NO_OPINION
            # The stored result disagrees with the stored suggestion and the
            # analyst column says nothing: the analyst edited the result
            # column (old habit), or this is a pre-1.1.0 file.  Keep that
            # decision by moving it into the analyst column.  A manually
            # flagged polygon is always 1 regardless, so it is not an edit.
            if (d_prev in (0, 1) and s_prev in (0, 1) and d_prev != s_prev
                    and not manual_flag):
                a_val = d_prev
                if legacy_file:
                    n_migrated += 1
                else:
                    n_edited_result += 1

        if a_val in (0, 1):
            decision, source = a_val, "analyst"
            n_override += 1
        elif manual_flag:
            decision, source = 1, "manual_flag"
            n_manual += 1
        else:
            decision, source = af_a, "suggested"
            if af_a == 1:
                n_auto += 1

        dec.append(int(decision)); sugg.append(int(af_a)); analyst.append(int(a_val))
        means.append(round(emean, 4)); bases.append(round(ebase, 4))
        ratios.append(round(eratio, 4)); excs.append(round(eexc, 4))
        doms.append(dom); npix.append(n)
        rows_report.append({
            "polygon_id": row[id_col] if id_col else i,
            F_NPIX: n, F_DOM: dom, "bps_dom_name": _bps_name(dom, _lut) if dom else "",
            F_MEAN: round(emean, 4), F_BASE: round(ebase, 4),
            F_RATIO: round(eratio, 4), F_EXCESS: round(eexc, 4),
            F_SUGGEST: int(af_a), F_ANALYST: int(a_val), F_DECIDE: int(decision),
            "source": source,
        })

    # -- Assemble + write output shapefile ----------------------------------
    out = gdf.copy()
    out[F_SUGGEST] = sugg
    out[F_ANALYST] = analyst
    out[F_DECIDE] = dec
    out = out.drop(columns=[F_AUTO_LEGACY], errors="ignore")
    if legacy_file:
        _log(f"    migrating pre-1.1.0 {out_shp.name}: {n_migrated} analyst "
             f"override(s) moved into the '{F_ANALYST}' column; "
             f"'{F_AUTO_LEGACY}' is dropped")
    if n_edited_result:
        _log(f"    NOTE: {n_edited_result} row(s) had '{F_DECIDE}' edited by hand. "
             f"Kept, but please edit '{F_ANALYST}' instead: '{F_DECIDE}' is "
             f"recomputed every run.")
    out[F_MEAN] = means
    out[F_BASE] = bases
    out[F_RATIO] = ratios
    out[F_EXCESS] = excs
    out[F_DOM] = doms
    out[F_NPIX] = npix
    # Ensure the fill tool's trigger columns exist so the output is fill-ready.
    for c in attr_treat:
        if c not in out.columns:
            out[c] = 0.0

    # Seed a stable per-polygon label if the source lacks one, so rows in
    # {key}_polygon_summary.csv trace back to features.  (Rate tuning happens
    # in the {key}_rates_adjust.shp file the fill writes - not here.)
    if "UniqueID" not in out.columns:
        out["UniqueID"] = range(len(out))
        _log("    seeded 'UniqueID' column (stable per-polygon label)")
    if mirror_to:
        out[mirror_to] = out[F_DECIDE].astype(float)
        _log(f"    mirrored '{F_DECIDE}' into trigger column '{mirror_to}'")

    out.to_file(out_shp)
    _log(f"  -> wrote {out_shp.name}  ({len(out)} polygons)")

    # -- CSV report ----------------------------------------------------------
    csv_path = out_dir / f"{cfg.STUDY_AREA_NAME}_autoflag_report.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_report[0].keys())) if rows_report \
            else None
        if w:
            w.writeheader(); w.writerows(rows_report)
    _log(f"  -> wrote {csv_path.name}")

    # -- Per-BpS-class diagnostic -------------------------------------------
    # Share of each class's in-basin area that ends up inside flagged polygons.
    # A high share means the class is largely irrigated, so its basin-wide
    # median baseline is inflated and the screen is probably under-flagging it.
    dec_arr = np.array(dec, dtype=int)
    dom_arr = np.array(doms, dtype=int)
    flag_geoms = [(gdf_r.geometry.iloc[i], 1) for i in range(len(gdf_r))
                  if dec_arr[i] == 1 and gdf_r.geometry.iloc[i] is not None
                  and gdf_r.geometry.iloc[i].is_valid]
    flag_mask = (rasterize(flag_geoms, out_shape=grid_shape,
                           transform=grid_transform, fill=0, dtype=np.uint8).astype(bool)
                 if flag_geoms else np.zeros(grid_shape, dtype=bool))
    class_rows, contaminated = [], []
    for c in sorted(class_base):
        cls = valid & (bps == c)
        nb = int(cls.sum())
        if nb == 0:
            continue
        nf = int((cls & flag_mask).sum())
        pct_f = 100.0 * nf / nb
        n_dom = int((dom_arr == c).sum())
        n_dom_f = int(((dom_arr == c) & (dec_arr == 1)).sum())
        class_rows.append({
            "bps_code": c, "bps_name": _bps_name(c, _lut),
            "baseline_ft": round(class_base[c], 4),
            "n_pix_basin": nb, "n_pix_flagged": nf,
            "pct_area_flagged": round(pct_f, 1),
            "n_polys_dom": n_dom, "n_polys_dom_flagged": n_dom_f,
        })
        if pct_f >= CONTAM_WARN_PCT:
            contaminated.append((c, _bps_name(c, _lut), pct_f))
    if class_rows:
        class_csv = out_dir / f"{cfg.STUDY_AREA_NAME}_autoflag_class_summary.csv"
        with open(class_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(class_rows[0].keys()))
            w.writeheader(); w.writerows(class_rows)
        _log(f"  -> wrote {class_csv.name}")
        _log("  per-BpS-class flagged share (high share => baseline may be "
             "irrigation-contaminated):")
        for r in sorted(class_rows, key=lambda x: -x["pct_area_flagged"]):
            _log(f"      {r['bps_name'][:32]:32s} code={r['bps_code']:<6d} "
                 f"base={r['baseline_ft']:.3f} ft  area_flagged={r['pct_area_flagged']:5.1f}%  "
                 f"polys={r['n_polys_dom_flagged']}/{r['n_polys_dom']}")

    n_flagged = int(sum(dec))
    _log("-- Summary -----------------------------------------")
    _log(f"  polygons total          : {len(out):,}")
    _log(f"  suggested by thresholds : {n_auto:,}")
    _log(f"  already flagged by hand : {n_manual:,}")
    _log(f"  decided by analyst col  : {n_override:,}")
    _log(f"  FLAGGED for treatment   : {n_flagged:,}  ({F_DECIDE} = 1)")
    for c, name, pct in contaminated:
        _log(f"  WARNING: BpS {c} ({name}) has {pct:.0f}% of its in-basin area inside "
             f"flagged polygons - its p{pctl:g} baseline may be irrigation-inflated and "
             f"cause under-flagging. Consider lowering baseline_pctl (e.g. 30-40) and "
             f"re-running with --reset.")
    _log(f"  Next: review in QGIS.  '{F_SUGGEST}' is the machine's call; type 0 or 1")
    _log(f"  into '{F_ANALYST}' where you disagree (-1 = go with the suggestion),")
    _log(f"  then re-run.  '{F_DECIDE}' is the result and is recomputed every run.")
    if mirror_to:
        _log(f"  The fill will treat flagged polygons via the '{mirror_to}' column.")
    else:
        _log(f"  To run the fill on these flags, add \"{F_DECIDE}\" to attr_treat in")
        _log(f"  config.toml [treatment] and point treatment_shp at {out_shp.name},")
        _log(f"  or re-run with --mirror-to {attr_treat[-1] if attr_treat else 'rplc_rt'}.")


def _cli():
    import basin_config as _bc
    ap = argparse.ArgumentParser(
        prog="flag_irrigated.py",
        description="Flag treatment polygons whose ETg looks irrigation-inflated "
                    "relative to their BpS class.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("study_area", nargs="?", help="Basin key (e.g. 053_PineValley).")
    ap.add_argument("--all", action="store_true", help="Process every basin with a config.toml.")
    ap.add_argument("--only", nargs="+", metavar="KEY", help="Process only these basin keys.")
    ap.add_argument("--skip", nargs="+", metavar="KEY", default=[], help="With --all, skip these.")
    ap.add_argument("--list", action="store_true", help="List available basins and exit.")
    ap.add_argument("--ratio", type=float, default=None,
                    help="Override ratio threshold (mean ETg / class baseline).")
    ap.add_argument("--min-excess", type=float, default=None,
                    help="Override minimum ETg excess in ft/yr above the baseline.")
    ap.add_argument("--pctl", type=float, default=None,
                    help="Override the per-BpS-class baseline percentile (50 = median).")
    ap.add_argument("--reset", action="store_true",
                    help="Clear the 'analyst' column back to -1 (drop every hand decision).")
    ap.add_argument("--mirror-to", metavar="ATTR", default=None,
                    help="Also copy the autoflag decision into this trigger column "
                         "(e.g. rplc_rt) so the fill treats flagged polygons unchanged.")
    args = ap.parse_args()

    available = _bc.available_areas()
    if args.list:
        print(f"{len(available)} basin(s) with config.toml:")
        for k in available:
            print(f"  {k}")
        return
    if args.all and args.only:
        ap.error("--all and --only are mutually exclusive")
    if args.all:
        targets = [k for k in available if k not in set(args.skip)]
    elif args.only:
        missing = [k for k in args.only if k not in available]
        if missing:
            sys.exit(f"Basin(s) not found: {', '.join(missing)}")
        targets = list(args.only)
    elif args.study_area:
        if args.study_area not in available:
            sys.exit(f"Basin '{args.study_area}' not found (no config.toml).\n"
                     f"  Available: {', '.join(available) if available else '(none)'}")
        targets = [args.study_area]
    else:
        ap.print_help()
        sys.exit("\nERROR: supply <study_area>, --all, --only, or --list.")

    if not targets:
        sys.exit("No basins to process.")

    failed = []
    for key in targets:
        try:
            flag_one(key, args.ratio, args.min_excess, args.pctl,
                     args.reset, args.mirror_to)
        except SystemExit as e:
            if len(targets) == 1:
                raise
            failed.append((key, str(e)))
            print(f"! {key} aborted: {e}")
        except Exception as e:  # pragma: no cover - defensive
            if len(targets) == 1:
                raise
            failed.append((key, f"{type(e).__name__}: {e}"))
            print(f"! {key} failed: {type(e).__name__}: {e}")
    if failed and len(failed) == len(targets):
        sys.exit(1)


if __name__ == "__main__":
    _cli()
