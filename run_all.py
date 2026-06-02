#!/usr/bin/env python3
"""
run_all.py
==========
Orchestrator: run the ETg baseline-fill pipeline for one, several, or all
basins that have a ``config.toml`` under ``basins/``.

For each basin the workflow is:
  1. prep    - clip BpS from statewide (if BpS.tif missing in input/)
  2. fill    - run etg_baseline_fill.py
  3. diag    - run diagnostics.py
  4. summary - run etunit_summary.py

Usage
-----
    # Run everything for all configured basins:
    python run_all.py

    # Run specific basins:
    python run_all.py 101_SierraValley 053_PineValley

    # Prep only (clip BpS + generate configs, no fill):
    python run_all.py --prep-only

    # Fill + diagnostics only (skip prep, skip summary):
    python run_all.py --skip-prep --skip-summary

    # Dry run - show what would be processed:
    python run_all.py --dry-run

    # List all basins with config.toml:
    python run_all.py --list

License: MIT
"""

import argparse
import sys
import time
import traceback
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _discover_basins(basins_dir: Path) -> list[str]:
    """Return sorted list of basin keys that have a config.toml."""
    if not basins_dir.exists():
        return []
    return sorted(
        d.name for d in basins_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
        and (d / "config.toml").exists()
    )


def _basin_needs_prep(basins_dir: Path, key: str) -> bool:
    """True if BpS hasn't been clipped yet."""
    input_dir = basins_dir / key / "input"
    return not (input_dir / "BpS.tif").exists()


def _basin_ready(basins_dir: Path, key: str) -> tuple[bool, list[str]]:
    """
    Check if a basin has all required inputs to run the fill.
    Returns (ready, list_of_missing_items).
    """
    basin_dir = basins_dir / key
    input_dir = basin_dir / "input"
    source_dir = basin_dir / "source"
    search_dirs = [source_dir, input_dir] if source_dir.exists() else [input_dir]
    missing = []

    # BpS (prep-generated covariate) lives in input/
    if not (input_dir / "BpS.tif").exists():
        missing.append("BpS.tif")

    # ETg raster + treatment shapefile (user-supplied) live in source/
    tifs, shps = [], []
    for d in search_dirs:
        tifs += list(d.glob("*etg*.tif")) + list(d.glob("*ETg*.tif"))
        shps += [s for s in d.glob("*.shp") if s.stem != "boundary"]
    if not tifs:
        missing.append("ETg raster (no *etg*.tif found)")
    if not shps:
        missing.append("treatment shapefile (no .shp found)")
    return (len(missing) == 0, missing)


