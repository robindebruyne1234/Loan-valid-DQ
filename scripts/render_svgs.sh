#!/usr/bin/env bash
# Rasterise the hand-authored SVG diagrams to PNG for slides.
# Optional, like render_diagrams.sh: the SVGs are the committed artefact.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null || { echo "render_svgs | node not found, skipping"; exit 0; }
# The defect catalogue is generated from the data first, then rasterised with
# the rest: a stale picture of a defect list is worse than no picture.
python3 scripts/make_defect_catalogue.py
HAND=(docs/diagrams/05_where_the_filter_sits.svg
      docs/diagrams/06_model_shape.svg
      docs/diagrams/07_defect_lifecycle.svg
      docs/diagrams/08_defect_catalogue.svg
      docs/diagrams/09_system_map.svg
      docs/diagrams/10_build_sequence.svg)
PUPPETEER_MODULE="${PUPPETEER_MODULE:-puppeteer}" node scripts/svg_to_png.js "${HAND[@]}"
