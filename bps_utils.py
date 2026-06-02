"""
bps_utils.py  —  LANDFIRE BpS raster attribute table (RAT) utilities.

Extracts class names and colours from the source BpS raster and writes
QGIS-compatible symbology files alongside clipped basin BpS rasters so
they render with the original LANDFIRE colour palette.

Two sidecar formats are written:

    BpS.clr   — ESRI-style colour file (works in QGIS, ArcGIS, GDAL).
                Each line: ``VALUE  R  G  B  ALPHA  LABEL``
    BpS.qml   — QGIS layer style file with a paletted/unique-values
                renderer.  Loads automatically when the .tif is opened
                in QGIS (if the .qml shares the same stem).

Both are generated from the same lookup table.

Usage
-----
    from bps_utils import extract_bps_lookup, write_bps_symbology

    # One-time: extract from the source LANDFIRE raster
    lut = extract_bps_lookup(Path("statewide/BpS_statewide.tif"))

    # Per-basin: write sidecar files next to the clipped BpS
    write_bps_symbology(Path("basins/053_PineValley/input/BpS.tif"), lut)

License: MIT
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

# Type alias: code → (R, G, B, class_name)
BpsLookup = Dict[int, Tuple[int, int, int, str]]

# Default path for the cached lookup (written once by prep_statewide,
# read by prep_basin and etg_baseline_fill).
_DEFAULT_LUT_PATH = Path(__file__).resolve().parent / "statewide" / "bps_lookup.json"


def extract_bps_lookup(
    bps_path: Path,
    *,
    lut_cache: Optional[Path] = None,
) -> BpsLookup:
    """
    Extract class names and colours from a BpS GeoTIFF.

    LANDFIRE BpS rasters carry a GDAL Raster Attribute Table (RAT) with
    columns like ``BPS_NAME``, ``R``, ``G``, ``B``.  If the RAT is absent
    (common after reprojection or format conversion), we fall back to the
    GDAL colour table if present.

    The result is cached to ``lut_cache`` (default: statewide/bps_lookup.json)
    so downstream scripts don't need to re-read the source raster.

    Parameters
    ----------
    bps_path : Path
        BpS raster (statewide or CONUS).
    lut_cache : Path, optional
        Where to write the JSON cache.  ``None`` disables caching.

    Returns
    -------
    BpsLookup
        {code: (R, G, B, class_name), ...}
    """
    import rasterio

    lut: BpsLookup = {}

    # ── Try GDAL RAT first (osgeo.gdal, independent of rasterio) ──────
    # LANDFIRE BpS rasters carry a Raster Attribute Table with columns
    # BPS_NAME, R, G, B, etc.  rasterio doesn't expose the RAT, so we
    # open the file with GDAL directly.
    try:
        from osgeo import gdal
        ds = gdal.Open(str(bps_path))
        if ds is not None:
            band = ds.GetRasterBand(1)
            rat = band.GetDefaultRAT() if band else None
            if rat and rat.GetRowCount() > 0:
                col_idx = {}
                for c in range(rat.GetColumnCount()):
                    col_idx[rat.GetNameOfCol(c).upper()] = c

                name_col = None
                for candidate in ("BPS_NAME", "CLASSNAMES", "VALUE",
                                  "CLASS_NAME", "NAME"):
                    if candidate in col_idx:
                        name_col = col_idx[candidate]
                        break

                r_col = col_idx.get("R") or col_idx.get("RED")
                g_col = col_idx.get("G") or col_idx.get("GREEN")
                b_col = col_idx.get("B") or col_idx.get("BLUE")

                for row in range(rat.GetRowCount()):
                    code = int(rat.GetValueAsDouble(row, col_idx.get("VALUE", 0)))
                    if code == 0:
                        continue
                    r = int(rat.GetValueAsDouble(row, r_col)) if r_col is not None else 200
                    g = int(rat.GetValueAsDouble(row, g_col)) if g_col is not None else 200
                    b = int(rat.GetValueAsDouble(row, b_col)) if b_col is not None else 200
                    name = (rat.GetValueAsString(row, name_col)
                            if name_col is not None else f"BpS {code}")
                    lut[code] = (r, g, b, name)
            ds = None  # close GDAL dataset
    except Exception:
        pass  # GDAL not available or RAT missing — try colour table next

    # ── Fall back to rasterio colour table ─────────────────────────────
    if not lut:
        with rasterio.open(bps_path) as src:
            try:
                cmap = src.colormap(1)  # {pixel_value: (R, G, B, A)}
                if cmap:
                    for code, rgba in cmap.items():
                        if code == 0:
                            continue
                        r, g, b = rgba[0], rgba[1], rgba[2]
                        lut[code] = (r, g, b, f"BpS {code}")
            except Exception:
                pass

    # ── Last resort: enumerate unique values with grey palette ──────
    if not lut:
        with rasterio.open(bps_path) as src:
            arr = src.read(1)
        codes = np.unique(arr)
        codes = codes[(codes > 0) & (codes < 65535)]
        for i, code in enumerate(codes):
            grey = 50 + int(200 * i / max(len(codes) - 1, 1))
            lut[int(code)] = (grey, grey, grey, f"BpS {int(code)}")

    # Cache the lookup
    if lut_cache is None:
        lut_cache = _DEFAULT_LUT_PATH
    if lut_cache:
        lut_cache.parent.mkdir(parents=True, exist_ok=True)
        serialisable = {str(k): list(v) for k, v in lut.items()}
        lut_cache.write_text(json.dumps(serialisable, indent=2),
                             encoding="utf-8")

    return lut


def load_bps_lookup(lut_path: Optional[Path] = None) -> BpsLookup:
    """
    Load a previously cached BpS lookup table from JSON.

    Parameters
    ----------
    lut_path : Path, optional
        Path to the JSON cache.  Defaults to statewide/bps_lookup.json.

    Returns
    -------
    BpsLookup  or empty dict if file doesn't exist.
    """
    if lut_path is None:
        lut_path = _DEFAULT_LUT_PATH
    if not lut_path.exists():
        return {}
    raw = json.loads(lut_path.read_text(encoding="utf-8"))
    return {int(k): tuple(v) for k, v in raw.items()}


def write_bps_symbology(bps_tif: Path, lut: BpsLookup) -> None:
    """
    Write QGIS-compatible sidecar symbology files next to a BpS raster.

    Creates:
        <stem>.clr  — ESRI colour file
        <stem>.qml  — QGIS layer style (paletted unique-values)

    Only codes actually present in the raster are included.

    Parameters
    ----------
    bps_tif : Path
        The BpS GeoTIFF to write symbology for.
    lut : BpsLookup
        Full lookup from extract_bps_lookup() or load_bps_lookup().
    """
    import rasterio

    if not lut or not bps_tif.exists():
        return

    # Find which codes are actually in this raster
    with rasterio.open(bps_tif) as src:
        arr = src.read(1)
    present_codes = set(np.unique(arr)) - {0}
    if not present_codes:
        return

    stem = bps_tif.with_suffix("")  # e.g. /path/to/BpS

    # ── .clr (ESRI colour file) ────────────────────────────────────────
    clr_lines = []
    for code in sorted(present_codes):
        if code in lut:
            r, g, b, name = lut[code]
        else:
            r, g, b, name = 180, 180, 180, f"BpS {code}"
        clr_lines.append(f"{code} {r} {g} {b} 255 {name}")

    clr_path = stem.with_suffix(".clr")
    clr_path.write_text("\n".join(clr_lines) + "\n", encoding="utf-8")

    # ── .qml (QGIS style) ─────────────────────────────────────────────
    qml_entries = []
    for code in sorted(present_codes):
        if code in lut:
            r, g, b, name = lut[code]
        else:
            r, g, b, name = 180, 180, 180, f"BpS {code}"
        # Escape XML special chars in name
        safe_name = (name.replace("&", "&amp;")
                         .replace("<", "&lt;")
                         .replace(">", "&gt;")
                         .replace('"', "&quot;"))
        qml_entries.append(
            f'        <paletteEntry value="{code}" '
            f'color="#{r:02x}{g:02x}{b:02x}" alpha="255" '
            f'label="{safe_name}"/>'
        )

    qml_content = f"""\
