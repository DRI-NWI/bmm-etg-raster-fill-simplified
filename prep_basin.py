#!/usr/bin/env python3
"""
prep_basin.py
=============
Per-basin setup: clips the statewide BpS raster to a single basin boundary
and generates a default ``config.toml`` if one doesn't exist.

BpS is the only covariate this workflow needs - the baseline is a spatially
weighted per-BpS-class mean, with no DEM or other terrain inputs.

Reads the basin polygon from NWI_Investigations_EPSG_32611.shp using the
``Basin`` field as the key (e.g. "101_SierraValley").

Usage
-----
    # Prep a single basin:
    python prep_basin.py 101_SierraValley

    # Prep all basins:
    python prep_basin.py --all

    # List available basin keys from the NWI shapefile:
    python prep_basin.py --list

    # Also cut each basin's treatment polygons out of a statewide dataset
    # (writes source/<basin_key>_treatment.shp and points config.toml at it):
    python prep_basin.py --all --treatment-src C:\\data\\NV_phreats_statewide.shp

Outputs
-------
    basins/<basin_key>/
        source/       (you drop the ETg raster + treatment shapefile here;
                       with --treatment-src, <basin_key>_treatment.shp is
                       written here for you)
        input/
            BpS.tif
            BpS.clr   (QGIS/ArcGIS symbology)
            BpS.qml
        output/
        config.toml   (created only if missing - never overwritten)

License: MIT
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.enums import Resampling
    import geopandas as gpd
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\n"
             "Install: pip install rasterio geopandas shapely")

_here = Path(__file__).resolve().parent
PROJECT_DIR = _here
STATEWIDE_DIR = PROJECT_DIR / "statewide"
BASINS_DIR = PROJECT_DIR / "basins"
NWI_SHP = _here / "NWI_Investigations_EPSG_32611.shp"

# Fields in NWI_Investigations_EPSG_32611.shp
BASIN_KEY_FIELD = "Basin"
BASIN_ID_FIELD  = "BasinID"
BASIN_NAME_FIELD = "BasinName"

# Buffer around basin polygon when clipping BpS (meters).  Larger than the
# treatment buffer so there's always BpS data available at the edges of the
# treatment zone.
BASIN_CLIP_BUFFER_M = 5_000  # 5 km


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_nwi() -> gpd.GeoDataFrame:
    """Load NWI shapefile, return GeoDataFrame."""
    if not NWI_SHP.exists():
        sys.exit(f"ERROR: NWI shapefile not found: {NWI_SHP}")
    return gpd.read_file(NWI_SHP)


def _crs_equal(a, b) -> bool:
    """Compare two CRS-like objects (rasterio.crs.CRS lacks ``.equals()``)."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return rasterio.crs.CRS.from_user_input(a) == \
               rasterio.crs.CRS.from_user_input(b)
    except Exception:
        return str(a) == str(b)


def _clip_from_statewide(
    src_name: str,
    dst_path: Path,
    clip_geom,
    clip_crs,
    resampling=Resampling.nearest,
    force: bool = False,
):
    """
    Clip a statewide raster to a basin polygon + buffer.

    If ``dst_path`` already exists and ``force`` is False, the existing file
    is preserved (a log note is emitted).  Pass ``force=True`` to re-clip.
    Returns True on success, False if the statewide source is missing.
    """
    if dst_path.exists() and not force:
        size_mb = dst_path.stat().st_size / 1e6
        _log(f"    -> {dst_path.name} already present ({size_mb:.1f} MB) "
             f"- skipping (pass --force to rebuild)")
        return True

    src_path = STATEWIDE_DIR / src_name
    if not src_path.exists():
        _log(f"  WARNING: {src_path.name} not found in statewide/ - "
             f"run prep_statewide.py first")
        return False

    with rasterio.open(src_path) as src:
        geom_series = gpd.GeoSeries([clip_geom], crs=clip_crs)
        if not _crs_equal(geom_series.crs, src.crs):
            geom_series = geom_series.to_crs(src.crs)
        geom = [geom_series.iloc[0].__geo_interface__]

        out_image, out_transform = rio_mask(
            src, geom, crop=True, all_touched=True, nodata=src.nodata,
        )
        out_profile = src.profile.copy()
        out_profile.update(
            height=out_image.shape[1],
            width=out_image.shape[2],
            transform=out_transform,
            compress="DEFLATE",
            predictor=2,
        )

    with rasterio.open(dst_path, "w", **out_profile) as dst:
        dst.write(out_image)

    size_mb = dst_path.stat().st_size / 1e6
    _log(f"    -> {dst_path.name}  ({size_mb:.1f} MB)")
    return True


