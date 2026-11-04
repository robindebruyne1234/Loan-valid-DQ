// Render an HTML file to an A4 PDF with Chromium (Playwright).
// Usage: node render_pdf.mjs <in.html> <out.pdf> "<footer title>"
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

// ESM ignores NODE_PATH; resolve the preinstalled Playwright through require.
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [, , input, output, title = ""] = process.argv;
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.pdf({
  path: output,
  format: "A4",
  printBackground: true,
  outline: true,
  tagged: true,
  displayHeaderFooter: true,
  headerTemplate: "<span></span>",
  footerTemplate: `
    <div style="width:100%;font-family:'Liberation Sans',Arial,sans-serif;font-size:7.5pt;color:#7B8794;
                padding:0 16mm;display:flex;justify-content:space-between;">
      <span>${esc(title)}</span>
      <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
    </div>`,
  margin: { top: "16mm", bottom: "18mm", left: "16mm", right: "16mm" },
});
await browser.close();
