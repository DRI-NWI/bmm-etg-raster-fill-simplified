#!/usr/bin/env python3
"""
treatment_subset.py
===================
Cut a basin's treatment polygons out of a larger (e.g. statewide) treatment
dataset, so each basin works from its own small shapefile in source/.

Why: etg_baseline_fill.py reads every polygon in the treatment shapefile,
reprojects them, and in step 8 rasterizes them one at a time onto the basin
grid.  Pointed at a statewide phreatophyte + ag dataset, that loop runs over
tens of thousands of polygons that never touch the basin.  A shared statewide
file also collects every basin's ``{key}_rates_adjust.shp`` in one folder.

Selection rule
--------------
A polygon is kept when it overlaps the basin area (intersects, and does not
merely share an edge or corner).  Kept polygons stay WHOLE: they are not
clipped at the basin line, so their geometry and attributes match the
statewide source exactly.  The fill only uses the part that falls on the ETg
grid anyway.  Each kept row gets a ``src_fid`` column holding its row number
in the source file, so edits can be joined back to the statewide dataset.

Used by prep_basin.py and prep_custom_basin.py (``--treatment-src``).  Can
also be run on its own:

    python treatment_subset.py C:\\data\\NV_phreats_statewide.shp ^
        --boundary C:\\data\\basin_outline.shp ^
        --out basins\\MyBasin\\source\\MyBasin_treatment.shp

License: MIT
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    import geopandas as gpd
    import shapely
    from shapely.ops import unary_union
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nInstall: pip install geopandas shapely")


# Column added to the subset: row number of the polygon in the source file.
SRC_FID_COL = "src_fid"

# Shapefile field names are limited to 10 characters.
_SHP_FIELD_MAX = 10


class SubsetError(RuntimeError):
    """The subset could not be built (missing source, no CRS, no overlap)."""


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def subset_name(basin_key: str) -> str:
    """Standard file name for a basin's subset (contains 'treatment' so the
    prep scripts' config auto-detection recognises it)."""
    return f"{basin_key}_treatment.shp"


def _is_stale(dst: Path, src: Path) -> bool:
    """True if dst is missing or older than src."""
    if not dst.exists():
        return True
    try:
        return dst.stat().st_mtime < src.stat().st_mtime
    except OSError:
        return True