def _generate_default_config(basin_dir: Path, basin_key: str,
                             basin_id: str, basin_name: str,
                             treatment_name: str | None = None):
    """
    Write a default config.toml for a basin.

    An existing config.toml is never overwritten.  The one exception is the
    two ``# PLACE ...`` placeholders: once the ETg raster and treatment
    shapefile are in source/, re-running prep fills those in.  Any value you
    have set by hand stays as you left it.

    ``treatment_name`` (the --treatment-src subset) takes priority over the
    file-name scan below.
    """
    config_path = basin_dir / "config.toml"

    # Scan source/ (preferred) then input/ (legacy) for likely ETg + treatment files.
    source_dir = basin_dir / "source"
    input_dir = basin_dir / "input"
    search_dirs = [source_dir, input_dir] if source_dir.exists() else [input_dir]
    etg_candidates, shp_candidates = [], []
    for d in search_dirs:
        etg_candidates += sorted(d.glob("*etg*median*.tif")) + \
                          sorted(d.glob("*ETg*.tif"))
        shp_candidates += sorted(d.glob("*.shp"))

    treatment_shps = [s for s in shp_candidates
                      if any(kw in s.stem.lower()
                             for kw in ("etunit", "et_unit", "phreats", "treatment",
                                        "w_ag", "master"))]
    if not treatment_shps:
        treatment_shps = shp_candidates

    etg_tif = etg_candidates[0].name if etg_candidates else "# PLACE ETg RASTER HERE"
    treat_shp = treatment_shps[0].name if treatment_shps else "# PLACE TREATMENT SHP HERE"
    if treatment_name:
        treat_shp = treatment_name

    import basin_config as _bc

    if config_path.exists():
        filled = _bc.backfill_source_files(
            config_path, etg_tif=etg_tif, treatment_shp=treat_shp)
        if filled:
            _log(f"  config.toml already exists - filled in {', '.join(filled)} "
                 f"(your other edits are untouched)")
        else:
            _log("  config.toml already exists - preserving your edits")
        if treatment_name:
            from treatment_subset import check_config_points_at
            check_config_points_at(config_path, treatment_name)
        return

    # Render the config.toml from basins/_template/config.toml.  To change
    # defaults for new NWI basins, edit the template file - not this script.
    toml_content = _bc.render_config_template({
        "basin_key":         basin_key,
        "basin_id":          basin_id,
        "basin_name":        basin_name,
        "etg_tif":           etg_tif,
        "treatment_shp":     treat_shp,
        # NWI basins fall back to the statewide NWI shapefile, so we leave the
        # boundary_shp line commented out in the generated config.
        "boundary_shp_line": '# boundary_shp = "boundary.shp"',
    })

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(toml_content)
    _log("  -> config.toml generated from basins/_template/config.toml "
         "(review & edit before running fill)")


