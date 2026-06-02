"""
synth_data.py
=============
Generate a small, self-contained synthetic study area for the pipeline smoke
test: a BpS raster, an ETg raster (with a simulated irrigation block), a basin
boundary, and a treatment shapefile.  No network access or external data needed.

All layers are written in EPSG:32611 (UTM 11N) so they align without
reprojection.  Used by test_pipeline_smoke.py; can also be run standalone:

    python tests/synth_data.py /some/output/dir
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS
import geopandas as gpd
from shapely.geometry import box


# Pixel grid: 90 x 90 at 30 m (2.7 km square), origin in UTM 11N.
X0, Y0 = 400_000.0, 4_500_000.0
RES = 30.0
H = W = 90
IRR0, IRR1 = 36, 54          # irrigated block (18x18 px) in the interior
CLASS_MEAN = {11: 1.4, 12: 0.9, 13: 0.6, 14: 1.1}   # base ETg per BpS class
CRS_UTM = CRS.from_epsg(32611)


def generate(dest: Path) -> dict:
    """Write synthetic layers into *dest* and return their paths."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)

    # -- BpS raster (padded so clipping has margin) --------------------------
    pad = 15
    Hb, Wb = H + 2 * pad, W + 2 * pad
    tb = from_origin(X0 - pad * RES, Y0 + pad * RES, RES, RES)
    bps = np.empty((Hb, Wb), dtype=np.int32)
    bps[: Hb // 2, : Wb // 2] = 11
    bps[: Hb // 2, Wb // 2:] = 12
    bps[Hb // 2:, : Wb // 2] = 13
    bps[Hb // 2:, Wb // 2:] = 14
    speckle = rng.random((Hb, Wb)) < 0.05
    bps[speckle] = rng.choice([11, 12, 13, 14], size=int(speckle.sum()))
    bps_path = dest / "bps.tif"
    with rasterio.open(bps_path, "w", driver="GTiff", height=Hb, width=Wb,
                       count=1, dtype="int32", crs=CRS_UTM, transform=tb,
                       nodata=0, compress="DEFLATE") as d:
        d.write(bps, 1)

    # -- ETg raster: class base + smooth gradient + noise + irrigation block --
    ys, _ = np.mgrid[0:H, 0:W]
    grad = 0.30 * (1 - ys / H)
    bps_aoi = bps[pad:pad + H, pad:pad + W]
    etg = np.zeros((H, W), dtype=np.float32)
    for c, m in CLASS_MEAN.items():
        etg[bps_aoi == c] = m
    etg = etg + grad + rng.normal(0, 0.05, (H, W)).astype(np.float32)
    etg = np.clip(etg, 0.05, None)
    etg[IRR0:IRR1, IRR0:IRR1] += 2.5      # irrigation inflation
    transform = from_origin(X0, Y0, RES, RES)
    etg_path = dest / "etg.tif"
    with rasterio.open(etg_path, "w", driver="GTiff", height=H, width=W,
                       count=1, dtype="float32", crs=CRS_UTM, transform=transform,
                       nodata=np.nan, compress="DEFLATE") as d:
        d.write(etg, 1)

    # -- Boundary shapefile (inset 3 px from the AOI edge) -------------------
    bx0, by0 = X0 + 3 * RES, Y0 - (H - 3) * RES
    bx1, by1 = X0 + (W - 3) * RES, Y0 - 3 * RES
    boundary_path = dest / "boundary.shp"
    gpd.GeoDataFrame({"name": ["SmokeTest"]},
                     geometry=[box(bx0, by0, bx1, by1)], crs=CRS_UTM
                     ).to_file(boundary_path)

    # -- Treatment shapefile -------------------------------------------------
    def px_poly(r0, r1, c0, c1):
        return box(X0 + c0 * RES, Y0 - r1 * RES, X0 + c1 * RES, Y0 - r0 * RES)

    treatment_path = dest / "treatment.shp"
    gpd.GeoDataFrame(
        {
            "ET_unit":    ["Cropland", "Pasture", "Phreatophyte"],
            "scale_fctr": [0.0, 0.7, 0.0],
            "rplc_rt":    [0.5, 0.0, 0.0],
            "adj_fctr":   [0.9, 0.0, 0.0],
            "DRI_ID":     ["T1", "T2", "U1"],
        },
        geometry=[px_poly(IRR0, IRR1, IRR0, IRR1),
                  px_poly(12, 22, 64, 80),
                  px_poly(70, 84, 8, 22)],
        crs=CRS_UTM,
    ).to_file(treatment_path)

    return {
        "bps": bps_path,
        "etg": etg_path,
        "boundary": boundary_path,
        "treatment": treatment_path,
        "irr_block": (IRR0, IRR1),
    }


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("synth_out")
    paths = generate(out)
    for k, v in paths.items():
        print(f"{k}: {v}")