<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="AllStyleCategories">
  <pipe>
    <rasterrenderer type="paletted" band="1" opacity="1">
      <colorPalette>
{chr(10).join(qml_entries)}
      </colorPalette>
    </rasterrenderer>
  </pipe>
</qgis>
"""
    qml_path = stem.with_suffix(".qml")
    qml_path.write_text(qml_content, encoding="utf-8")


def embed_bps_colortable_and_rat(bps_tif: Path, lut: BpsLookup) -> bool:
    """
    Embed a GDAL color table and Raster Attribute Table into a clipped
    BpS GeoTIFF so it auto-renders in QGIS/ArcGIS with LANDFIRE class
    names and colours — exactly like the original CONUS source.

    rasterio's ``profile`` copy does NOT carry the color table or RAT
    across when a raster is clipped/reprojected, so we re-attach them
    here using GDAL directly.

    Only codes actually present in the raster are included in the RAT
    (keeps the attribute table compact).  The color table is attached
    for every code in ``lut`` (the extras are harmless).

    Returns True on success, False if GDAL isn't available or the
    raster dtype isn't integer (paletted rendering requires an integer
    band).
    """
    if not lut or not bps_tif.exists():
        return False

    try:
        from osgeo import gdal
    except Exception:
        return False

    ds = gdal.Open(str(bps_tif), gdal.GA_Update)
    if ds is None:
        return False
    band = ds.GetRasterBand(1)

    # Paletted rendering requires an integer band.  If the clip produced
    # a float raster (shouldn't happen with Resampling.nearest but just
    # in case), bail out — the .qml sidecar is the best we can do.
    dt = gdal.GetDataTypeName(band.DataType)
    if dt not in ("Byte", "UInt16", "Int16", "UInt32", "Int32"):
        ds = None
        return False

    # ── Color table ────────────────────────────────────────────────────
    ct = gdal.ColorTable()
    # Start with a neutral default (prevents uninitialised entries from
    # showing up black).
    for i in range(256 if dt == "Byte" else 0, 0):
        ct.SetColorEntry(i, (0, 0, 0, 0))
    for code, (r, g, b, _name) in lut.items():
        if 0 <= int(code) <= 65535:
            ct.SetColorEntry(int(code), (int(r), int(g), int(b), 255))
    band.SetColorTable(ct)
    band.SetColorInterpretation(gdal.GCI_PaletteIndex)

    # ── Raster Attribute Table (RAT) ───────────────────────────────────
    # Determine which codes are actually present so the RAT stays small.
    import numpy as _np
    arr = band.ReadAsArray()
    present = sorted(int(c) for c in _np.unique(arr) if int(c) != 0)

    rat = gdal.RasterAttributeTable()
    rat.CreateColumn("VALUE",    gdal.GFT_Integer, gdal.GFU_MinMax)
    rat.CreateColumn("R",        gdal.GFT_Integer, gdal.GFU_Red)
    rat.CreateColumn("G",        gdal.GFT_Integer, gdal.GFU_Green)
    rat.CreateColumn("B",        gdal.GFT_Integer, gdal.GFU_Blue)
    rat.CreateColumn("BPS_NAME", gdal.GFT_String,  gdal.GFU_Name)

    rat.SetRowCount(len(present))
    for i, code in enumerate(present):
        if code in lut:
            r, g, b, name = lut[code]
        else:
            r, g, b, name = 180, 180, 180, f"BpS {code}"
        rat.SetValueAsInt(i, 0, int(code))
        rat.SetValueAsInt(i, 1, int(r))
        rat.SetValueAsInt(i, 2, int(g))
        rat.SetValueAsInt(i, 3, int(b))
        rat.SetValueAsString(i, 4, str(name))

    band.SetDefaultRAT(rat)

    band.FlushCache()
    ds.FlushCache()
    ds = None
    return True


def bps_name(code: int, lut: Optional[BpsLookup] = None) -> str:
    """Return the human-readable class name for a BpS code, or 'BpS <code>'."""
    if lut is None:
        lut = load_bps_lookup()
    if code in lut:
        return lut[code][3]
    return f"BpS {code}"