def main():
    project_dir = _here
    basins_dir = project_dir / "basins"

    parser = argparse.ArgumentParser(
        description="Run ETg baseline-fill pipeline for one or more basins."
    )
    parser.add_argument("basins", nargs="*",
                        help="Basin key(s) to process. If omitted, runs all "
                             "basins with config.toml.")
    parser.add_argument("--list", action="store_true",
                        help="List configured basins and their readiness")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without running")
    parser.add_argument("--prep-only", action="store_true",
                        help="Only run BpS prep + config generation")
    parser.add_argument("--skip-prep", action="store_true",
                        help="Skip BpS prep step")
    parser.add_argument("--skip-diag", action="store_true",
                        help="Skip diagnostics step")
    parser.add_argument("--skip-summary", action="store_true",
                        help="Skip ET unit summary step")
    args = parser.parse_args()

    # -- List mode -----------------------------------------------------------
    if args.list:
        keys = _discover_basins(basins_dir)
        if not keys:
            print(f"No basins found in {basins_dir}")
            print("Run prep_basin.py to set up basin directories first.")
            return
        print(f"\n{len(keys)} basins with config.toml:\n")
        for k in keys:
            ready, missing = _basin_ready(basins_dir, k)
            status = "READY" if ready else f"missing: {', '.join(missing)}"
            print(f"  {k:45s}  {status}")
        return

    # -- Determine which basins to process -----------------------------------
    if args.basins:
        keys = args.basins
    else:
        keys = _discover_basins(basins_dir)

    if not keys:
        print("No basins to process.")
        print("  Set up basins with: python prep_basin.py --all")
        return

    # -- Dry run -------------------------------------------------------------
    if args.dry_run:
        print(f"\nDry run - would process {len(keys)} basins:\n")
        for k in keys:
            needs_prep = _basin_needs_prep(basins_dir, k)
            ready, missing = _basin_ready(basins_dir, k)
            prep_note = " (needs prep)" if needs_prep else ""
            status = "ready" if ready else f"missing: {', '.join(missing)}"
            print(f"  {k:45s}  {status}{prep_note}")
        return

    # -- Run pipeline --------------------------------------------------------
    t0 = time.time()
    results = {"ok": [], "skip": [], "fail": []}

    for i, key in enumerate(keys, 1):
        _log(f"\n{'='*70}")
        _log(f"[{i}/{len(keys)}]  Basin: {key}")
        _log(f"{'='*70}")

        try:
            # -- 1. Prep ----------------------------------------------------
            if not args.skip_prep and _basin_needs_prep(basins_dir, key):
                _log("Step 1: Prepping BpS ...")
                import prep_basin
                import geopandas as gpd
                gdf_nwi = gpd.read_file(prep_basin.NWI_SHP)
                prep_basin.prep_one_basin(key, gdf_nwi)

            if args.prep_only:
                results["ok"].append(key)
                continue

            # -- Check readiness --------------------------------------------
            ready, missing = _basin_ready(basins_dir, key)
            if not ready:
                _log(f"  SKIPPING - missing inputs: {', '.join(missing)}")
                results["skip"].append((key, missing))
                continue

            # -- 2. Fill ----------------------------------------------------
            _log("Step 2: Running ETg baseline fill ...")
            import etg_baseline_fill
            etg_baseline_fill.main(key)

            skip_marker = basins_dir / key / "output" / f"{key}_SKIPPED.txt"
            if skip_marker.exists():
                _log(f"  Basin was skipped (see {skip_marker.name})")
                results["ok"].append(key)
                continue

            # -- 3. Diagnostics ---------------------------------------------
            if not args.skip_diag:
                _log("Step 3: Running diagnostics ...")
                import diagnostics
                diagnostics.main(key)

            # -- 4. ET unit summary -----------------------------------------
            if not args.skip_summary:
                _log("Step 4: Running ET unit summary ...")
                import etunit_summary
                try:
                    etunit_summary.main(key)
                except Exception as e:
                    _log(f"  WARNING: ET unit summary failed: {e}")
                    _log("  (continuing - this is non-critical)")

            results["ok"].append(key)

        except SystemExit as e:
            _log(f"  FAILED (sys.exit): {e}")
            results["fail"].append((key, str(e)))
        except Exception as e:
            _log(f"  FAILED: {e}")
            traceback.print_exc()
            results["fail"].append((key, str(e)))

    # -- Summary -------------------------------------------------------------
    _log(f"\n{'='*70}")
    _log(f"Pipeline complete.  Elapsed: {time.time() - t0:.1f} s")
    _log(f"  Succeeded: {len(results['ok'])}")
    if results["skip"]:
        _log(f"  Skipped:   {len(results['skip'])}")
        for key, missing in results["skip"]:
            _log(f"    {key}: {', '.join(missing)}")
    if results["fail"]:
        _log(f"  Failed:    {len(results['fail'])}")
        for key, err in results["fail"]:
            _log(f"    {key}: {err}")

    # -- Cross-basin summary CSV ---------------------------------------------
    if not args.prep_only and results["ok"]:
        _build_cross_basin_summary(basins_dir, results["ok"])


def _parse_metadata(meta_path: Path) -> dict:
    """
    Parse a basin's run_metadata.txt into a flat dict of key=value pairs.
    Handles the simple INI-like format without needing configparser.
    """
    data = {}
    if not meta_path.exists():
        return data
    for line in meta_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            # Strip any trailing inline "# comment" from the value.
            val = val.partition("#")[0].strip()
            data[key.strip()] = val
    return data


def _build_cross_basin_summary(basins_dir: Path, basin_keys: list[str]):
    """
    After all basins complete, collect key metrics from each basin's
    run_metadata.txt into a single cross_basin_summary.csv.
    """
    import csv as _csv

    _log("\nBuilding cross-basin summary ...")

    rows = []
    for key in sorted(basin_keys):
        out_dir = basins_dir / key / "output"
        meta_files = list(out_dir.glob("*_run_metadata.txt"))
        if not meta_files:
            skip_files = list(out_dir.glob("*_SKIPPED.txt"))
            if skip_files:
                rows.append({"basin_key": key, "status": "skipped"})
            continue

        meta = _parse_metadata(meta_files[0])
        rows.append({
            "basin_key": key,
            "status": "ok",
            "training_pixels": meta.get("total_valid_pixels", ""),
            "basin_boundary_mask": meta.get("basin_boundary_mask", ""),
            "bps_classes": meta.get("bps_classes_trained", ""),
            "spatial_weight_radius_px": meta.get("spatial_weight_radius_px", ""),
            "y_mean": meta.get("y_mean", ""),
            "y_std": meta.get("y_std", ""),
            "treatment_pixels": meta.get("treatment_pixels", ""),
            "downward_capped_pixels": meta.get("downward_capped_pixels", ""),
            "neg_baseline_clipped": meta.get("negative_baseline_clipped", ""),
            "pct_change_mean": meta.get("mean", ""),
            "pct_change_median": meta.get("median", ""),
        })

    if rows:
        summary_path = basins_dir.parent / "cross_basin_summary.csv"
        all_keys = []
        for r in rows:
            for k in r:
                if k not in all_keys:
                    all_keys.append(k)
        with open(summary_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        _log(f"  -> {summary_path.name}  ({len(rows)} basins)")
    else:
        _log("  No metadata files found - skipping summary")


if __name__ == "__main__":
    main()
