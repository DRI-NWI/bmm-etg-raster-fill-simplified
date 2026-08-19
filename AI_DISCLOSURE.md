# AI-Assisted Development Disclosure

## Overview

This codebase was developed collaboratively between DRI research staff and Claude,
an AI assistant made by Anthropic. This document describes the nature and extent
of AI involvement, in keeping with principles of scientific transparency and
reproducibility.

This tool extends the Beamer-Minor Model (BMM) ETg estimation workflow (Beamer et
al., 2013; Minor, 2019; Huntington et al., 2022) by replacing manually assigned
replacement rates with a data-driven spatial baseline. The scientific
foundation -- Landsat-based ETg estimation, ET unit delineation, and the concept of
separating irrigation-enhanced ET from natural groundwater discharge -- was
established in prior peer-reviewed work by DRI staff (see README.md, References).

This repository is a simplified fork of the original `bmm-etg-raster-fill`.
The original two-stage model (per-BpS-class mean refined by a machine-learning
terrain-residual model) was reduced to its baseline after DRI
cross-validation showed the terrain-residual model never improved on the
BpS-class baseline. See CHANGELOG.md for the full rationale.

## Roles

**Human (DRI research staff):**
- Defined the scientific problem and research objectives.
- Specified the modeling approach and the input datasets.
- Evaluated the original two-stage model with cross-validation, found the
  terrain-residual model never beat the BpS-class baseline, and directed the
  simplification to a BpS-only baseline.
- Chose the spatially weighted per-BpS-class mean as the baseline method.
- Made all decisions about treatment-zone classification and full baseline
  replacement for treatment polygons.
- Chose to exclude NDVI to avoid irrigation signal leakage.
- Decided to constrain training data to within-basin pixels only.
- Decided feathering should occur outside the treatment boundary.
- Designed the expert adjustment knob (basin-wide default + per-polygon override).
- Designed the statewide scaling architecture (per-basin configs, NWI basin
  boundaries, directory structure).
- Validated outputs against domain knowledge and prior results.
- Reviewed and approved all code before use.

**AI (Claude, Anthropic):**
- Implemented the Python workflow based on human-specified requirements.
- Wrote raster I/O, reprojection, and rasterization routines.
- Implemented the spatially weighted per-BpS-class mean baseline.
- Implemented Gaussian edge feathering outside the treatment boundary, the
  per-pixel expert-adjustment raster, the downward-only cap, and the
  basin boundary training mask.
- Built the multi-basin architecture: statewide BpS prep, per-basin prep, TOML
  config system, and batch orchestrator.
- Built BpS symbology utilities: RAT extraction, JSON lookup cache, and
  QGIS-compatible .clr and .qml sidecar generation.
- Implemented the custom study-area workflow (prep_custom_basin.py) with
  auto CRS detection.
- Wrote diagnostic plotting and summary statistics code.
- Performed the simplification refactor: removed the ML model, terrain and
  ancillary covariates (DEM, slope, WTD, HAND, REM, soil), and the associated
  download / derivation scripts, under human direction.
- Drafted documentation and this disclosure.

## Development process

The code was developed iteratively over multiple conversation sessions. The human
researcher described each requirement in domain-specific terms, and the AI
translated those requirements into working Python code. The researcher tested each
version on real data, reported results and issues, and directed further changes,
including the decision to retire the machine-learning framework once
cross-validation showed it added no value.

## Reproducibility

All code is provided in source form. Per-basin `config.toml` files document every
tunable parameter for each basin. The `environment.yml` file specifies dependency
requirements. Run metadata files record the exact configuration, training
statistics, per-BpS class means, and results for each basin. Per-basin log files
provide a timestamped audit trail. No proprietary AI APIs are called at runtime --
the AI was used only during development.

## Model and version

- AI model: Claude (Anthropic), Opus class
- Development period: 2026
- The AI has no access to the runtime environment and does not influence results
  after the code is written

## Contact

For questions about the scientific methodology, contact the DRI research team.
For questions about the code implementation, issues and pull requests are welcome
on the project repository.