def prep_one_basin(
    basin_key: str,
    gdf_nwi: gpd.GeoDataFrame,
    *,
    force: bool = False,
    treatment_src: Path | None = None,
):
    """Set up a single basin directory: clip BpS + generate config.

    With ``treatment_src`` (a statewide treatment dataset), also write this
    basin's polygons to source/<basin_key>_treatment.shp.
    """
    _log(f"\n{'='*60}")
    _log(f"Preparing basin: {basin_key}")

    match = gdf_nwi[gdf_nwi[BASIN_KEY_FIELD] == basin_key]
    if len(match) == 0:
        _log(f"  ERROR: '{basin_key}' not found in NWI shapefile (Basin field)")
        return False
    row = match.iloc[0]
    basin_id = str(row[BASIN_ID_FIELD]).strip()
    basin_name = str(row[BASIN_NAME_FIELD]).strip()
    geom = row.geometry

    # Create directory structure:
    #   source/  -- user-supplied raws (ETg + treatment shp)
    #   input/   -- prep-generated BpS
    #   output/  -- fill outputs
    basin_dir = BASINS_DIR / basin_key
    source_dir = basin_dir / "source"
    input_dir = basin_dir / "input"
    output_dir = basin_dir / "output"
    source_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Buffer the basin geometry for BpS clipping
    clip_crs = gdf_nwi.crs
    if clip_crs is not None and clip_crs.is_geographic:
        geom_series = gpd.GeoSeries([geom], crs=clip_crs).to_crs("EPSG:5070")
        clip_geom = geom_series.iloc[0].buffer(BASIN_CLIP_BUFFER_M)
        clip_crs = geom_series.crs
    else:
        clip_geom = geom.buffer(BASIN_CLIP_BUFFER_M)

    # -- Clip BpS from statewide ---------------------------------------------
    _log("  Clipping BpS ...")
    bps_dst = input_dir / "BpS.tif"
    _clip_from_statewide("BpS_statewide.tif", bps_dst,
                         clip_geom, clip_crs, Resampling.nearest,
                         force=force)

    # Write QGIS-compatible symbology sidecars (.clr + .qml) and embed the
    # color table + RAT inside the GeoTIFF so the BpS raster renders with
    # LANDFIRE class names and colours in QGIS / ArcGIS.
    try:
        from bps_utils import (
            load_bps_lookup,
            write_bps_symbology,
            embed_bps_colortable_and_rat,
        )
        bps_lut = load_bps_lookup()
        if bps_lut and bps_dst.exists():
            embedded = embed_bps_colortable_and_rat(bps_dst, bps_lut)
            write_bps_symbology(bps_dst, bps_lut)
            if embedded:
                _log("    -> BpS.tif color table + RAT embedded; "
                     "BpS.clr + BpS.qml sidecars written")
            else:
                try:
                    from osgeo import gdal  # noqa: F401
                    why = "raster dtype is not integer"
                except ImportError:
                    why = ("the osgeo/gdal Python bindings are not installed; "
                           "conda install -c conda-forge gdal")
                _log(f"    -> BpS.clr + BpS.qml sidecars written "
                     f"(color table + RAT not embedded: {why})")
    except Exception as e:
        _log(f"    (BpS symbology skipped: {e})")

    # -- Subset statewide treatment polygons (optional) ----------------------
    treatment_name = None
    if treatment_src is not None:
        from treatment_subset import subset_treatment, subset_name, SubsetError
        _log(f"  Subsetting treatment polygons from {Path(treatment_src).name} ...")
        # Unbuffered basin polygon: only this basin's polygons, not neighbours'.
        try:
            t_dst = subset_treatment(treatment_src, geom, gdf_nwi.crs,
                                     source_dir / subset_name(basin_key),
                                     force=force)
            treatment_name = t_dst.name
        except SubsetError as e:
            _log(f"  WARNING: treatment subset skipped: {e}")

    # -- Generate config.toml ------------------------------------------------
    _generate_default_config(basin_dir, basin_key, basin_id, basin_name,
                             treatment_name=treatment_name)

    _log(f"  Done.  Place raw ETg raster and treatment shapefile in:\n"
         f"    {source_dir.resolve()}/\n"
         f"  Prep-generated BpS lives in:\n"
         f"    {input_dir.resolve()}/")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Clip BpS and generate config for one or more basins."
    )
    parser.add_argument("basins", nargs="*",
                        help="Basin key(s) from NWI shapefile Basin field "
                             "(e.g. 101_SierraValley)")
    parser.add_argument("--all", action="store_true",
                        help="Prep ALL basins in the NWI shapefile")
    parser.add_argument("--list", action="store_true",
                        help="List available basin keys and exit")
    parser.add_argument("--only-missing", action="store_true",
                        help="With --all: skip basins that already have BpS.tif "
                             "(and, with --treatment-src, a treatment subset)")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild BpS.tif (and the treatment subset) even "
                             "if it already exists.")
    parser.add_argument("--treatment-src", type=Path, default=None,
                        help="Statewide treatment dataset (phreatophyte + ag "
                             "polygons).  Each basin's overlapping polygons are "
                             "written to source/<basin_key>_treatment.shp.")
    args = parser.parse_args()

    if args.treatment_src is not None and not args.treatment_src.exists():
        sys.exit(f"ERROR: --treatment-src not found: {args.treatment_src}")

    gdf_nwi = _load_nwi()

    if args.list:
        keys = sorted(gdf_nwi[BASIN_KEY_FIELD].dropna().unique())
        print(f"\n{len(keys)} basins in NWI_Investigations_EPSG_32611.shp:\n")
        for k in keys:
            row = gdf_nwi[gdf_nwi[BASIN_KEY_FIELD] == k].iloc[0]
            print(f"  {k:40s}  ({row[BASIN_NAME_FIELD]})")
        return

    if not args.all and not args.basins:
        parser.print_help()
        sys.exit(1)

    if not (STATEWIDE_DIR / "BpS_statewide.tif").exists():
        _log("WARNING: statewide/BpS_statewide.tif not found - "
             "run prep_statewide.py first")

    t0 = time.time()
    BASINS_DIR.mkdir(parents=True, exist_ok=True)

    if args.all:
        keys = sorted(gdf_nwi[BASIN_KEY_FIELD].dropna().unique())
    else:
        keys = args.basins

    n_ok, n_fail = 0, 0
    for key in keys:
        if args.only_missing:
            bps_path = BASINS_DIR / key / "input" / "BpS.tif"
            done = bps_path.exists()
            if args.treatment_src is not None:
                from treatment_subset import subset_name
                done = done and (BASINS_DIR / key / "source" /
                                 subset_name(key)).exists()
            if done:
                continue
        if prep_one_basin(key, gdf_nwi, force=args.force,
                          treatment_src=args.treatment_src):
            n_ok += 1
        else:
            n_fail += 1

    _log(f"\n{'='*60}")
    _log(f"Prepped {n_ok} basins, {n_fail} failed.  "
         f"Elapsed: {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
