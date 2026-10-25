#!/usr/bin/env bash
# Rasterise the hand-authored SVG diagrams to PNG for slides.
# Optional, like render_diagrams.sh: the SVGs are the committed artefact.
set -euo pipefail
cd "$(dirname "$0")/.."
# Two rasterisers, because the first one is not always there. Puppeteer is
# preferred when its module is installed; otherwise fall back to the Chromium
# that ships with this image, which needs no node modules at all.
CHROMIUM="${CHROMIUM:-/opt/pw-browsers/chromium}"
rasterise_with_chromium() {
  for svg in "$@"; do
    W=$(grep -o 'width="[0-9]*"' "$svg" | head -1 | tr -dc 0-9)
    H=$(grep -o 'height="[0-9]*"' "$svg" | head -1 | tr -dc 0-9)
    "$CHROMIUM" --headless --no-sandbox --disable-gpu --hide-scrollbars \
      --force-device-scale-factor=2 --window-size="$W,$((H + 20))" \
      --screenshot="${svg%.svg}.png" "file://$PWD/$svg" 2>/dev/null
    echo "render_svgs | ${svg%.svg}.png"
  done
}
# The defect catalogue is generated from the data first, then rasterised with
# the rest: a stale picture of a defect list is worse than no picture.
python3 scripts/make_defect_catalogue.py
HAND=(docs/diagrams/05_where_the_filter_sits.svg
      docs/diagrams/06_model_shape.svg
      docs/diagrams/07_defect_lifecycle.svg
      docs/diagrams/08_defect_catalogue.svg
      docs/diagrams/09_system_map.svg
      docs/diagrams/10_build_sequence.svg
      docs/diagrams/11_access_model.svg
      docs/diagrams/12_auth_flow.svg)
if command -v node >/dev/null && node -e "require.resolve('puppeteer')" 2>/dev/null; then
  PUPPETEER_MODULE="${PUPPETEER_MODULE:-puppeteer}" node scripts/svg_to_png.js "${HAND[@]}"
elif [ -x "$CHROMIUM" ]; then
  rasterise_with_chromium "${HAND[@]}"
else
  echo "render_svgs | no rasteriser available, skipping (the SVGs are the artefact)"
fi
