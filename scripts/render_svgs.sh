#!/usr/bin/env bash
# Rasterise the hand-authored SVG diagrams to PNG for slides.
# Optional, like render_diagrams.sh: the SVGs are the committed artefact.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v node >/dev/null || { echo "render_svgs | node not found, skipping"; exit 0; }
HAND=(docs/diagrams/05_where_the_filter_sits.svg docs/diagrams/06_model_shape.svg)
PUPPETEER_MODULE="${PUPPETEER_MODULE:-puppeteer}" node scripts/svg_to_png.js "${HAND[@]}"
