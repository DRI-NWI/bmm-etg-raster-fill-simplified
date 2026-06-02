#!/usr/bin/env python3
"""
diagnostics.py
==============
Post-run evaluation and visual sanity checks for the ETg baseline-fill workflow.

Generates diagnostic plots and console distribution summaries:

  1. Histogram — ETg distributions (outside vs treatment, before and after).
  2. Scatter — predicted baseline vs. original ETg for treatment-zone pixels.
  3. BpS box-plots — ETg by vegetation class (outside vs treatment).
  4. Map panels — side-by-side original, baseline prediction, and final ETg.
  5. Difference map — change in treatment zones (red = reduced, blue = increased).
  6. Treatment-zone map — color-coded zones (outside / treatment).
  7. Feather weight map — blend weights and edge detail (if feathering enabled).
  8. Console summary — distribution statistics (n, mean, median, p10, p90).

Usage:
    cd <project folder>
    python diagnostics.py

License: MIT (see LICENSE)
"""

import sys
from pathlib import Path

import numpy as np

try:
    import rasterio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as e:
    sys.exit(f"Missing dependency: {e}")

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
cfg = None  # set by main()


def _read(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        nd = src.nodata
    if nd is not None:
        arr[arr == np.float32(nd)] = np.nan
    return arr


def _load_cfg(study_area: str):
    """Load per-basin TOML config via basin_config.py."""
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


def main(study_area: str | None = None):
    # When called with no argument, fall through to the CLI (supports
    # --all / --only / --skip for batch processing).
    if study_area is None:
        return _cli()
    _load_cfg(study_area)
    print(f"Study area: {cfg.STUDY_AREA_NAME}")

    out = cfg.OUT_DIR

    # ── Load rasters ─────────────────────────────────────────────────────────
    print("Loading rasters …")

    # Prefer the raw (unmodified) ETg raster so diagnostics compare the true
    # Landsat-derived ETg against the modeled baseline and final product.
    # The input ETg raster is the only source (no separate raw variant is
    # supported).
    etg_orig = _read(cfg.ETG_TIF)

    sa = cfg.STUDY_AREA_NAME
    etg_baseline = _read(out / f"{sa}_ETg_baseline_pred.tif")
    etg_final    = _read(out / f"{sa}_ETg_final.tif")
    treatment    = _read(out / "treatment_zone.tif")
    bps          = _read(out / "BpS_matched.tif").astype(np.int32)

    is_treat   = treatment == 1
    is_outside = (~is_treat) & np.isfinite(etg_orig) & (etg_orig > 0)

    # Flattened subsets
    orig_out   = etg_orig[is_outside]
    orig_treat = etg_orig[is_treat & np.isfinite(etg_orig)]
    final_treat = etg_final[is_treat & np.isfinite(etg_final)]
    base_treat  = etg_baseline[is_treat & np.isfinite(etg_baseline)]

    # ── 1. Histogram comparison ──────────────────────────────────────────────
    # Y-axis is "% of group" — each histogram is normalized so its bars sum to
    # 100%.  This lets us compare the shape of distributions whose pixel counts
    # differ by orders of magnitude (basin floor ≫ treatment zones) on one plot.
    # Group sizes (n) are annotated in the legend so magnitude context isn't lost.
    print("Plotting histograms …")
    fig, ax = plt.subplots(figsize=(9, 5))
    p99 = np.nanpercentile(etg_orig[np.isfinite(etg_orig)], 99)
    bins = np.linspace(0, p99, 80)

    def _pct_weights(arr):
        # Each bar = (count / total) * 100, so the whole histogram sums to 100%.
        n = len(arr)
        return np.full(n, 100.0 / n) if n > 0 else np.empty(0)

    ax.hist(orig_out,    bins=bins, alpha=0.35,
            weights=_pct_weights(orig_out),
            label=f"Outside treatment (n = {len(orig_out):,})")
    ax.hist(orig_treat,  bins=bins, alpha=0.35,
            weights=_pct_weights(orig_treat),
            label=f"Treatment zones – original (n = {len(orig_treat):,})")
    ax.hist(final_treat, bins=bins, alpha=0.35,
            weights=_pct_weights(final_treat),
            label=f"Treatment zones – filled (n = {len(final_treat):,})")
    ax.set_xlabel("ETg (ft/yr)")
    ax.set_ylabel("% of group")
    ax.set_title("ETg distributions: outside vs treatment zones")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / f"{sa}_diag_histogram.png", dpi=150)
    plt.close(fig)
    print(f"  → {out / 'diag_histogram.png'}")

    # ── 2. Scatter: baseline vs original (treatment zones) ───────────────────
    print("Plotting scatter …")
    n_samp = min(len(orig_treat), 20_000)
    if n_samp > 0:
        rng = np.random.default_rng(42)
        si = rng.choice(len(orig_treat), size=n_samp, replace=False)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(base_treat[si], orig_treat[si], s=1, alpha=0.15, c="steelblue")
        lims = [0, np.nanpercentile(np.concatenate([orig_treat, base_treat]), 99)]
        ax.plot(lims, lims, "k--", lw=0.8, label="1:1")
        ax.set_xlabel("Predicted baseline ETg (ft/yr)")
        ax.set_ylabel("Original (raw) ETg (ft/yr)")
        ax.set_title("Treatment-zone pixels: baseline vs original")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / f"{sa}_diag_scatter.png", dpi=150)
        plt.close(fig)
        print(f"  → {out / 'diag_scatter.png'}")

    # ── 3. Per-BpS box-plots ─────────────────────────────────────────────────
    print("Plotting BpS box-plots …")
    bps_treat_arr = bps[is_treat & (bps > 0)]
    if len(bps_treat_arr) > 0:
        uniq, counts = np.unique(bps_treat_arr, return_counts=True)
        top10 = uniq[np.argsort(-counts)[:10]]

        data_out, data_treat, labels = [], [], []
        for b in top10:
            m_out = is_outside & (bps == b)
            m_tr  = is_treat & (bps == b) & np.isfinite(etg_final)
            if m_out.sum() > 10:
                data_out.append(etg_orig[m_out])
                data_treat.append(etg_final[m_tr] if m_tr.sum() > 0
                                  else np.array([np.nan]))
                labels.append(str(b))

        if labels:
            fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
            axes[0].boxplot(data_out, tick_labels=labels, showfliers=False)
            axes[0].set_title("Outside-treatment ETg")
            axes[0].set_xlabel("BpS code"); axes[0].set_ylabel("ETg (ft/yr)")
            axes[1].boxplot(data_treat, tick_labels=labels, showfliers=False)
            axes[1].set_title("Treatment-zone ETg (after fill)")
            axes[1].set_xlabel("BpS code")
            fig.tight_layout()
            fig.savefig(out / f"{sa}_diag_bps_boxplots.png", dpi=150)
            plt.close(fig)
            print(f"  → {out / 'diag_bps_boxplots.png'}")

    # ── 4. Map panels ────────────────────────────────────────────────────────
    print("Plotting map panels …")
    vmin, vmax = 0, np.nanpercentile(etg_orig[np.isfinite(etg_orig)], 98)

    fig, axes = plt.subplots(1, 3, figsize=(18, 8))
    titles = ["Original ETg", "Baseline prediction", "Final ETg"]
    arrays = [etg_orig, etg_baseline, etg_final]
    for ax, arr, title in zip(axes, arrays, titles):
        im = ax.imshow(arr, vmin=vmin, vmax=vmax, cmap="YlGnBu")
        ax.set_title(title, fontsize=14, pad=10)
        ax.axis("off")
    fig.tight_layout(rect=[0, 0.07, 1, 0.96])  # room at top for titles, bottom for colorbar
    fig.colorbar(im, ax=axes.ravel().tolist(), orientation="horizontal",
                 fraction=0.04, pad=0.04, shrink=0.5,
                 label="ETg (ft/yr)")
    fig.savefig(out / f"{sa}_diag_map_panels.png", dpi=150)
    plt.close(fig)
    print(f"  → {out / 'diag_map_panels.png'}")

    # ── 5. Difference map ────────────────────────────────────────────────────
    print("Plotting difference map …")
    diff = etg_orig - etg_final
    diff[treatment == 0] = np.nan

    fig, ax = plt.subplots(figsize=(8, 7))
    fin = diff[np.isfinite(diff)]
    vabs = np.nanpercentile(np.abs(fin), 98) if len(fin) > 0 else 1
    im = ax.imshow(diff, cmap="RdBu_r", vmin=-vabs, vmax=vabs)
    ax.set_title("ETg change in treatment zones (original − final)\n"
                 "Red = reduced  |  Blue = increased")
    ax.axis("off")
    fig.colorbar(im, ax=ax, shrink=0.6, label="ΔETg (ft/yr)")
    fig.tight_layout()
    fig.savefig(out / f"{sa}_diag_difference_map.png", dpi=150)
    plt.close(fig)
    print(f"  → {out / 'diag_difference_map.png'}")

    # ── 6. Treatment-zone map ────────────────────────────────────────────────
    print("Plotting treatment-zone map …")
    tmap = np.full_like(etg_orig, np.nan)
    tmap[is_outside] = 0   # outside
    tmap[is_treat]   = 1   # treatment

    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap(["#d9d9d9", "#2166ac"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5], cmap.N)

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(tmap, cmap=cmap, norm=norm, interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax, shrink=0.5, ticks=[0, 1])
    cbar.ax.set_yticklabels(["Outside", "Treatment"])
    ax.set_title("Treatment zones")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / f"{sa}_diag_treatment_map.png", dpi=150)
    plt.close(fig)
    print(f"  → {out / 'diag_treatment_map.png'}")

    # ── 7. Feather weight map (if feathering was used) ───────────────────────
    feather_path = out / "feather_weight.tif"
    if feather_path.exists():
        print("Plotting feather weight map …")
        fweight = _read(feather_path)

        fig, axes = plt.subplots(1, 2, figsize=(16, 7))

        # Left: feather weight
        im0 = axes[0].imshow(fweight, vmin=0, vmax=1, cmap="magma")
        axes[0].set_title("Feather blend weight\n(1 = 100% baseline, 0 = 100% raw ETg)")
        axes[0].axis("off")
        fig.colorbar(im0, ax=axes[0], shrink=0.6, label="Weight")

        # Right: zoomed ETg comparison – original vs final for a treatment area
        # Show the full difference map with feathered edges visible
        diff_f = etg_orig - etg_final
        diff_f[treatment == 0] = np.nan
        fin = diff_f[np.isfinite(diff_f)]
        vabs = np.nanpercentile(np.abs(fin), 98) if len(fin) > 0 else 1
        im1 = axes[1].imshow(diff_f, cmap="RdBu_r", vmin=-vabs, vmax=vabs)
        axes[1].set_title("ΔETg with feathered edges\n(compare to diag_difference_map)")
        axes[1].axis("off")
        fig.colorbar(im1, ax=axes[1], shrink=0.6, label="ΔETg (ft/yr)")

        fig.tight_layout()
        fig.savefig(out / f"{sa}_diag_feather_map.png", dpi=150)
        plt.close(fig)
        print(f"  → {out / 'diag_feather_map.png'}")

    # ── Console summary ──────────────────────────────────────────────────────
    print("\n── Distribution summary ──────────────────────────────")
    for label, arr in [
        ("Outside treatment", orig_out),
        ("Treatment zones – original", orig_treat),
        ("Treatment zones – baseline pred", base_treat),
        ("Treatment zones – final", final_treat),
    ]:
        a = arr[np.isfinite(arr)] if len(arr) > 0 else arr
        if len(a) > 0:
            print(f"  {label:35s}  n={len(a):>8,}  "
                  f"mean={np.mean(a):.3f}  med={np.median(a):.3f}  "
                  f"p10={np.percentile(a,10):.3f}  p90={np.percentile(a,90):.3f}")

    print("\nDone – diagnostic plots saved to:", out.resolve())


