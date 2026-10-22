/**
 * Rasterise hand-authored SVG files to PNG with the bundled Chromium.
 *
 * Only needed to put the diagrams into slides: the SVGs themselves are the
 * committed artefact and render directly in Markdown, in a browser and in a
 * document. ImageMagick in this image has no SVG delegate, hence Chromium.
 *
 * Usage: node scripts/svg_to_png.js <file.svg> [...]
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');

const SCALE = 2;

(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/opt/pw-browsers/chromium',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  for (const file of process.argv.slice(2)) {
    const svg = fs.readFileSync(file, 'utf8');
    const viewBox = svg.match(/viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"/);
    if (!viewBox) { console.error(`skip ${file}: no viewBox`); continue; }
    const width = Math.ceil(parseFloat(viewBox[1]));
    const height = Math.ceil(parseFloat(viewBox[2]));

    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: SCALE });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8">
       <style>html,body{margin:0;padding:0;background:#fff}
       svg{display:block;width:${width}px;height:${height}px}</style></head>
       <body>${svg}</body></html>`,
      { waitUntil: 'load' }
    );
    const out = file.replace(/\.svg$/, '.png');
    await page.screenshot({ path: out, omitBackground: false });
    await page.close();
    console.log(`svg_to_png | ${path.basename(out)} ${width * SCALE}x${height * SCALE}`);
  }
  await browser.close();
})();