def subset_treatment(
    src_path: Path,
    area_geom,
    area_crs,
    dst_path: Path,
    *,
    force: bool = False,
) -> Path:
    """
    Write the polygons of ``src_path`` that overlap ``area_geom`` to
    ``dst_path`` (ESRI Shapefile).

    Parameters
    ----------
    src_path : Path
        Large treatment dataset (any format geopandas reads: .shp, .gpkg, ...).
    area_geom : shapely geometry
        Basin outline.  Use the unbuffered basin polygon.
    area_crs : CRS-like
        CRS of ``area_geom``.
    dst_path : Path
        Output shapefile.  Overwritten when older than ``src_path`` or when
        ``force`` is True; otherwise left as is.

    Returns the output path.  Raises SubsetError if the source is missing,
    has no CRS, or has no polygons overlapping the basin.
    """
    src_path, dst_path = Path(src_path), Path(dst_path)
    if not src_path.exists():
        raise SubsetError(f"treatment source not found: {src_path}")

    if not force and not _is_stale(dst_path, src_path):
        _log(f"    -> {dst_path.name} already present and newer than "
             f"{src_path.name} - skipping (pass --force to rebuild)")
        return dst_path

    area = gpd.GeoSeries([area_geom], crs=area_crs)

    # Bounding-box read: only features near the basin come off disk.
    # geopandas reprojects the bbox GeoSeries into the file's CRS.
    # fid_as_index (pyogrio engine) puts each feature's source row number in
    # the index, which becomes src_fid.  The fiona engine lacks it.
    _log(f"    reading {src_path.name} within the basin bounding box ...")
    try:
        gdf = gpd.read_file(src_path, bbox=area, fid_as_index=True)
    except TypeError:
        gdf = gpd.read_file(src_path, bbox=area)
        _log("    note: src_fid is the order within the bounding-box read, "
             "not the source row number (install pyogrio for true FIDs)")
    if gdf.crs is None:
        raise SubsetError(f"{src_path.name} has no CRS; cannot match it to "
                          f"the basin outline.  Define its projection first.")

    area_src = area.to_crs(gdf.crs).iloc[0] if area.crs is not None else area.iloc[0]

    # Predicates run on a repaired copy so a few bad rings in a statewide
    # dataset do not stop the run; the written geometry is the original.
    geom_ok = gdf.geometry.notna() & ~gdf.geometry.is_empty
    test_geom = gdf.geometry.copy()
    test_geom[geom_ok] = shapely.make_valid(gdf.geometry[geom_ok].values)
    keep = geom_ok & test_geom.intersects(area_src) & ~test_geom.touches(area_src)

    sub = gdf[keep].copy()
    n_bbox = len(gdf)
    if len(sub) == 0:
        raise SubsetError(f"no polygons in {src_path.name} overlap the "
                          f"basin outline (checked {n_bbox:,} near its "
                          f"bounding box).  Check that both layers cover the "
                          f"same area and CRS.")

    n_cross = int((~test_geom[keep].within(area_src)).sum())
    n_invalid = int((~sub.geometry.is_valid).sum())

    if SRC_FID_COL in sub.columns:
        _log(f"    note: source already has a '{SRC_FID_COL}' column - "
             f"leaving it as is")
    else:
        sub.insert(0, SRC_FID_COL, sub.index.astype("int64"))
    sub = sub.reset_index(drop=True)

    long_cols = [c for c in sub.columns
                 if c != "geometry" and len(c) > _SHP_FIELD_MAX]
    if long_cols:
        _log(f"    WARNING: shapefile field names are cut to "
             f"{_SHP_FIELD_MAX} characters; these will be renamed: "
             f"{', '.join(long_cols)}.  Check that the attribute names in "
             f"config.toml still match.")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    sub.to_file(dst_path)

    _log(f"    -> {dst_path.name}  ({len(sub):,} polygons kept of "
         f"{n_bbox:,} near the basin; {n_cross:,} cross the basin line and "
         f"are kept whole)")
    if n_invalid:
        _log(f"    note: {n_invalid:,} kept polygon(s) have invalid geometry; "
             f"the fill skips invalid polygons, so repair them in the source")
    return dst_path


def check_config_points_at(config_path: Path, treat_name: str) -> None:
    """
    After prep, warn if an existing config.toml names a different treatment
    shapefile than the subset just written.  The prep scripts never overwrite
    a value you set by hand, so this tells you which line to change.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        return
    import basin_config as _bc
    m = _bc._SOURCE_FIELD_RE["treatment_shp"].search(
        config_path.read_text(encoding="utf-8"))
    if m is None or _bc.is_placeholder(m.group(2)):
        return
    current = m.group(2)
    if Path(current).name != treat_name:
        _log(f"  NOTE: config.toml uses treatment_shp = \"{current}\", not the "
             f"new subset.  To use the subset, set:")
        _log(f"        treatment_shp = \"{treat_name}\"")


def main():
    parser = argparse.ArgumentParser(
        description="Cut one basin's treatment polygons out of a statewide "
                    "treatment dataset.")
    parser.add_argument("src", type=Path,
                        help="Statewide treatment dataset (.shp, .gpkg, ...)")
    parser.add_argument("--boundary", type=Path, required=True,
                        help="Basin outline (all features are dissolved)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output shapefile path")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild the output even if it is up to date")
    args = parser.parse_args()

    gdf_bnd = gpd.read_file(args.boundary)
    if len(gdf_bnd) == 0:
        sys.exit(f"ERROR: boundary file is empty: {args.boundary}")
    if gdf_bnd.crs is None:
        sys.exit(f"ERROR: boundary file has no CRS: {args.boundary}")

    t0 = time.time()
    _log(f"Subsetting {args.src.name} to {args.boundary.name} ...")
    try:
        subset_treatment(args.src, unary_union(gdf_bnd.geometry), gdf_bnd.crs,
                         args.out, force=args.force)
    except SubsetError as e:
        sys.exit(f"ERROR: {e}")
    _log(f"Elapsed: {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
