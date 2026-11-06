// Defence deck: the whole project as one short story (about 25 minutes, 14 story slides + 10 data slides + backup).
// node study_pack/deck/build_defense.js  ->  deliverables/study_pack/05_Defense_Deck.pptx
// Figures are from the delivered version (fc0c281) unless a slide says "after delivery".
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/root/.claude/skills/synced/86fef461-ce27-49a2-921b-8a346b8a123a_1bd7a851-6d43-4fb3-89f5-95162e3bf336/pptx/scripts/apply_theme.js");

const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "deliverables", "study_pack", "05_Defense_Deck.pptx");
const ASSETS = path.join(__dirname, "..", "assets");

const THEME = {
  name: "Governed Data",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1F2933", lt1: "FFFFFF", dk2: "0F4C45", lt2: "E7F1EE",
    accent1: "0F4C45", accent2: "B5541B", accent3: "1F6F64",
    accent4: "B42318", accent5: "B54708", accent6: "067647",
    hlink: "1F6F64", folHlink: "5B3E96",
  },
};
const H = { ink: "1F2933", muted: "52606D", faint: "9AA5B1", line: "D9E2EC", primary: "0F4C45", tint: "E7F1EE",
  accent: "B5541B", accentTint: "FBEFE6", block: "B42318", blockTint: "FDECEA", warn: "B54708", warnTint: "FEF3E2",
  info: "067647", infoTint: "E8F5EE", post: "5B3E96", postTint: "F2EDFA", grey: "F4F6F8", off: "EEF1F4",
  raw: "7B8794", stg: "1F6F64", dq: "B5541B", core: "0F4C45", ai: "067647", sec: "B42318", white: "FFFFFF" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.author = "Robin De Bruyne";
pres.company = "Take-home walkthrough";
pres.title = "Defending the Governed Data Product for AI";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };

// ---------------------------------------------------------------- layouts
const FOOT = { text: { text: "Berka governed data product · defence · delivered version fc0c281", options: { x: 0.6, y: 7.02, w: 8, h: 0.3, fontSize: 10, color: "7B8794", margin: 0 } } };
pres.defineSlideMaster({
  title: "TITLE", background: { color: H.primary },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.1, w: 11.9, h: 1.8, fontSize: 40, bold: true, color: "FFFFFF", valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.1, w: 10.8, h: 1.3, fontSize: 20, color: "E7F1EE", valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION", background: { color: H.primary },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.55, w: 11.7, h: 1.4, fontSize: 40, bold: true, color: "FFFFFF", valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.1, w: 11.0, h: 1.3, fontSize: 18, color: "E7F1EE", valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "E7F1EE" },
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: "FFFFFF" }, margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.32, w: 9.0, h: 0.85, fontSize: 30, bold: true, color: H.primary, valign: "middle", align: "left", margin: 0 }, text: "" } },
    FOOT,
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "7B8794" },
});
pres.defineSlideMaster({
  title: "WIDE", background: { color: "FFFFFF" }, margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.32, w: 12.1, h: 0.85, fontSize: 30, bold: true, color: H.primary, valign: "middle", align: "left", margin: 0 }, text: "" } },
    FOOT,
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "7B8794" },
});

// ---------------------------------------------------------------- helpers
const ICON = {};
async function renderIcons() {
  const want = { robot: "FaRobot", db: "FaDatabase", broom: "FaBroom", check: "FaClipboardCheck", book: "FaBook",
    lock: "FaLock", key: "FaKey", shield: "FaShieldAlt", filter: "FaFilter", chart: "FaChartBar", bug: "FaBug",
    bulb: "FaLightbulb", search: "FaSearch", users: "FaUsers", file: "FaFileAlt", route: "FaRoute", warn: "FaExclamationTriangle",
    layer: "FaLayerGroup", balance: "FaBalanceScale", question: "FaQuestion", flag: "FaFlagCheckered", eye: "FaEyeSlash", cogs: "FaCogs" };
  for (const [k, name] of Object.entries(want)) {
    for (const [tone, color] of [["w", "#FFFFFF"], ["p", "#" + H.primary], ["a", "#" + H.accent]]) {
      const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(fa[name], { color, size: 256 }));
      const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
      ICON[`${k}_${tone}`] = "image/png;base64," + png.toString("base64");
    }
  }
}
let current = null;
const section = (name) => { pres.addSection({ title: name }); current = name; };
const slide = (master = "CONTENT") => pres.addSlide({ masterName: master, sectionTitle: current });
const title = (s, t) => s.addText(t, { placeholder: "title" });
const notes = (s, t) => s.addNotes(t.trim().replace(/\n\s+/g, "\n"));
function text(s, t, o) { s.addText(t, Object.assign({ isTextBox: true, fontSize: 16, color: H.ink, margin: 0, valign: "top" }, o)); }
function box(s, o) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: o.r ?? 0.08,
    fill: { color: o.fill || H.grey }, line: { color: o.line || o.fill || H.grey, width: o.lw || 0.75, dashType: o.dash }, objectName: o.name || "box" });
}
function label(s, t, o) { // text centred in a box
  s.addText(t, Object.assign({ shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.08, fontSize: 15, bold: true, color: "FFFFFF",
    align: "center", valign: "middle", margin: 4, line: { color: o.fill }, objectName: "label" }, o, { fill: { color: o.fill } }));
}
function iconCircle(s, key, x, y, d, fill) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill || H.primary }, line: { color: fill || H.primary }, objectName: "icon circle" });
  const pad = d * 0.24;
  s.addImage({ data: ICON[key + "_w"], x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, altText: key + " icon" });
}
function icon(s, key, tone, x, y, d) { s.addImage({ data: ICON[`${key}_${tone}`], x, y, w: d, h: d, altText: key + " icon" }); }
function arrow(s, x1, y1, x2, y2, color, width) {
  s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1, line: { color: color || H.faint, width: width || 2, endArrowType: "triangle" }, objectName: "arrow" });
}
function bullets(s, items, o) {
  const runs = items.map((it, i) => {
    const t = typeof it === "string" ? { text: it } : it;
    return { text: t.text, options: Object.assign({ bullet: { indent: 16 }, breakLine: i < items.length - 1, paraSpaceAfter: 7 }, t.options || {}) };
  });
  s.addText(runs, Object.assign({ isTextBox: true, fontSize: 16, color: H.ink, margin: 0, valign: "top" }, o));
}
function stat(s, o) {
  text(s, o.n, { x: o.x, y: o.y, w: o.w, h: 0.7, fontSize: o.size || 36, bold: true, color: o.color || H.primary });
  text(s, o.l, { x: o.x, y: o.y + 0.72, w: o.w, h: 0.7, fontSize: 13, color: H.muted });
}
function chip(s, x, y, w, t, fill, color) {
  s.addText(t, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.17, x, y, w, h: 0.34, fill: { color: fill }, line: { color: fill },
    fontSize: 11, bold: true, color: color || "FFFFFF", align: "center", valign: "middle", margin: 0, objectName: "chip" });
}
function table(s, rows, o) {
  const head = rows[0].map((h) => ({ text: h, options: { bold: true, color: H.primary, border: [{ type: "none" }, { type: "none" }, { pt: 1.5, color: H.primary }, { type: "none" }] } }));
  const body = rows.slice(1).map((r) => r.map((c) => {
    const cell = typeof c === "object" ? c : { text: String(c) };
    return { text: cell.text, options: Object.assign({ color: H.ink, border: [{ type: "none" }, { type: "none" }, { pt: 0.5, color: H.line }, { type: "none" }] }, cell.options || {}) };
  }));
  s.addTable([head, ...body], Object.assign({ fontFace: "Calibri", fontSize: 14, margin: [3, 5, 3, 5], valign: "middle" }, o));
}
// The recurring "you are here" map: six layers, the ones a slide is about in colour.
const LAYERS = [["raw", H.raw], ["stg", H.stg], ["dq", H.dq], ["core", H.core], ["ai", H.ai], ["sec", H.sec]];
function miniMap(s, on) {
  const x0 = 9.75, y0 = 0.48, w = 0.5, gap = 0.04;
  LAYERS.forEach(([n, c], i) => {
    const lit = on.includes(n);
    s.addText(n, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.05, x: x0 + i * (w + gap), y: y0, w, h: 0.5,
      fill: { color: lit ? c : H.off }, line: { color: lit ? c : H.off }, fontSize: 11, bold: true, fontFace: "Courier New",
      color: lit ? "FFFFFF" : H.faint, align: "center", valign: "middle", margin: 0, objectName: "map " + n });
  });
  text(s, "you are here", { x: x0, y: y0 + 0.53, w: 6 * (w + gap), h: 0.25, fontSize: 10, color: H.faint, align: "center" });
}

