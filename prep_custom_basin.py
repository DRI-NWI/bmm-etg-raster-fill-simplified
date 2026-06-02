#!/usr/bin/env python3
"""
prep_custom_basin.py
====================
Set up a basin directory for a study area that is NOT part of the Nevada
NWI investigation basins.  This is the entry point for applying the ETg
baseline-fill workflow to any geographic area (e.g. Sierra Valley CA,
basins in other states, or international sites).

Unlike prep_basin.py, which clips BpS from a pre-built statewide subset and
reads basin boundaries from the NWI shapefile, this script:

    1. Accepts a user-provided boundary shapefile (or GeoJSON / GPKG).
    2. Clips BpS from a CONUS-scale (or any extent) source raster.
    3. Generates a config.toml identical in structure to prep_basin.py's.
    4. Copies the boundary shapefile into source/ so etg_baseline_fill.py
       can use it as the training mask (via the ``boundary_shp`` config
       field), removing the dependency on NWI_Investigations.

The resulting basin directory is indistinguishable from an NWI basin
directory - etg_baseline_fill.py, diagnostics.py, and etunit_summary.py
all work exactly the same way.

Usage
-----
    python prep_custom_basin.py SierraValley \\
        --boundary  /path/to/sierra_valley_boundary.shp \\
        --bps       /path/to/LF2020_BPS_CONUS.tif

Outputs
-------
    basins/<basin_key>/
        source/
            boundary.shp     (copy of your boundary)
        input/
            BpS.tif
            BpS.clr          (QGIS symbology, if bps_lookup.json exists)
            BpS.qml
        output/
        config.toml

After prep, place your ETg raster and treatment shapefile in source/,
review config.toml, and run:

    python etg_baseline_fill.py <basin_key>

License: MIT
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

try:
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    import geopandas as gpd
    from shapely.ops import unary_union
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\n"
             "Install: pip install rasterio geopandas shapely")

_here = Path(__file__).resolve().parent
PROJECT_DIR = _here
BASINS_DIR = PROJECT_DIR / "basins"

# Buffer around boundary when clipping BpS (meters).
CLIP_BUFFER_M = 5_000  # 5 km


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _crs_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return rasterio.crs.CRS.from_user_input(a) == \
               rasterio.crs.CRS.from_user_input(b)
    except Exception:
        return str(a) == str(b)


def _clip_raster(
    src_path: Path,
    dst_path: Path,
    clip_geom,
    clip_crs,
    target_crs,
    resampling=Resampling.nearest,
    label: str = "",
    force: bool = False,
):
    """
    Clip a raster to a geometry and reproject into target_crs.

    If ``dst_path`` already exists, return immediately unless ``force`` is
    True.  This lets users pre-populate input/ with data staged from
    another machine without re-running an expensive clip.
    """
    if dst_path.exists() and not force:
        size_mb = dst_path.stat().st_size / 1e6
        _log(f"  {label or src_path.name}: {dst_path.name} already present "
             f"({size_mb:.1f} MB) - skipping (use --force to rebuild)")
        return
    _log(f"  Clipping {label or src_path.name} ...")

    with rasterio.open(src_path) as src:
        geom_series = gpd.GeoSeries([clip_geom], crs=clip_crs)
        if not _crs_equal(geom_series.crs, src.crs):
            geom_series = geom_series.to_crs(src.crs)
        geom = [geom_series.iloc[0].__geo_interface__]

        clipped_image, clipped_transform = rio_mask(
            src, geom, crop=True, all_touched=True, nodata=src.nodata,
        )
        src_crs = src.crs
        src_nodata = src.nodata
        src_dtype = src.dtypes[0]
        src_count = src.count

    need_reproject = (target_crs is not None and
                      not _crs_equal(target_crs, src_crs))

    if not need_reproject:
        out_profile = {
            "driver": "GTiff",
            "dtype": src_dtype,
            "count": src_count,
            "crs": src_crs,
            "transform": clipped_transform,
            "width": clipped_image.shape[2],
            "height": clipped_image.shape[1],
            "nodata": src_nodata,
            "compress": "DEFLATE",
            "predictor": 2,
        }
        with rasterio.open(dst_path, "w", **out_profile) as dst:
            dst.write(clipped_image)
    else:
        dst_crs = rasterio.crs.CRS.from_user_input(target_crs)
        _log(f"    reprojecting {label or src_path.name} "
             f"from {src_crs.to_string()} -> {dst_crs.to_string()}")

        src_height = clipped_image.shape[1]
        src_width = clipped_image.shape[2]
        left, bottom, right, top = rasterio.transform.array_bounds(
            src_height, src_width, clipped_transform
        )

        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, src_width, src_height,
            left=left, bottom=bottom, right=right, top=top,
        )

        out_profile = {
            "driver": "GTiff",
            "dtype": src_dtype,
            "count": src_count,
            "crs": dst_crs,
            "transform": dst_transform,
            "width": dst_width,
            "height": dst_height,
            "nodata": src_nodata,
            "compress": "DEFLATE",
            "predictor": 2,
        }

        with rasterio.open(dst_path, "w", **out_profile) as dst:
            for b in range(1, src_count + 1):
                reproject(
                    source=clipped_image[b - 1],
                    destination=rasterio.band(dst, b),
                    src_transform=clipped_transform,
                    src_crs=src_crs,
                    src_nodata=src_nodata,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    dst_nodata=src_nodata,
                    resampling=resampling,
                )

    size_mb = dst_path.stat().st_size / 1e6
    _log(f"    -> {dst_path.name}  ({size_mb:.1f} MB)")


def _copy_boundary(boundary_path: Path, dest_dir: Path) -> Path:
    """
    Copy boundary shapefile (and its sidecar files) into ``dest_dir``
    (the basin's source/ directory).  Returns the destination .shp path.
    """
    stem = boundary_path.stem
    src_dir = boundary_path.parent
    dst_stem = "boundary"

    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
                ".geojson", ".gpkg"):
        src_file = src_dir / f"{stem}{ext}"
        if src_file.exists():
            dst_file = dest_dir / f"{dst_stem}{ext}"
            shutil.copy2(src_file, dst_file)

    if boundary_path.suffix.lower() in (".geojson", ".gpkg"):
        dst = dest_dir / f"{dst_stem}{boundary_path.suffix.lower()}"
        if not dst.exists():
            shutil.copy2(boundary_path, dst)
        return dst

    return dest_dir / f"{dst_stem}.shp"


def _generate_config(basin_dir: Path, basin_key: str, boundary_name: str):
    """Write a default config.toml for a custom basin."""
    config_path = basin_dir / "config.toml"
    if config_path.exists():
        _log("  config.toml already exists - preserving your edits")
        return

    source_dir = basin_dir / "source"
    input_dir = basin_dir / "input"
    search_dirs = [source_dir, input_dir] if source_dir.exists() else [input_dir]
    etg_candidates, shp_candidates = [], []
    for d in search_dirs:
        etg_candidates += sorted(d.glob("*etg*median*.tif")) + \
                          sorted(d.glob("*ETg*.tif"))
        shp_candidates += sorted(d.glob("*.shp"))
    treatment_shps = [s for s in shp_candidates
                      if s.stem != "boundary" and
                      any(kw in s.stem.lower()
                          for kw in ("etunit", "et_unit", "phreats",
                                     "treatment", "w_ag", "master"))]
    if not treatment_shps:
        treatment_shps = [s for s in shp_candidates if s.stem != "boundary"]

    etg_tif = etg_candidates[0].name if etg_candidates else "# PLACE ETg RASTER HERE"
    treat_shp = treatment_shps[0].name if treatment_shps else "# PLACE TREATMENT SHP HERE"

    import basin_config as _bc
    toml_content = _bc.render_config_template({
        "basin_key":         basin_key,
        "basin_id":          "",
        "basin_name":        basin_key,
        "etg_tif":           etg_tif,
        "treatment_shp":     treat_shp,
        # Custom basins always have an explicit boundary from --boundary.
        "boundary_shp_line": f'boundary_shp = "{boundary_name}"',
    })

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(toml_content)
    _log("  -> config.toml generated from basins/_template/config.toml "
         "(review & edit before running fill)")


def prep_custom_basin(
    basin_key: str,
    boundary_path: Path,
    bps_path: Path,
    *,
    buffer_m: float = CLIP_BUFFER_M,
    force: dict | None = None,
):
    """
    Set up a basin directory from user-provided inputs.

    Parameters
    ----------
    basin_key : str
        Directory name under basins/ (e.g. "SierraValley").
    boundary_path : Path
        Shapefile / GeoJSON / GPKG defining the study-area boundary.
    bps_path : Path
        BpS raster (any extent >= study area; will be clipped).
    buffer_m : float
        Buffer around boundary for BpS clipping (meters).
    """
    force = force or {}

    def _force(key: str) -> bool:
        return bool(force.get("all") or force.get(key))

    _log(f"\n{'='*60}")
    _log(f"Preparing custom basin: {basin_key}")

    # -- Read boundary -------------------------------------------------------
    if not boundary_path.exists():
        sys.exit(f"ERROR: boundary file not found: {boundary_path}")
    gdf_bnd = gpd.read_file(boundary_path)
    if len(gdf_bnd) == 0:
        sys.exit(f"ERROR: boundary file is empty: {boundary_path}")

    bnd_crs = gdf_bnd.crs
    if bnd_crs is None:
        sys.exit(f"ERROR: boundary file has no CRS: {boundary_path}")

    _log(f"  Boundary CRS: {bnd_crs.to_string()}")
    _log(f"  {len(gdf_bnd)} feature(s) in boundary")

    # Target CRS: use the boundary CRS if projected, else auto-pick a UTM zone.
    if bnd_crs.is_projected:
        target_crs = bnd_crs
    else:
        centroid = unary_union(gdf_bnd.geometry).centroid
        utm_zone = int((centroid.x + 180) / 6) + 1
        hemisphere = "north" if centroid.y >= 0 else "south"
        epsg = 32600 + utm_zone if hemisphere == "north" else 32700 + utm_zone
        target_crs = rasterio.crs.CRS.from_epsg(epsg)
        _log(f"  Boundary is geographic - auto-selected UTM: EPSG:{epsg}")

    _log(f"  Target CRS for basin: {target_crs.to_string()}")

    dissolved = unary_union(gdf_bnd.geometry)
    if bnd_crs.is_geographic:
        geom_series = gpd.GeoSeries([dissolved], crs=bnd_crs).to_crs(target_crs)
        dissolved_proj = geom_series.iloc[0]
        clip_crs = target_crs
    else:
        dissolved_proj = dissolved
        clip_crs = bnd_crs

    clip_geom = dissolved_proj.buffer(buffer_m)
    _log(f"  Clip buffer: {buffer_m:.0f} m")

    # -- Create directory structure ------------------------------------------
    basin_dir = BASINS_DIR / basin_key
    source_dir = basin_dir / "source"
    input_dir = basin_dir / "input"
    output_dir = basin_dir / "output"
    source_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Copy boundary into source/ ------------------------------------------
    _log("  Copying boundary into source/ ...")
    bnd_dst = _copy_boundary(boundary_path, source_dir)
    boundary_name = bnd_dst.name
    _log(f"    -> {boundary_name}")

    # -- Clip BpS ------------------------------------------------------------
    if not bps_path.exists():
        sys.exit(f"ERROR: BpS raster not found: {bps_path}")
    bps_dst = input_dir / "BpS.tif"
    _clip_raster(bps_path, bps_dst,
                 clip_geom, clip_crs, target_crs,
                 Resampling.nearest, "BpS",
                 force=_force("bps"))

    # Write QGIS symbology if a lookup is available
    def _apply_bps_symbology(lut):
        from bps_utils import write_bps_symbology, embed_bps_colortable_and_rat
        embedded = embed_bps_colortable_and_rat(bps_dst, lut)
        write_bps_symbology(bps_dst, lut)
        if embedded:
            _log("    -> BpS.tif color table + RAT embedded; "
                 "BpS.clr + BpS.qml sidecars written")
        else:
            _log("    -> BpS.clr + BpS.qml sidecars written (GDAL embed skipped)")

    try:
        from bps_utils import load_bps_lookup
        bps_lut = load_bps_lookup()
        if bps_lut and bps_dst.exists():
            _apply_bps_symbology(bps_lut)
    except Exception as e:
        _log(f"    (BpS symbology skipped: {e})")

    # If no cached lookup exists, try extracting from the source raster
    try:
        from bps_utils import extract_bps_lookup, load_bps_lookup as _reload
        if not _reload():
            _log("  Extracting BpS class lookup from source ...")
            extract_bps_lookup(bps_path)
            bps_lut = _reload()
            if bps_lut and bps_dst.exists():
                _apply_bps_symbology(bps_lut)
    except Exception:
        pass

    # -- Generate config.toml ------------------------------------------------
    _generate_config(basin_dir, basin_key, boundary_name)

    _log(f"\n  Done.  Place raw ETg raster and treatment shapefile in:\n"
         f"    {source_dir.resolve()}/\n"
         f"  (Prep-generated BpS is in {input_dir.resolve()}/)\n"
         f"  Then run:\n"
         f"    python etg_baseline_fill.py {basin_key}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Set up a basin directory for a custom (non-NWI) study area."
    )
    parser.add_argument("basin_key",
                        help="Name for this basin (used as directory name, "
                             "e.g. 'SierraValley')")
    parser.add_argument("--boundary", type=Path, required=True,
                        help="Shapefile / GeoJSON / GPKG defining the "
                             "study-area boundary polygon")
    parser.add_argument("--bps", type=Path, required=True,
                        help="BpS raster (any extent >= study area)")
    parser.add_argument("--buffer-m", type=float, default=CLIP_BUFFER_M,
                        help=f"Buffer around boundary for clipping "
                             f"(default: {CLIP_BUFFER_M} m)")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild BpS.tif even if already present")
    parser.add_argument("--force-bps", action="store_true", help="Rebuild BpS.tif")
    args = parser.parse_args()

    force_dict = {
        "all": bool(args.force),
        "bps": bool(args.force_bps),
    }

    t0 = time.time()
    BASINS_DIR.mkdir(parents=True, exist_ok=True)

    prep_custom_basin(
        basin_key=args.basin_key,
        boundary_path=args.boundary,
        bps_path=args.bps,
        buffer_m=args.buffer_m,
        force=force_dict,
    )

    _log(f"\nElapsed: {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
