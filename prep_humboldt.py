"""
prep_humboldt.py — Stage Humboldt Basin training data (Huntington et al., 2022)
================================================================================

Adapts the Humboldt_Data/ bundle (one master shapefile + 35 per-HA ETg rasters)
into the per-basin BMM Raster Fill directory structure.

For each raster in Humboldt_Data/RASTERS:
  1. Parse the 1–3 digit HA number from the filename.
  2. Look up the canonical NWI basin key (e.g. "42" -> "042_MarysRiverArea")
     by joining on BasinID from NWI_Investigations_EPSG_32611.shp.
  3. Convert the raster from mm/yr to ft/yr (÷304.8).
  4. Write it to  basins/<KEY>/source/<KEY>_ETg_Huntington2022.tif

For each HA present in the Humboldt master shapefile:
  1. Subset features where HYD_AREA matches the HA number.
  2. Derive  rplc_rt = FixETg_mm / 304.8  (ft/yr, matches BMM convention).
  3. Ensure scale_fctr is present (it already is in the source).
  4. Write to  basins/<KEY>/source/<KEY>_treatment_Huntington2022.shp

Also drops a PROVENANCE.txt in each basin's source/ folder citing the report,
and patches any existing basin config.toml [source] section to point at the
new filenames (creating config.toml if missing via the existing template).

Usage
-----
    python prep_humboldt.py --dry-run          # preview only, write nothing
    python prep_humboldt.py                    # stage all 35 basins
    python prep_humboldt.py --only 053 061     # stage only these HA numbers
    python prep_humboldt.py --run-prep         # also invoke prep_basin.py after

Reference
---------
    Huntington, J.L., Bromley, M., and others, 2022.
    Groundwater discharge from phreatophyte vegetation, Humboldt River Basin,
    Nevada. Desert Research Institute, Publication No. 41288.
    https://www.dri.edu/project/humboldt-etg/
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling  # noqa: F401  (kept for future resampling use)
import geopandas as gpd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE          = Path(__file__).resolve().parent
HUMBOLDT_DIR  = HERE / "Humboldt_Data"
RASTER_DIR    = HUMBOLDT_DIR / "RASTERS"
SHAPE_FILE    = HUMBOLDT_DIR / "SHAPEFILE" / "Humboldt_ALL_INSIDE_DISS.shp"
NWI_SHP       = HERE / "NWI_Investigations_EPSG_32611.shp"
BASINS_DIR    = HERE / "basins"
TEMPLATE_TOML = BASINS_DIR / "_template" / "config.toml"

# Conversion constant: 1 foot = 304.8 mm
MM_PER_FT = 304.8

PROVENANCE = """\
Provenance
==========
Source:   Humboldt_Data/ (staged by prep_humboldt.py)
Report:   Huntington, J.L., Bromley, M., and others, 2022.
          Groundwater discharge from phreatophyte vegetation,
          Humboldt River Basin, Nevada.
          Desert Research Institute, Publication No. 41288.
URL:      https://www.dri.edu/project/humboldt-etg/

Files in this directory tagged with "_Huntington2022" originate from the
2022 Humboldt ETg report's training dataset. Raster ETg values were
converted from mm/yr to ft/yr (÷304.8) when staged. The treatment
shapefile is a per-HA subset of Humboldt_ALL_INSIDE_DISS.shp with a
derived rplc_rt column = FixETg_mm / 304.8.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Raster filenames look like:
#   42_marysriverarea_median.etg_mean.tif
#   131_buffalovalley_median.etg_mean.tif
#   73a_lovelockvalley_median.etg_mean.tif      (sub-basin with trailing letter)
# NWI BasinID uses uppercase suffix ("137A", "178A"), so we normalize to that.
_RASTER_RE = re.compile(
    r"^(\d{1,3})([a-zA-Z]?)_([a-z0-9]+)_median\.etg_mean\.tif$", re.IGNORECASE
)


def parse_raster_filename(fn: str) -> str | None:
    """Return the NWI-style BasinID (e.g. '042', '073A'), or None if not a match."""
    m = _RASTER_RE.match(fn)
    if not m:
        return None
    digits = m.group(1).zfill(3)
    suffix = m.group(2).upper()
    return digits + suffix