// ================================================================= the deck
async function build() {
  await renderIcons();

  // ---------------------------------------------------------------- 1 Opening
  section("Opening");
  let s = slide("TITLE");
  s.addText("Defending the Governed Data Product for AI", { placeholder: "title" });
  s.addText("Eight raw banking files, made into data an AI assistant can query correctly — and only for the clients each user may see", { placeholder: "body" });
  text(s, "Berka (PKDD'99) take-home · technical walkthrough · November 2026", { x: 0.8, y: 6.55, w: 10, h: 0.4, fontSize: 14, color: "E7F1EE" });
  iconCircle(s, "robot", 11.2, 0.7, 1.4, H.accent);
  notes(s, `
    [30 seconds] Thank you. I'll tell this as one story in five parts — the problem, the principle I designed around,
    three proofs (one per task), the evidence, and what I would challenge myself on. About 25 minutes, plus about ten
    for the evidence in numbers (insights and the ten answers as charts), then questions.
    Everything is from the version I handed in, commit fc0c281; where I mention later work, I'll say so.`);

  s = slide("WIDE");
  title(s, "One story in five parts");
  const parts = [["question", "1  The problem", "Natural-language questions on bank data"],
    ["robot", "2  The principle", "Treat the AI as a dumb and dangerous client"],
    ["shield", "3  Three proofs", "Trustworthy data · one meaning · access it can't bypass"],
    ["chart", "4  The evidence", "10 questions, measured — and its limits"],
    ["bulb", "5  Honesty & next", "What I'd challenge, what I learned, what's next"]];
  parts.forEach(([ic, h, d], i) => {
    const x = 0.6 + i * 2.48;
    iconCircle(s, ic, x + 0.62, 1.55, 1.0, i === 2 ? H.accent : H.primary);
    if (i < 4) arrow(s, x + 1.78, 2.05, x + 2.42, 2.05, H.faint, 2.25);
    text(s, h, { x, y: 2.8, w: 2.25, h: 0.45, fontSize: 18, bold: true, color: i === 2 ? H.accent : H.primary, align: "center" });
    text(s, d, { x, y: 3.3, w: 2.25, h: 1.0, fontSize: 14, color: H.muted, align: "center" });
  });
  box(s, { x: 0.6, y: 4.65, w: 12.13, h: 1.95, fill: H.tint });
  text(s, "The thread through all five", { x: 0.9, y: 4.8, w: 11.5, h: 0.4, fontSize: 15, bold: true, color: H.primary });
  const thread = [["search", "Traceable", "every number comes from a command you can re-run"],
    ["broom", "No silent repairs", "nothing is fixed or dropped without a record"],
    ["robot", "Never trusted blindly", "the AI gets no chance to be quietly wrong"],
    ["lock", "Filter in the engine", "where the model's text cannot reach it"]];
  thread.forEach(([ic, h, d], i) => {
    const x = 0.9 + i * 2.95;
    icon(s, ic, "p", x, 5.33, 0.5);
    text(s, h, { x: x + 0.65, y: 5.28, w: 2.15, h: 0.35, fontSize: 15, bold: true, color: H.primary });
    text(s, d, { x: x + 0.65, y: 5.65, w: 2.15, h: 0.8, fontSize: 13, color: H.ink });
  });
  notes(s, `
    [1 minute] This is the whole talk on one slide. If you only remember the bottom box, you have the project:
    traceable numbers, no silent repairs, an AI that is never trusted blindly, and a filter in the engine.
    Timing: problem and principle 4 minutes, the three proofs about 12, evidence 4, honesty and next steps 6.`);

  // ---------------------------------------------------------------- 2 Problem and principle
  section("1–2 · Problem and principle");
  s = slide("WIDE");
  title(s, "The problem: an answer that looks right and isn't");
  const tasks = [["check", "Task 1 · Data quality", "Rules with a severity — and a reason for every severity"],
    ["book", "Task 2 · AI-ready product", "A model, a semantic layer, and an LLM answering 10 questions"],
    ["lock", "Task 3 · Entitlements", "Each user sees only their clients; the LLM cannot bypass it"]];
  tasks.forEach(([ic, h, d], i) => {
    const y = 1.45 + i * 1.32;
    iconCircle(s, ic, 0.6, y + 0.1, 0.9, H.primary);
    text(s, h, { x: 1.7, y: y + 0.05, w: 4.6, h: 0.45, fontSize: 19, bold: true, color: H.primary });
    text(s, d, { x: 1.7, y: y + 0.5, w: 4.6, h: 0.7, fontSize: 15, color: H.muted });
  });
  box(s, { x: 6.75, y: 1.45, w: 5.98, h: 3.85, fill: H.accentTint });
  text(s, "Three things must be true — all three", { x: 7.05, y: 1.65, w: 5.4, h: 0.5, fontSize: 19, bold: true, color: H.accent });
  bullets(s, [{ text: "The data is clean — a duplicate payment inflates every total" },
    { text: "Every word means one thing — 'a bad loan' cannot mean two things" },
    { text: "Every user sees only their own clients — a bank may not show everyone everything" }],
    { x: 7.05, y: 2.25, w: 5.4, h: 2.4, fontSize: 17 });
  text(s, "Miss one, and the assistant gives an answer that looks right and is wrong — or leaks.", { x: 7.05, y: 4.55, w: 5.4, h: 0.7, fontSize: 15, italic: true, color: H.ink });
  stat(s, { x: 0.6, y: 5.55, w: 3.0, n: "1,079,680", l: "rows in 8 source files" });
  stat(s, { x: 3.7, y: 5.55, w: 2.4, n: "10", l: "business questions" });
  stat(s, { x: 6.75, y: 5.55, w: 3.0, n: "5,369", l: "clients, 4,500 accounts" });
  stat(s, { x: 9.85, y: 5.55, w: 2.9, n: "1–2 days", l: "expected effort (more on that later)" });
  notes(s, `
    [90 seconds] The brief: the public Berka bank data, ten questions, three tasks. The business wants to ask questions in
    plain English. That only works if three things hold at once — clean data, one meaning per word, and entitlement.
    Miss one, and you get the worst outcome: an answer that looks right. I'll come back to the 1–2 day estimate honestly
    at the end. Documents: the brief; DDR context section.`);

  s = slide("WIDE");
  title(s, "The principle: treat the AI as a dumb and dangerous client");
  iconCircle(s, "robot", 5.92, 1.5, 1.5, H.accent);
  box(s, { x: 0.6, y: 1.45, w: 4.9, h: 2.4, fill: H.grey });
  text(s, "Dumb — it guesses", { x: 0.85, y: 1.6, w: 4.4, h: 0.45, fontSize: 20, bold: true, color: H.primary });
  bullets(s, ["A column that sounds right", "The wrong date or quarter", "A count where a share was asked", "Its own meaning of 'problematic'"], { x: 0.85, y: 2.12, w: 4.4, h: 1.7, fontSize: 15 });
  box(s, { x: 7.83, y: 1.45, w: 4.9, h: 2.4, fill: H.grey });
  text(s, "Dangerous — its SQL runs", { x: 8.08, y: 1.6, w: 4.4, h: 0.45, fontSize: 20, bold: true, color: H.block });
  bullets(s, ["A second statement smuggled in", "Internal schemas, huge results", "Trying to see more clients", "Anything it writes hits customer data"], { x: 8.08, y: 2.12, w: 4.4, h: 1.7, fontSize: 15 });
  text(s, "So every layer removes a reason to guess, or a way to do harm:", { x: 0.6, y: 4.1, w: 12.1, h: 0.45, fontSize: 17, bold: true, color: H.ink });
  const lines = [["book", "Meaning", "Semantic layer", "removes the reasons to guess", H.primary],
    ["filter", "Shape", "SQL guard", "one read-only SELECT, bounded", H.warn],
    ["lock", "Rows", "Row level security", "the only security boundary", H.block]];
  lines.forEach(([ic, h, w2, d, c], i) => {
    const x = 0.6 + i * 4.09;
    box(s, { x, y: 4.65, w: 3.95, h: 1.95, fill: "FFFFFF", line: c, lw: 1.5 });
    iconCircle(s, ic, x + 0.22, 4.85, 0.75, c);
    text(s, h, { x: x + 1.15, y: 4.85, w: 2.7, h: 0.4, fontSize: 19, bold: true, color: c });
    text(s, w2, { x: x + 1.15, y: 5.28, w: 2.7, h: 0.35, fontSize: 15, bold: true });
    text(s, d, { x: x + 0.22, y: 5.85, w: 3.55, h: 0.6, fontSize: 14, color: H.muted });
  });
  notes(s, `
    [90 seconds] This is the design principle behind every decision. Dumb: the model will confidently guess anything the data
    doesn't spell out. Dangerous: whatever it writes runs against customer data. So three defences, doing different jobs:
    the semantic layer for meaning, the guard for shape, row level security for rows. Say it clearly: only the third is a
    security boundary — it would hold even if the first two failed. And the guard proves a query is safe, never that it is right.`);

  s = slide("WIDE");
  title(s, "The map: six schemas in one PostgreSQL database");
  text(s, "8 files", { x: 0.6, y: 2.45, w: 0.9, h: 0.4, fontSize: 14, bold: true, color: H.muted, align: "center" });
  icon(s, "file", "p", 0.82, 1.85, 0.5);
  arrow(s, 1.5, 2.35, 1.78, 2.35);
  const cols = [["raw", H.raw, "Bronze", "verbatim text, SHA-256 per file"], ["stg", H.stg, "Silver", "typed, decoded, nothing filtered"],
    ["dq", H.dq, "Control", "124 rules, quarantine, flags"], ["core", H.core, "Gold", "star schema = stg − quarantine"],
    ["ai", H.ai, "Surface", "11 security-invoker views"]];
  cols.forEach(([n, c, tag, d], i) => {
    const x = 1.8 + i * 2.2;
    box(s, { x, y: 1.45, w: 1.95, h: 1.85, fill: c });
    text(s, n, { x: x + 0.15, y: 1.55, w: 1.7, h: 0.55, fontSize: 26, bold: true, color: "FFFFFF", fontFace: "Courier New" });
    text(s, tag.toUpperCase(), { x: x + 0.15, y: 2.1, w: 1.7, h: 0.3, fontSize: 11, bold: true, color: "FFFFFF" });
    text(s, d, { x: x + 0.15, y: 2.45, w: 1.7, h: 0.8, fontSize: 13, color: "FFFFFF" });
    if (i < 4) arrow(s, x + 1.95, 2.35, x + 2.2, 2.35);
  });
  // the AI path above the surface, sec below core
  box(s, { x: 8.4, y: 3.75, w: 4.15, h: 1.15, fill: H.sec });
  text(s, "sec · ACCESS", { x: 8.6, y: 3.85, w: 3.8, h: 0.4, fontSize: 18, bold: true, color: "FFFFFF", fontFace: "Courier New" });
  text(s, "grants, 2FA sessions → 7 RLS policies on core", { x: 8.6, y: 4.3, w: 3.8, h: 0.5, fontSize: 13, color: "FFFFFF" });
  arrow(s, 9.05, 3.75, 9.05, 3.32, H.sec, 2.5);
  box(s, { x: 5.2, y: 3.75, w: 2.9, h: 1.15, fill: H.grey, line: H.faint, dash: "dash" });
  text(s, "inject", { x: 5.4, y: 3.85, w: 2.5, h: 0.4, fontSize: 17, bold: true, color: H.muted, fontFace: "Courier New" });
  text(s, "20 seeded defects — tests only", { x: 5.4, y: 4.3, w: 2.5, h: 0.5, fontSize: 13, color: H.muted });
  arrow(s, 6.55, 3.75, 6.55, 3.32, H.faint, 1.5);
  // the LLM path
  box(s, { x: 0.6, y: 5.25, w: 12.13, h: 1.4, fill: H.tint });
  iconCircle(s, "robot", 0.85, 5.45, 1.0, H.accent);
  const path_ = ["question", "semantic layer", "LLM → SQL", "guard", "2FA login", "ai views + RLS", "answer"];
  path_.forEach((p, i) => {
    const x = 2.05 + i * 1.53;
    label(s, p, { x, y: 5.68, w: 1.3, h: 0.55, fill: i === 3 ? H.warn : i === 5 ? H.sec : i === 1 ? H.primary : H.stg, fontSize: 13 });
    if (i < path_.length - 1) arrow(s, x + 1.3, 5.95, x + 1.53, 5.95, H.primary, 1.75);
  });
  notes(s, `
    [90 seconds] This is the map I'll keep returning to — you'll see it small in the top corner of the next slides.
    Data flows left to right: raw keeps the files verbatim and hashed, staging types and decodes but filters nothing,
    the dq control plane grades every defect, core is the star schema — staging minus the quarantine, checked on rows and
    money after every build — and ai is the only surface anyone may query. sec sits beside core: its policies decide rows.
    The bottom row is the AI path; one database, SQL files, plain Python. Why PostgreSQL: Task 3 is enforcement, and DuckDB
    has no row level security. Documents: DDR §1–2, VISUAL_GUIDE.`);

  // ---------------------------------------------------------------- 3 Three proofs
  section("3 · Three proofs");
  s = slide();
  title(s, "Proof 1 · Trustworthy data, nothing silently changed");
  miniMap(s, ["raw", "stg", "dq"]);
  const flow = [["db", "8 files", "landed verbatim"], ["broom", "21 cleaning steps", "only 1 removes a row"], ["check", "124 rules", "19 fire · 14 defect types"], ["flag", "1 quarantined", "440 warn flags"]];
  flow.forEach(([ic, h, d], i) => {
    const x = 0.6 + i * 3.1;
    iconCircle(s, ic, x, 1.5, 0.85, i === 3 ? H.accent : H.primary);
    text(s, h, { x: x + 1.0, y: 1.5, w: 1.95, h: 0.45, fontSize: 18, bold: true, color: H.primary });
    text(s, d, { x: x + 1.0, y: 1.95, w: 1.95, h: 0.45, fontSize: 14, color: H.muted });
    if (i < 3) arrow(s, x + 2.75, 1.92, x + 3.05, 1.92);
  });
  const sev = [["BLOCK", H.block, H.blockTint, "Quarantined with a reason; excluded, reversible", "1 row"],
    ["WARN", H.warn, H.warnTint, "Kept; the flag travels to the answer as a caveat", "440 flags"],
    ["INFO", H.info, H.infoTint, "Standardised or logged; no answer changes", "12 rules"]];
  sev.forEach(([n, c, t, d, k], i) => {
    const x = 0.6 + i * 2.6;
    box(s, { x, y: 2.85, w: 2.45, h: 2.05, fill: t });
    chip(s, x + 0.18, 3.02, 1.0, n, c);
    text(s, d, { x: x + 0.18, y: 3.48, w: 2.1, h: 0.95, fontSize: 14 });
    text(s, k, { x: x + 0.18, y: 4.42, w: 2.1, h: 0.4, fontSize: 17, bold: true, color: c });
  });
  box(s, { x: 8.55, y: 2.85, w: 4.18, h: 3.75, fill: H.tint });
  text(s, "How I know it's true", { x: 8.8, y: 3.0, w: 3.7, h: 0.45, fontSize: 18, bold: true, color: H.primary });
  bullets(s, ["20 of 20 seeded defects caught by the right rule", "raw = stg on 11 checks", "core = stg − quarantine on 9 checks (rows and money)", "Every changed value keeps its original in a _raw column"],
    { x: 8.8, y: 3.5, w: 3.75, h: 3.0, fontSize: 15 });
  box(s, { x: 0.6, y: 5.1, w: 7.75, h: 1.5, fill: H.grey });
  text(s, "Same check, opposite decision", { x: 0.85, y: 5.2, w: 7.3, h: 0.4, fontSize: 16, bold: true, color: H.primary });
  text(s, "14 zero-amount postings are real interest runs → info (blocking would break 14 balance chains to fix nothing). A negative amount would be block: money moves the wrong way.",
    { x: 0.85, y: 5.62, w: 7.3, h: 0.95, fontSize: 14 });
  notes(s, `
    [3 minutes] Task one. The files land verbatim; staging converts without overwriting — 21 steps, and exactly one removes
    a row, a duplicate posting. Then 124 rules grade every defect, and each severity does something: block quarantines,
    warn flags and the flag reaches the answer, info logs. The zero-amount example shows the severity is reasoned, not felt.
    Proof: seeded defects prove the rules fire; reconciliation proves nothing was lost.
    If asked about the only blocked row: it's a 0.00 duplicate — the rule needs an identical resulting balance, so it can only
    catch zero-amount duplicates (Lessons L-04). Documents: workbook 'Defect types' and 'DQ rules', CLEANING_LEDGER, dq_report.`);

  s = slide();
  title(s, "Proof 2 · One meaning, checked on every build");
  miniMap(s, ["core", "ai"]);
  s.addImage({ path: path.join(ASSETS, "04_star_schema.png"), x: 0.6, y: 1.4, w: 4.4, h: 4.55, sizing: { type: "contain", w: 4.4, h: 4.55 }, altText: "Core star schema" });
  text(s, "Star schema: 4 grains (client, account, loan, posting), natural keys, verified every build", { x: 0.6, y: 6.05, w: 4.4, h: 0.6, fontSize: 12, color: H.muted, italic: true });
  const facts = [["layer", "11", "entities, grain and every column described"], ["balance", "12", "certified metrics with their time column"], ["route", "19", "joins with measured cardinality"], ["warn", "7", "caveats with row counts"]];
  facts.forEach(([ic, n, d], i) => {
    const x = 5.35 + (i % 2) * 3.7, y = 1.45 + Math.floor(i / 2) * 1.2;
    iconCircle(s, ic, x, y, 0.75, H.primary);
    text(s, n, { x: x + 0.9, y: y - 0.02, w: 0.9, h: 0.6, fontSize: 28, bold: true, color: H.primary });
    text(s, d, { x: x + 1.65, y: y + 0.05, w: 1.95, h: 0.75, fontSize: 13, color: H.muted });
  });
  box(s, { x: 5.35, y: 3.95, w: 3.6, h: 2.65, fill: H.tint });
  text(s, "Decided once", { x: 5.6, y: 4.08, w: 3.2, h: 0.4, fontSize: 17, bold: true, color: H.primary });
  bullets(s, ["Owner = the OWNER disposition", "Problematic = status B or D (76 / 682)", "Incoming = credits, unsigned", "Month-end = last posting, carried forward"],
    { x: 5.6, y: 4.52, w: 3.25, h: 2.0, fontSize: 14 });
  box(s, { x: 9.15, y: 3.95, w: 3.58, h: 2.65, fill: H.accentTint });
  text(s, "The build fails if …", { x: 9.4, y: 4.08, w: 3.2, h: 0.4, fontSize: 17, bold: true, color: H.accent });
  bullets(s, ["a column doesn't exist or isn't described", "a grain isn't one row per key", "a join's cardinality changed", "a metric names a missing column"],
    { x: 9.4, y: 4.52, w: 3.2, h: 2.0, fontSize: 14 });
  notes(s, `
    [3 minutes] Task two. A star schema, because the questions live at four grains, and a wide table turns every count into
    count(distinct) — exactly what generated SQL gets wrong quietly. Each business word is decided once, in the model and in
    the semantic layer. The semantic layer is not prompt text: it's a file the build validates against the live database.
    A layer that drifted gives the model confident wrong information it cannot check. Its 'is not' glossary is the AI-ready part:
    a disponent is not the owner, incoming is not a net flow.
    Raise it here: the month-end fact breaks same-day ties by the highest transaction id — disclosed; I'll come back to it.
    Documents: model_explanation.md, semantic_layer.yaml, DDR §3 and §5.`);

  s = slide();
  title(s, "Proof 3 · Access the model cannot bypass");
  miniMap(s, ["core", "ai", "sec"]);
  s.addImage({ path: path.join(ASSETS, "05_where_the_filter_sits.png"), x: 0.6, y: 1.4, w: 6.6, h: 3.0, sizing: { type: "contain", w: 6.6, h: 3.0 }, altText: "Three places a filter can live" });
  s.addChart(pres.charts.BAR, [{ name: "clients visible", labels: ["cro_global (all)", "rm_north", "rm_south", "rm_unassigned"], values: [5369, 1481, 1387, 0] }], {
    x: 0.6, y: 4.5, w: 6.6, h: 2.15, barDir: "bar", chartColors: [H.primary], showValue: true, dataLabelPosition: "outEnd", dataLabelColor: H.ink,
    dataLabelFontSize: 12, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "#,##0", catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: H.ink,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "Clients visible after logging in as each user", titleFontSize: 13, titleColor: H.primary, titleFontFace: "+mn-lt" });
  const ans = [["lock", "Where", "7 RLS policies on the client-bearing core tables; every view in between is security_invoker"],
    ["shield", "Why no bypass", "The predicate isn't in the model's text; identity is session_user; no BYPASSRLS"],
    ["users", "Onboarding", "Insert a user + portfolio, create the role, enrol TOTP — no code. Offboarding: one UPDATE"],
    ["key", "Two factors", "Password alone → 0 rows; the code is verified inside the database"]];
  ans.forEach(([ic, h, d], i) => {
    const y = 1.45 + i * 1.3;
    iconCircle(s, ic, 7.5, y + 0.05, 0.7, i === 3 ? H.accent : H.sec);
    text(s, h, { x: 8.35, y, w: 4.38, h: 0.4, fontSize: 17, bold: true, color: H.primary });
    text(s, d, { x: 8.35, y: y + 0.42, w: 4.38, h: 0.8, fontSize: 14, color: H.ink });
  });
  notes(s, `
    [3 minutes] Task three asked me to explain — I built and tested it. The filter is a row level security policy on the base
    tables, so it sits inside every statement's plan, evaluated as the caller because every view in between is security_invoker.
    The caller is session_user, which no SQL can change. The model only writes text; the predicate isn't in the text, so there's
    nothing to remove. The bank-wide user is a portfolio of every client, not an exemption — and a new user with no portfolio sees
    zero, not everything. Nine bypass attempts in the tests fail. Onboarding is inserts; the grants are derived live.
    Know the limits: a disponent sees the owner's card (L-05); a direct client can roll back failed codes (L-09).
    Documents: ACCESS_AND_AUTH, workbook 'Entitlements', DDR §6.`);

  s = slide("WIDE");
  title(s, "One question, end to end — and who protects what");
  const seq = [["question", "Question", "“What % of loans are problematic?”", H.primary],
    ["book", "Semantic layer", "the model's whole world: no data, no tools", H.primary],
    ["robot", "LLM writes SQL", "one JSON: sql + reasoning", H.accent],
    ["filter", "Guard", "one read-only SELECT on ai, LIMIT ≤ 10,000", H.warn],
    ["key", "2FA login", "the user's own session, 60 s timeout", H.sec],
    ["lock", "RLS on core", "only this user's rows exist", H.sec],
    ["chart", "Answer + log", "rm_north 179 loans · cro_global 76 / 682", H.info]];
  seq.forEach(([ic, h, d, c], i) => {
    const x = 0.6 + i * 1.75;
    iconCircle(s, ic, x + 0.38, 1.5, 0.8, c);
    if (i < seq.length - 1) arrow(s, x + 1.25, 1.9, x + 1.68, 1.9, H.faint, 2);
    text(s, h, { x, y: 2.42, w: 1.6, h: 0.45, fontSize: 15, bold: true, color: c, align: "center" });
    text(s, d, { x, y: 2.88, w: 1.6, h: 1.0, fontSize: 12, color: H.muted, align: "center" });
  });
  // bands: meaning / shape / rows / check
  const bands = [[0, 3, "MEANING — removes reasons to guess", H.primary], [3, 4, "SHAPE", H.warn], [4, 6, "ROWS — the security boundary", H.sec], [6, 7, "CHECK", H.info]];
  bands.forEach(([a, b, t, c]) => label(s, t, { x: 0.6 + a * 1.75, y: 4.05, w: (b - a) * 1.75 - 0.12, h: 0.45, fill: c, fontSize: 12 }));
  box(s, { x: 0.6, y: 4.8, w: 12.13, h: 1.85, fill: H.accentTint });
  icon(s, "warn", "a", 0.85, 5.0, 0.55);
  text(s, "The guard proves a query is safe to run — not that it answers the question.", { x: 1.6, y: 4.98, w: 10.9, h: 0.5, fontSize: 19, bold: true, color: H.accent });
  text(s, "Observed: “Find male or female loans in Q1 1995” → SQL used T2.gender on ai.account_owner → guard allowed → database: column does not exist. Safe failure, but valid-and-wrong SQL would have returned a plausible number.",
    { x: 1.6, y: 5.5, w: 10.9, h: 0.65, fontSize: 15 });
  text(s, "Later we fixed it (not in the delivered version): an intent check (D029) refuses this query before it runs.", { x: 1.6, y: 6.17, w: 10.9, h: 0.35, fontSize: 14, italic: true, color: H.post });
  notes(s, `
    [2 minutes] One question all the way through. The model sees only the semantic layer and the question. Its SQL is parsed
    by the guard, then runs on the user's own two-factor session, where row level security decides the rows; every call is logged.
    The coloured band is the point: meaning, shape and rows are different jobs. And the orange box is the honest limit:
    the guard is a shape filter. The gender question passed it and failed in the database — a safe failure. A query that is valid
    but wrong would not fail. In the delivered version the intent checker was a prototype; after delivery I built it in (D029).
    Documents: src/sql_guard.py, DDR §7, Lessons L-07.`);

  // ---------------------------------------------------------------- 4 Evidence
  section("4 · Evidence");
  s = slide("WIDE");
  title(s, "The evidence — and what it does not prove");
  s.addChart(pres.charts.BAR, [
    { name: "match", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [10, 6] },
    { name: "partial", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [0, 2] },
    { name: "mismatch", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [0, 2] }],
    { x: 0.6, y: 1.4, w: 6.4, h: 3.3, barDir: "bar", barGrouping: "stacked", chartColors: [H.info, H.warn, H.block],
      showValue: true, dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", dataLabelFontSize: 13, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "0;;;",
      showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: "+mn-lt", catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
      catAxisLabelColor: H.ink, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
      showTitle: true, title: "Ten questions, compared by value with independent reference SQL", titleFontSize: 13, titleColor: H.primary, titleFontFace: "+mn-lt" });
  stat(s, { x: 0.6, y: 4.95, w: 2.0, n: "10/10", l: "first attempt", color: H.info });
  stat(s, { x: 2.7, y: 4.95, w: 2.2, n: "~2 min", l: "USD 0.40, every call logged" });
  stat(s, { x: 5.0, y: 4.95, w: 2.0, n: "327", l: "tests passed (1 skipped)" });
  box(s, { x: 7.3, y: 1.4, w: 5.43, h: 2.45, fill: H.tint });
  text(s, "What it shows", { x: 7.55, y: 1.55, w: 5.0, h: 0.4, fontSize: 18, bold: true, color: H.primary });
  bullets(s, ["The semantic layer is good enough for a strong model on these questions", "No SQL hand-corrected; references never shown to the model", "A weak model fails in exactly the ways the layer warns about"],
    { x: 7.55, y: 2.0, w: 5.0, h: 1.8, fontSize: 14 });
  box(s, { x: 7.3, y: 4.05, w: 5.43, h: 2.6, fill: H.accentTint });
  text(s, "What it does not show", { x: 7.55, y: 4.2, w: 5.0, h: 0.4, fontSize: 18, bold: true, color: H.accent });
  bullets(s, ["Generalisation: no hold-out set, and the pack names the questions", "Stability: one sample per question", "Currency: recorded on the pack before the semantic audit"],
    { x: 7.55, y: 4.65, w: 5.0, h: 1.9, fontSize: 14 });
  notes(s, `
    [2 minutes] The evidence. Claude answered all ten on the first attempt; all ten match hand-crafted reference SQL, compared
    by value — two correct queries name columns differently, so comparing SQL text would measure style. The small local model
    scored six: it counted instead of computing a share, and fanned out a join — exactly the traps the layer warns about.
    Then say what it doesn't prove before anyone asks: no hold-out, one sample, an older pack. The honest claim is 'good enough
    for a strong model on these ten', not 'it generalises'. Every figure is mapped to its source in DELIVERY_AUDIT.md.
    Precise authorship: the reference SQL wasn't written by the model under test, and every answer was re-derived from raw (L-12).`);

  // ---------------------------------------------------------------- 5 Honesty and next
  // ---------------------------------------------------------------- 4b Evidence in numbers (BI visuals, bi_slides.js)
  require("./bi_slides")({ pres, H, slide, title, notes, text, box, label, bullets, stat, chip, table, icon, iconCircle, section });

  section("5 · Honesty and next steps");
  s = slide("WIDE");
  title(s, "Where I would challenge myself");
  const weak = [["balance", "Month-end tie-break", "Highest trans_id picks the closing posting — right 0.4% of the time where the balance chain decides", "Disclosed · fixed after", H.post],
    ["filter", "Guard ≠ meaning", "A safe query can be wrong; the intent checker was a prototype", "Disclosed · fixed after", H.post],
    ["chart", "10/10 is narrow", "No hold-out, question labels in the pack, one sample", "Partly disclosed", H.warn],
    ["eye", "Disponent privacy", "Sees the owner's card; a hidden owner shows as 'no card' — false, not hidden", "Found after delivery", H.block],
    ["cogs", "Scope vs a 1–2 day brief", "2FA, web tour, deployment guide, agents — tasks first; I'd cut those first", "Talk track", H.muted]];
  weak.forEach(([ic, h, d, st, c], i) => {
    const y = 1.4 + i * 1.06;
    box(s, { x: 0.6, y, w: 12.13, h: 0.92, fill: i % 2 ? "FFFFFF" : H.grey });
    iconCircle(s, ic, 0.78, y + 0.13, 0.66, H.primary);
    text(s, h, { x: 1.65, y: y + 0.12, w: 3.2, h: 0.7, fontSize: 17, bold: true, color: H.primary, valign: "middle" });
    text(s, d, { x: 4.9, y: y + 0.08, w: 5.4, h: 0.78, fontSize: 14, valign: "middle" });
    chip(s, 10.45, y + 0.29, 2.1, st, c);
  });
  notes(s, `
    [2 minutes] Before you ask, these are the five things I would challenge myself on. The first two I disclosed at delivery and
    fixed afterwards on a separate branch. The evaluation is narrower than 10 out of 10 suggests. The disponent finding is one I
    made after delivery: row level security changed the meaning of a column — hidden became a false value. And scope: the tasks
    came first; if I had to cut, the deployment guide, the simulated agents, then the web page.
    Detail and wording for each: Lessons Learned document, L-01, L-07, L-08, L-05/L-06, L-19.`);

  s = slide("WIDE");
  title(s, "The lesson I'd take to any data team");
  text(s, "My best-looking defect — “an account off by exactly 1,200: a missing posting” — was my own bug.", { x: 0.6, y: 1.35, w: 12.1, h: 0.55, fontSize: 19, bold: true, color: H.accent });
  // dominoes: account 3888, 31 Jan 1998
  const dom = [["opening", "10,500.00", H.grey, H.ink], ["+1.30 interest", "id 3,467,643 → 10,501.30", H.grey, H.ink], ["−1,200.00 withdrawal", "id 1,137,901 → 9,301.30", H.primary, "FFFFFF"]];
  dom.forEach(([h, d, f, tc], i) => {
    const x = 0.6 + i * 2.75;
    box(s, { x, y: 2.15, w: 2.45, h: 1.35, fill: f, line: H.primary, lw: 1.5 });
    text(s, h, { x: x + 0.1, y: 2.25, w: 2.25, h: 0.45, fontSize: 15, bold: true, color: tc, align: "center" });
    text(s, d, { x: x + 0.1, y: 2.72, w: 2.25, h: 0.7, fontSize: 13, color: tc, align: "center" });
    if (i < 2) arrow(s, x + 2.45, 2.82, x + 2.75, 2.82, H.primary, 2.25);
  });
  text(s, "Account 3888, 31 Jan 1998 — each posting starts where the previous one ended. The chain says the withdrawal came last; my rule (highest id) read 10,501.30.",
    { x: 0.6, y: 3.65, w: 8.0, h: 0.8, fontSize: 14, color: H.muted });
  const nums = [["0.4%", "how often the highest id was the true closing posting", H.block], ["55 → 14", "material reconciliation breaks after the fix", H.accent], ["+1.53", "change in the Q9 average (43,808.94 → 43,810.47)", H.primary], ["107", "accounts with a different closing balance", H.primary]];
  nums.forEach(([n, l, c], i) => stat(s, { x: 0.6 + i * 2.05, y: 4.65, w: 1.95, n, l, color: c, size: 30 }));
  box(s, { x: 9.0, y: 2.15, w: 3.73, h: 4.45, fill: H.accentTint });
  icon(s, "bulb", "a", 9.25, 2.35, 0.6);
  text(s, "What I learned", { x: 9.95, y: 2.4, w: 2.7, h: 0.5, fontSize: 18, bold: true, color: H.accent });
  bullets(s, ["A derived check inherits the bugs of what it reads", "'Unknowable' is a hypothesis — test it before documenting it", "When a number makes a great story, check it twice"],
    { x: 9.25, y: 3.1, w: 3.3, h: 3.4, fontSize: 15 });
  notes(s, `
    [2 minutes] This is the story I'd tell any data team. I assumed the source had no intra-day order and broke same-day ties by
    the highest id — and disclosed it. Going back, the running balance records the order: each posting starts where the previous
    ended. The highest id was right 0.4% of the time. The average barely moved, 1.53 CZK, but 107 accounts did.
    And my most convincing defect — an account off by exactly 1,200, 'a missing posting' — was this account: an interest credit
    with a higher id than the withdrawal after it. My reconciliation rule read my own wrong balance: 55 material breaks became 14.
    Also worth one sentence: my checks caught me twice before delivery — the self-test that nearly deleted real data, and the view
    that leaked all 682 loans. Documents: Lessons L-01–L-03, chapter 7.`);

  s = slide("WIDE");
  title(s, "What I did next, and what changes at 100,000×");
  box(s, { x: 0.6, y: 1.4, w: 6.0, h: 5.25, fill: H.postTint });
  text(s, "After delivery — on a separate branch", { x: 0.85, y: 1.55, w: 5.5, h: 0.45, fontSize: 18, bold: true, color: H.post });
  table(s, [["", "Delivered", "After"], ["Closing posting", "highest trans_id", "balance chain (D028)"], ["Q9 average", "43,808.94", "43,810.47"], ["Material breaks", "55", "14"],
    ["Accounts that change", "—", "107 (max 1,200.00)"],
    ["Meaning of SQL", "guard only", "intent verified (D029)"], ["Gender question", "DB error", "refused before running"],
    ["Where", "fc0c281 (handed in)", "this branch, with tests"]],
    { x: 0.85, y: 2.1, w: 5.5, colW: [1.9, 1.7, 1.9], fontSize: 13, rowH: 0.37 });
  text(s, "Not merged: it changes a certified number — that needs the business to sign off the rule.", { x: 0.85, y: 5.65, w: 5.5, h: 0.85, fontSize: 14, italic: true, color: H.post });
  box(s, { x: 6.78, y: 1.4, w: 5.95, h: 5.25, fill: H.grey });
  text(s, "At 100,000× (≈ 100 bn postings, 10 TB)", { x: 7.03, y: 1.55, w: 5.5, h: 0.45, fontSize: 18, bold: true, color: H.primary });
  bullets(s, ["Rebuild-from-scratch becomes incremental: month partitions, merge not replace",
    "Rules check what arrived; info sampled, block exact",
    "Month-end maintained from last month + new postings",
    "Entitlements as a materialised (role, account) set",
    "A hold-out question set and monitoring"],
    { x: 7.03, y: 2.1, w: 5.45, h: 3.3, fontSize: 15 });
  box(s, { x: 7.03, y: 5.45, w: 5.45, h: 1.0, fill: H.tint });
  text(s, "Unchanged: the filter stays in the engine, onboarding stays an insert, the semantic layer stays the same size.", { x: 7.2, y: 5.53, w: 5.15, h: 0.85, fontSize: 14, bold: true, color: H.primary });
  notes(s, `
    [90 seconds] After delivery I fixed the two most important limitations on a branch, with tests and before/after evidence, and
    deliberately did not merge them: changing a certified number during a freeze, without sign-off, is what a governed product
    should not do. At a hundred thousand times, everything 'rebuild from scratch' becomes 'maintain incrementally', and the
    entitlement join becomes a materialised set — but the design does not change. Documents: DDR '100,000×', DECISIONS D028–D029.`);

  s = slide("SECTION");
  s.addText("Traceable numbers. No silent repairs. A filter the model cannot reach.", { placeholder: "title" });
  s.addText("Where it is weak, it is written down — with the evidence and the fix. Questions welcome.", { placeholder: "body" });
  iconCircle(s, "shield", 11.3, 0.8, 1.3, H.accent);
  notes(s, `
    [30 seconds] Three things to remember: every number traces to a command; nothing is silently repaired or dropped; and the
    filter sits where the model's text cannot reach it. Where it's weak, I've told you, with evidence and the fix.
    Backup slides: how the documents fit, the ten answers, the decision map, question anchors, security residuals.`);

  // ---------------------------------------------------------------- Backup
  section("Backup");
  s = slide("WIDE");
  title(s, "Backup · how the documents fit the story");
  const docs = [["1–2 Problem & principle", ["Brief + questions.csv", "DDR — context, decisions 1 and 7"], H.primary],
    ["3 Trustworthy data", ["Workbook: Defect types, DQ rules, Cleaning", "dq_rules.yaml · dq_report.md", "CLEANING_LEDGER.md · DDR decisions 2 and 4"], H.dq],
    ["3 One meaning", ["model_explanation.md · Workbook: Model", "semantic_layer.yaml → context_pack.md", "DDR decisions 3 and 5"], H.core],
    ["3 Access", ["ACCESS_AND_AUTH.md · WORKED_EXAMPLE.md", "Workbook: Entitlements", "DDR decision 6"], H.sec],
    ["4 Evidence", ["Workbook: Questions, Q detail", "llm_results / evaluation.json · llm_logs/", "DELIVERY_AUDIT.md — every claim → source"], H.info],
    ["5 Honesty & next", ["Lessons Learned (02) · DECISIONS.md", "ASSUMPTIONS.md · DDR 100,000×", "Study guide (01 / 01b) for depth"], H.post]];
  docs.forEach(([h, items, c], i) => {
    const x = 0.6 + (i % 3) * 4.09, y = 1.45 + Math.floor(i / 3) * 2.65;
    box(s, { x, y, w: 3.95, h: 2.45, fill: "FFFFFF", line: c, lw: 1.75 });
    label(s, h, { x: x + 0.15, y: y + 0.15, w: 3.65, h: 0.5, fill: c, fontSize: 15 });
    bullets(s, items, { x: x + 0.25, y: y + 0.8, w: 3.5, h: 1.6, fontSize: 13 });
  });
  notes(s, `Use when asked "where is the evidence for X?". The single map of every claim to its source is docs/DELIVERY_AUDIT.md.`);

  s = slide("WIDE");
  title(s, "Backup · the ten answers, as delivered");
  table(s, [["Q", "Question", "Answer"],
    ["1", "Clients per region", "south Moravia 937 · north Moravia 920 … (client's own district, all 5,369)"],
    ["2", "Loans granted per year", "1993 2.62 m (half year) … 1997 peak 30.73 m · total 103,261,740"],
    ["3", "Share of problematic loans", "76 / 682 = 11.14% (status B or D)"],
    ["4", "Average loan by owner's card", "junior 221,970 (n = 21) · gold 161,881 · no card 148,865 · classic 148,809"],
    ["5", "Top 10 districts, incoming 1997", "Hl.m. Praha 115.13 m · Karvina 28.51 m · Ostrava 27.69 m …"],
    ["6", "New accounts per month 1996", "106 · 104 · 124 · 101 · 91 · 113 · 137 · … · 125 (1,363)"],
    ["7", "Owner age at loan start", "A 37.07 · B 39.60 · C 38.70 · D 37.00"],
    ["8", "Gold-card owners by gender", "male 53 (60.23%) · female 35 (39.77%)"],
    ["9", "Average balance end Dec 1998", "43,808.94 over 4,500 accounts (76 carried forward)"],
    ["10", "Highest problematic share by frequency", "after transaction 18.75% (6 of 32 — not significant)"]],
    { x: 0.6, y: 1.4, w: 12.13, colW: [0.55, 3.6, 7.98], fontSize: 15, rowH: 0.46 });
  notes(s, `Interpretations: A1–A16. Least confident: Q10 (small n), Q4 (odd population), Q9 at account level (tie-break).`);

  s = slide("WIDE");
  title(s, "Backup · decisions by layer");
  const dmap = [["raw", H.raw, ["D003 verified public mirror", "D004 defects only in inject"]],
    ["stg", H.stg, ["D013 never repair in place", "D014 placeholders → NULL", "D015 19xx dates, NULL on failure", "D016 derived gender, labelled", "D018 sign resolved once", "D020 graded, not gated"]],
    ["dq", H.dq, ["D008 quarantine scoped to stg", "D006 / D017 one code map, checked"]],
    ["core", H.core, ["D007 natural keys", "D019 month-end decided once", "D012 rebuild restores ai"]],
    ["ai", H.ai, ["D005 sandboxed LLM", "D010 every view security_invoker", "D011 value-based evaluation"]],
    ["sec", H.sec, ["D009 filter in the engine", "D021 a customer IS a client", "D023 / D024 account, not person", "D025 three identifiers", "D026 2FA in the database", "D027 derive grants"]]];
  dmap.forEach(([n, c, items], i) => {
    const x = 0.6 + i * 2.05;
    label(s, n, { x, y: 1.45, w: 1.9, h: 0.6, fill: c, fontSize: 18, fontFace: "Courier New" });
    bullets(s, items.map((t) => ({ text: t, options: { bullet: false } })), { x, y: 2.25, w: 1.9, h: 4.4, fontSize: 12.5 });
  });
  notes(s, `D001 (repository at the git root) and D002 (PostgreSQL) span all layers. D022 is superseded by D023. Full text: DECISIONS.md, study guide chapter 18.`);

  s = slide("WIDE");
  title(s, "Backup · likely questions and where the answer is");
  table(s, [["If they ask …", "Short answer", "Go to"],
    ["Why not DuckDB / a warehouse?", "Task 3 needs enforcement in the engine; DuckDB has no RLS", "DDR §1"],
    ["Why never repair a value?", "A repaired value looks observed a week later", "D013, Proof 1"],
    ["Your only block is 0.00 CZK?", "The rule can only catch zero-amount duplicates; warn rule for batches", "L-04"],
    ["Can the LLM bypass the filter?", "It writes text; the predicate isn't in it; identity = session_user", "Proof 3"],
    ["Does passing the guard mean correct?", "No — shape only. The gender query proves it", "L-07"],
    ["Is 10/10 meaningful?", "Narrow: no hold-out, one sample, older pack", "L-08"],
    ["Biggest mistake?", "The tie-break; the 1,200 story was my own artefact", "L-01–L-03"],
    ["Why so much for 1–2 days?", "Tasks first; extras requested; cut deployment guide first", "L-19"]],
    { x: 0.6, y: 1.4, w: 12.13, colW: [3.5, 6.63, 2.0], fontSize: 15, rowH: 0.55 });
  notes(s, `Full question bank: study guide chapter 17; mistake answers: Lessons Learned chapter 10.`);

  s = slide("WIDE");
  title(s, "Backup · security residuals, stated before they are asked");
  table(s, [["Residual", "Status", "Fix"],
    ["Direct client rolls back failed second-factor guesses", "Disclosed (strict xfail)", "Count attempts outside the caller's transaction, or gateway-only logins"],
    ["Session bound to backend PID only", "A45", "Compare backend_start too"],
    ["Disponent sees the owner's card and disposition row", "Found after delivery", "Holder-based card policy; own-row dispositions; tests"],
    ["Hidden owner fields shown as 'no card' / NULL", "Found after delivery", "No coalesce over RLS-hidden joins; say 'not visible'"],
    ["TOTP secrets recoverable; demo shows codes", "A44, A46", "Encrypt with an external key; real enrolment"],
    ["No read audit, no masking, role-per-user pooling", "Recommended", "Audit log; masking; pool per role or SET ROLE gateway"]],
    { x: 0.6, y: 1.4, w: 12.13, colW: [4.6, 2.6, 4.93], fontSize: 15, rowH: 0.68 });
  notes(s, `Row level security itself is unaffected by all of these: without the second factor a principal reads no rows.`);

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", path.relative(ROOT, OUT));
}

build().catch((e) => { console.error(e); process.exit(1); });