def _cli():
    """Argparse-based CLI supporting single-basin and batch modes."""
    import argparse
    import basin_config as _bc

    ap = argparse.ArgumentParser(
        description="Generate diagnostic plots and distribution summaries "
                    "for one or more basins.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("study_area", nargs="?",
                    help="Basin key (e.g. 053_PineValley). Omit with "
                         "--all or --only for batch mode.")
    ap.add_argument("--all", action="store_true",
                    help="Process every basin with a config.toml.")
    ap.add_argument("--only", nargs="+", metavar="KEY",
                    help="Process only these basin keys.")
    ap.add_argument("--skip", nargs="+", metavar="KEY", default=[],
                    help="With --all, skip these basin keys.")
    ap.add_argument("--list", action="store_true",
                    help="List available basins and exit.")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="Abort the batch on the first failure "
                         "(default: continue and report a summary).")
    args = ap.parse_args()

    available = _bc.available_areas()

    if args.list:
        if available:
            print(f"{len(available)} basin(s) with config.toml:")
            for k in available:
                print(f"  {k}")
        else:
            print("(no basins with config.toml found)")
        return 0

    if args.all and args.only:
        sys.exit("ERROR: --all and --only are mutually exclusive.")
    if args.all:
        keys = [k for k in available if k not in set(args.skip)]
    elif args.only:
        keys = list(args.only)
    elif args.study_area:
        keys = [args.study_area]
    else:
        sys.exit(
            f"Usage: python diagnostics.py <study_area>\n"
            f"       python diagnostics.py --all [--skip KEY ...]\n"
            f"       python diagnostics.py --only KEY [KEY ...]\n"
            f"  Available: {', '.join(available) if available else '(none)'}"
        )

    if not keys:
        sys.exit("No basins to process.")

    if len(keys) == 1:
        main(keys[0])
        return 0

    print(f"Running diagnostics on {len(keys)} basins …\n")
    failures = []
    for i, key in enumerate(keys, 1):
        header = f"[{i}/{len(keys)}] {key}"
        print("=" * len(header))
        print(header)
        print("=" * len(header))
        try:
            main(key)
        except SystemExit as e:
            msg = str(e) if e.code not in (0, None) else "exited"
            print(f"  !! {key} failed: {msg}")
            failures.append((key, msg))
            if args.stop_on_error:
                break
        except Exception as e:
            print(f"  !! {key} failed: {e.__class__.__name__}: {e}")
            failures.append((key, f"{e.__class__.__name__}: {e}"))
            if args.stop_on_error:
                break
        print()

    print("=" * 60)
    ok = len(keys) - len(failures)
    print(f"Batch complete.  ok: {ok}   failed: {len(failures)}")
    if failures:
        print("Failures:")
        for k, msg in failures:
            print(f"  {k}: {msg}")
        return 1 if ok == 0 else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