def build_nwi_lookup() -> dict[str, str]:
    """BasinID (e.g. '042') -> canonical Basin key (e.g. '042_MarysRiverArea')."""
    gdf = gpd.read_file(NWI_SHP)
    return dict(zip(gdf["BasinID"].astype(str).str.strip(),
                    gdf["Basin"].astype(str).str.strip()))


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def convert_raster_mm_to_ft(src: Path, dst: Path) -> tuple[int, float, float]:
    """Read src (mm/yr), write dst (ft/yr = src/304.8). Returns (n_valid, min, max)."""
    with rasterio.open(src) as ds:
        data = ds.read(1).astype("float32")
        profile = ds.profile.copy()
        nodata = ds.nodata

    if nodata is not None:
        mask = (data == nodata) | ~np.isfinite(data)
    else:
        mask = ~np.isfinite(data)

    out = np.where(mask, np.nan, data / MM_PER_FT).astype("float32")

    profile.update(
        dtype="float32",
        nodata=np.float32(np.nan),
        compress="DEFLATE",
        predictor=2,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )

    ensure_dir(dst.parent)
    with rasterio.open(dst, "w", **profile) as outds:
        outds.write(out, 1)
        outds.update_tags(
            units="ft/yr",
            source="Humboldt_Data (mm/yr)",
            conversion="divided by 304.8",
            provenance="Huntington et al. 2022 (DRI Pub 41288)",
        )

    valid = ~mask
    n = int(valid.sum())
    if n:
        vmin = float(np.nanmin(out))
        vmax = float(np.nanmax(out))
    else:
        vmin = vmax = float("nan")
    return n, vmin, vmax


def subset_treatment_shp(ha3: str, dst_base: Path) -> int:
    """Write a per-HA subset shapefile. Returns feature count (0 = nothing written)."""
    gdf = gpd.read_file(SHAPE_FILE)

    # HYD_AREA is already zero-padded 3-digit per my inspection; normalize
    # defensively in case some rows are read as ints or trimmed strings.
    gdf["HYD_AREA"] = gdf["HYD_AREA"].astype(str).str.strip().str.zfill(3)
    sub = gdf[gdf["HYD_AREA"] == ha3].copy()
    if sub.empty:
        return 0

    # Derive BMM-convention rplc_rt (ft/yr) from FixETg_mm (mm/yr).
    if "FixETg_mm" not in sub.columns:
        raise RuntimeError("FixETg_mm column not found; cannot derive rplc_rt")

    sub["rplc_rt"] = (sub["FixETg_mm"].astype(float) / MM_PER_FT).round(4)

    # scale_fctr should already be present; round for tidiness.
    if "scale_fctr" in sub.columns:
        sub["scale_fctr"] = sub["scale_fctr"].astype(float).round(4)
    else:
        sub["scale_fctr"] = 0.0

    ensure_dir(dst_base.parent)
    sub.to_file(dst_base, driver="ESRI Shapefile")
    return len(sub)


def patch_config_toml(config_path: Path, etg_name: str, treat_name: str) -> None:
    """Update [source] etg_tif and treatment_shp in an existing config.toml.

    If config.toml doesn't exist, a minimal one is rendered from the template
    with just these two fields filled in; prep_basin.py can overwrite the
    [inputs] section later.
    """
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        text = _replace_toml_field(text, "etg_tif",       etg_name)
        text = _replace_toml_field(text, "treatment_shp", treat_name)
        config_path.write_text(text, encoding="utf-8")
        return

    # No config.toml yet — write a minimal one; prep_basin.py will complete it.
    basin_key = config_path.parent.name
    stub = (
        f"[basin]\n"
        f"basin_key = \"{basin_key}\"\n\n"
        f"[source]\n"
        f"etg_tif       = \"{etg_name}\"\n"
        f"treatment_shp = \"{treat_name}\"\n"
    )
    config_path.write_text(stub, encoding="utf-8")


_FIELD_RE = {
    "etg_tif":       re.compile(r'^(\s*etg_tif\s*=\s*)"[^"]*"', re.MULTILINE),
    "treatment_shp": re.compile(r'^(\s*treatment_shp\s*=\s*)"[^"]*"', re.MULTILINE),
}


