#!/usr/bin/env python3
"""
prep_statewide.py
=================
One-time script: clip the CONUS-wide LANDFIRE BpS raster to the dissolved
NWI investigation boundary (with buffer) so per-basin prep can use fast
windowed reads instead of touching the full CONUS file every time.  The
output is reprojected into the NWI shapefile CRS so downstream per-basin
prep operates on a single consistent grid.

BpS is the only covariate this workflow needs - the baseline is a
spatially weighted per-BpS-class mean, with no DEM or other terrain inputs.

Usage
-----
    python prep_statewide.py --bps /path/to/LF2020_BPS_CONUS.tif

Output is written to  <project>/statewide/BpS_statewide.tif
(plus statewide/bps_lookup.json with class names + colours).

License: MIT
"""

import argparse
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
    sys.exit(f"Missing dependency: {e}\nInstall: pip install rasterio geopandas shapely")


_here = Path(__file__).resolve().parent
PROJECT_DIR = _here
STATEWIDE_DIR = PROJECT_DIR / "statewide"
NWI_SHP = _here / "NWI_Investigations_EPSG_32611.shp"

# Buffer (meters) around the dissolved NWI boundary when clipping.  Ensures
# edge basins have BpS data right up to and slightly beyond their boundary so
# reprojection doesn't produce NaN strips.
CLIP_BUFFER_M = 10_000  # 10 km


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _crs_equal(a, b) -> bool:
    """Compare two CRS-like objects (rasterio.crs.CRS lacks ``.equals()``)."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return rasterio.crs.CRS.from_user_input(a) == \
               rasterio.crs.CRS.from_user_input(b)
    except Exception:
        return str(a) == str(b)


def _clip_raster_to_geometry(
    src_path: Path,
    dst_path: Path,
    clip_geom,
    clip_crs,
    target_crs=None,
    resampling=Resampling.nearest,
    label: str = "",
):
    """
    Clip a raster to a geometry and optionally reproject the clipped result
    into ``target_crs``.  The clip is done in the raster's native CRS to
    minimise resampling artefacts; the final output is then warped into the
    target CRS (by default the NWI shapefile CRS).  Writes a GeoTIFF with
    DEFLATE compression.
    """
    # Safety guard: never overwrite a user-supplied source raster in place.
    try:
        src_resolved = Path(src_path).resolve()
        dst_resolved = Path(dst_path).resolve()
    except Exception:
        src_resolved = Path(src_path)
        dst_resolved = Path(dst_path)
    if src_resolved == dst_resolved:
        sys.exit(
            f"ERROR: refusing to overwrite source raster in place.\n"
            f"  source: {src_path}\n"
            f"  destination: {dst_path}\n"
            f"  Supply a source path outside the project's statewide/ folder."
        )
    _log(f"  Clipping {label or src_path.name} ...")
    _log(f"    source:      {src_resolved}")
    _log(f"    destination: {dst_resolved}")

    with rasterio.open(src_path) as src:
        geom_series = gpd.GeoSeries([clip_geom], crs=clip_crs)
        if not _crs_equal(geom_series.crs, src.crs):
            geom_series_src = geom_series.to_crs(src.crs)
        else:
            geom_series_src = geom_series
        geom = [geom_series_src.iloc[0].__geo_interface__]

        clipped_image, clipped_transform = rio_mask(
            src, geom, crop=True, all_touched=True, nodata=src.nodata,
        )
        src_crs = src.crs
        src_nodata = src.nodata
        src_dtype = src.dtypes[0]
        src_count = src.count

    need_reproject = True
    if target_crs is None:
        need_reproject = False
    else:
        dst_crs = rasterio.crs.CRS.from_user_input(target_crs)
        if _crs_equal(dst_crs, src_crs):
            need_reproject = False

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


def main():
    parser = argparse.ArgumentParser(
        description="Clip the CONUS BpS raster to the NWI investigation extent."
    )
    parser.add_argument("--bps", type=Path, required=True,
                        help="Path to CONUS BpS raster (LANDFIRE LF2020)")
    parser.add_argument("--buffer-m", type=float, default=CLIP_BUFFER_M,
                        help=f"Buffer around NWI boundary (default: {CLIP_BUFFER_M} m)")
    args = parser.parse_args()

    t0 = time.time()
    STATEWIDE_DIR.mkdir(parents=True, exist_ok=True)

    # -- Load and dissolve NWI boundary --------------------------------------
    _log("Loading NWI investigation boundaries ...")
    if not NWI_SHP.exists():
        sys.exit(f"ERROR: NWI shapefile not found: {NWI_SHP}")

    gdf = gpd.read_file(NWI_SHP)
    _log(f"  {len(gdf)} basin polygons loaded")
    _log(f"  NWI shapefile CRS: {gdf.crs.to_string() if gdf.crs else 'UNKNOWN'}")

    dissolved = unary_union(gdf.geometry)
    if gdf.crs is not None and gdf.crs.is_geographic:
        _log("  WARNING: NWI shapefile is in geographic CRS - "
             "reprojecting to EPSG:5070 for buffering")
        gdf_proj = gdf.to_crs("EPSG:5070")
        dissolved = unary_union(gdf_proj.geometry)
        clip_crs = gdf_proj.crs
    else:
        clip_crs = gdf.crs

    clip_geom = dissolved.buffer(args.buffer_m)
    _log(f"  Dissolved + {args.buffer_m:.0f} m buffer ready")

    target_crs = gdf.crs
    _log(f"  Output CRS for statewide BpS: {target_crs.to_string()}")

    # -- Clip BpS ------------------------------------------------------------
    _log("Clipping BpS ...")
    if not args.bps.exists():
        sys.exit(f"ERROR: BpS raster not found: {args.bps}")
    bps_dst = STATEWIDE_DIR / "BpS_statewide.tif"
    _clip_raster_to_geometry(
        args.bps, bps_dst,
        clip_geom, clip_crs,
        target_crs=target_crs,
        resampling=Resampling.nearest,
        label="BpS",
    )

    # Extract BpS class names / colours from the CONUS source raster and cache
    # them as statewide/bps_lookup.json.  Downstream scripts (prep_basin,
    # etg_baseline_fill) use this lookup for symbology files and human-readable
    # class names in logs and metadata.
    _log("  Extracting BpS class lookup (names + colours) ...")
    try:
        from bps_utils import extract_bps_lookup
        bps_lut = extract_bps_lookup(args.bps)
        _log(f"    {len(bps_lut)} BpS classes extracted -> statewide/bps_lookup.json")
    except Exception as e:
        _log(f"    WARNING: could not extract BpS lookup: {e}")

    _log(f"\nStatewide BpS written to: {STATEWIDE_DIR.resolve()}")
    _log(f"  BpS_statewide.tif")
    _log(f"Elapsed: {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
