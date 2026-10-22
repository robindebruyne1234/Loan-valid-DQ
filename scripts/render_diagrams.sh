#!/usr/bin/env bash
# Render the Mermaid diagram sources in docs/diagrams/ to SVG and PNG.
#
# OPTIONAL. The rendered files are committed, so nothing here is needed to read
# the documentation, and nothing here is part of the data pipeline: GitHub
# renders the .mmd sources inline anyway. The PNGs exist so the diagrams can be
# dropped into slides for the walkthrough.
#
# Needs node/npx and a Chromium. In this container Chromium is pre-installed at
# /opt/pw-browsers/chromium.
set -euo pipefail

cd "$(dirname "$0")/.."
DIR=docs/diagrams
CONFIG=$(mktemp /tmp/mmdc-puppeteer-XXXX.json)
THEME=$(mktemp /tmp/mmdc-theme-XXXX.json)
trap 'rm -f "$CONFIG" "$THEME"' EXIT

CHROME="${PUPPETEER_EXECUTABLE_PATH:-/opt/pw-browsers/chromium}"
printf '{"args":["--no-sandbox","--disable-dev-shm-usage"]%s}\n' \
  "$( [ -x "$CHROME" ] && printf ',"executablePath":"%s"' "$CHROME" )" > "$CONFIG"

# A light canvas, so the same file is legible on a white page, in a dark-themed
# viewer and in a slide deck.
cat > "$THEME" <<'JSON'
{
  "theme": "base",
  "themeVariables": {
    "fontFamily": "Segoe UI, Helvetica, Arial, sans-serif",
    "fontSize": "14px",
    "primaryColor": "#eef3fb",
    "primaryTextColor": "#1f2a44",
    "primaryBorderColor": "#1f3864",
    "lineColor": "#5b6472",
    "textColor": "#1f2a44",
    "mainBkg": "#eef3fb"
  },
  "flowchart": { "curve": "basis", "nodeSpacing": 45, "rankSpacing": 60, "htmlLabels": true },
  "er": { "layoutDirection": "LR", "entityPadding": 12 }
}
JSON

for source in "$DIR"/*.mmd; do
  name=$(basename "$source" .mmd)
  echo "render_diagrams | $name"
  npx -y @mermaid-js/mermaid-cli \
    -i "$source" -o "$DIR/$name.svg" \
    -p "$CONFIG" -c "$THEME" -b white --quiet
  npx -y @mermaid-js/mermaid-cli \
    -i "$source" -o "$DIR/$name.png" \
    -p "$CONFIG" -c "$THEME" -b white --scale 2 --quiet
done

echo "render_diagrams | done -> $DIR"