def _replace_toml_field(text: str, key: str, value: str) -> str:
    pat = _FIELD_RE[key]
    if pat.search(text):
        return pat.sub(rf'\1"{value}"', text)
    # Field missing — append under a [source] header if one exists, else add it.
    if re.search(r"^\[source\]", text, flags=re.MULTILINE):
        return re.sub(r"(^\[source\][^\[]*)",
                      lambda m: m.group(1).rstrip() + f'\n{key} = "{value}"\n',
                      text, count=1, flags=re.MULTILINE)
    return text + f'\n[source]\n{key} = "{value}"\n'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be staged; don't write anything.")
    ap.add_argument("--only", nargs="+", metavar="HA",
                    help="Process only these HA numbers (e.g. --only 53 131).")
    ap.add_argument("--run-prep", action="store_true",
                    help="After staging, invoke prep_basin.py for each basin.")
    args = ap.parse_args()

    if not RASTER_DIR.exists():
        sys.exit(f"ERROR: {RASTER_DIR} not found.")
    if not SHAPE_FILE.exists():
        sys.exit(f"ERROR: {SHAPE_FILE} not found.")
    if not NWI_SHP.exists():
        sys.exit(f"ERROR: {NWI_SHP} not found.")

    only = {x.zfill(3) for x in args.only} if args.only else None
    nwi = build_nwi_lookup()

    rasters = sorted(RASTER_DIR.glob("*.tif"))
    print(f"Found {len(rasters)} rasters in {RASTER_DIR.name}/")
    print(f"NWI lookup has {len(nwi)} basins")
    print(f"{'DRY RUN — nothing will be written.' if args.dry_run else 'Staging basins ...'}")
    print()

    ok, skipped, errors = 0, 0, 0
    staged_keys: list[str] = []

    for src in rasters:
        ha3 = parse_raster_filename(src.name)
        if ha3 is None:
            print(f"  SKIP (unparseable name): {src.name}")
            skipped += 1
            continue
        if only and ha3 not in only:
            continue

        key = nwi.get(ha3)
        if key is None:
            print(f"  SKIP (HA {ha3} not in NWI shapefile): {src.name}")
            skipped += 1
            continue

        source_dir = BASINS_DIR / key / "source"
        etg_name   = f"{key}_ETg_Huntington2022.tif"
        treat_name = f"{key}_treatment_Huntington2022.shp"
        etg_dst    = source_dir / etg_name
        treat_dst  = source_dir / treat_name

        print(f"• HA {ha3}  ->  {key}")
        print(f"    raster : {src.name}  ->  source/{etg_name}  (mm/yr -> ft/yr)")

        if args.dry_run:
            # Just count features for preview
            gdf_check = gpd.read_file(SHAPE_FILE, rows=0)  # schema-only is fine
            # Count via attribute query (cheap-ish)
            feat_count = int(
                (gpd.read_file(SHAPE_FILE)["HYD_AREA"]
                    .astype(str).str.strip().str.zfill(3) == ha3).sum()
            )
            print(f"    shapefile subset would contain {feat_count} features  ->  source/{treat_name}")
            print()
            ok += 1
            continue

        try:
            ensure_dir(source_dir)
            n_valid, vmin, vmax = convert_raster_mm_to_ft(src, etg_dst)
            print(f"    wrote raster: {n_valid:,} valid pixels, range {vmin:.3f} to {vmax:.3f} ft/yr")

            n_feat = subset_treatment_shp(ha3, treat_dst)
            if n_feat == 0:
                print(f"    WARNING: no shapefile features for HA {ha3}")
            else:
                print(f"    wrote shapefile: {n_feat} features")

            (source_dir / "PROVENANCE.txt").write_text(PROVENANCE, encoding="utf-8")

            config_path = BASINS_DIR / key / "config.toml"
            patch_config_toml(config_path, etg_name, treat_name)
            print(f"    config.toml [source] updated")

            staged_keys.append(key)
            ok += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            errors += 1
        print()

    print("=" * 60)
    print(f"Done.  staged: {ok}   skipped: {skipped}   errors: {errors}")

    if args.run_prep and staged_keys and not args.dry_run:
        print(f"\nRunning prep_basin.py on {len(staged_keys)} basins ...")
        for key in staged_keys:
            print(f"\n>>> prep_basin.py {key}")
            rc = subprocess.call([sys.executable, "prep_basin.py", key], cwd=str(HERE))
            if rc != 0:
                print(f"    prep_basin.py returned non-zero ({rc}) for {key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
