// Walkthrough deck for the 45-minute technical walkthrough (about 30 minutes of talk).
// node study_pack/deck/build_deck.js  ->  deliverables/study_pack/03_Walkthrough_Deck.pptx
// Every figure is from the delivered version (fc0c281) unless a slide says "after delivery".
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/root/.claude/skills/synced/86fef461-ce27-49a2-921b-8a346b8a123a_1bd7a851-6d43-4fb3-89f5-95162e3bf336/pptx/scripts/apply_theme.js");

const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "deliverables", "study_pack", "03_Walkthrough_Deck.pptx");
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
const HEX = { ink: "1F2933", muted: "52606D", line: "D9E2EC", primary: "0F4C45", tint: "E7F1EE",
  accent: "B5541B", accentTint: "FBEFE6", block: "B42318", blockTint: "FDECEA", warn: "B54708",
  warnTint: "FEF3E2", info: "067647", infoTint: "E8F5EE", post: "5B3E96", postTint: "F2EDFA", grey: "F4F6F8",
  raw: "7B8794", stg: "1F6F64", dq: "B5541B", core: "0F4C45", ai: "067647", sec: "B42318" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.author = "Robin De Bruyne";
pres.company = "Take-home walkthrough";
pres.title = "The Governed Data Product for AI";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ---------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: "TITLE",
  background: { color: HEX.primary },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.9, fontSize: 46, bold: true, color: "FFFFFF", valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.1, w: 11.0, h: 1.4, fontSize: 20, color: "E7F1EE", valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION",
  background: { color: HEX.primary },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.6, w: 11.7, h: 1.3, fontSize: 40, bold: true, color: "FFFFFF", valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.05, w: 11.0, h: 1.2, fontSize: 18, color: "E7F1EE", valign: "top", margin: 0 }, text: "" } },
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "E7F1EE" },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "FFFFFF" },
  margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.32, w: 12.1, h: 0.85, fontSize: 32, bold: true, color: HEX.primary, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "Berka governed data product · delivered version fc0c281", options: { x: 0.6, y: 7.02, w: 8, h: 0.3, fontSize: 10, color: "7B8794", margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "7B8794" },
});

pres.defineSlideMaster({
  title: "STEP",
  background: { color: "FFFFFF" },
  margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 1.42, y: 0.32, w: 11.3, h: 0.85, fontSize: 32, bold: true, color: HEX.primary, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "Berka governed data product · delivered version fc0c281", options: { x: 0.6, y: 7.02, w: 8, h: 0.3, fontSize: 10, color: "7B8794", margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: "7B8794" },
});

// ---------------------------------------------------------------- helpers
let current = null;
function section(name) { pres.addSection({ title: name }); current = name; }
function slide(master = "CONTENT") { return pres.addSlide({ masterName: master, sectionTitle: current }); }
function title(s, text) { s.addText(text, { placeholder: "title" }); }
function text(s, t, o) { s.addText(t, Object.assign({ isTextBox: true, fontSize: 15, color: C.text1, margin: 0, valign: "top" }, o)); }
function card(s, o) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: 0.08,
    fill: { color: o.fill || HEX.grey }, line: { color: o.line || o.fill || HEX.grey, width: 0.75 }, objectName: o.name || "card" });
  const pad = 0.18;
  let y = o.y + pad;
  if (o.head) {
    text(s, o.head, { x: o.x + pad, y, w: o.w - 2 * pad, h: o.headH || 0.42, fontSize: o.headSize || 17, bold: true, color: o.headColor || HEX.primary });
    y += (o.headH || 0.42) + 0.04;
  }
  if (o.body) text(s, o.body, { x: o.x + pad, y, w: o.w - 2 * pad, h: o.h - (y - o.y) - pad, fontSize: o.bodySize || 16, color: o.bodyColor || HEX.ink });
}
function bullets(s, items, o) {
  const runs = items.map((it, i) => {
    const t = typeof it === "string" ? { text: it } : it;
    return { text: t.text, options: Object.assign({ bullet: t.bullet === false ? false : { indent: 16 }, breakLine: i < items.length - 1, paraSpaceAfter: 6 }, t.options || {}) };
  });
  s.addText(runs, Object.assign({ isTextBox: true, fontSize: 16, color: HEX.ink, margin: 0, valign: "top" }, o));
}
function badge(s, n, x, y, fill) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.62, h: 0.62, fill: { color: fill || HEX.accent }, line: { color: fill || HEX.accent }, objectName: "step badge" });
  text(s, String(n), { x, y: y + 0.02, w: 0.62, h: 0.58, fontSize: 20, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
}
function stepTitle(s, n, t) {
  // numbered badge beside the STEP layout's title placeholder
  badge(s, n, 0.6, 0.43);
  s.addText(t, { placeholder: "title" });
}
function stat(s, o) {
  text(s, o.n, { x: o.x, y: o.y, w: o.w, h: 0.75, fontSize: o.size || 40, bold: true, color: o.color || HEX.primary });
  text(s, o.l, { x: o.x, y: o.y + 0.78, w: o.w, h: 0.75, fontSize: 14, color: HEX.muted });
}
function chip(s, x, y, w, t, fill, color) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.34, rectRadius: 0.17, fill: { color: fill }, line: { color: fill }, objectName: "chip" });
  text(s, t, { x, y: y + 0.01, w, h: 0.32, fontSize: 11, bold: true, color: color || "FFFFFF", align: "center", valign: "middle" });
}
function table(s, rows, o) {
  const head = rows[0].map((h) => ({ text: h, options: { bold: true, color: HEX.primary, fill: { color: "FFFFFF" }, border: [{ type: "none" }, { type: "none" }, { pt: 1.5, color: HEX.primary }, { type: "none" }] } }));
  const body = rows.slice(1).map((r) => r.map((c) => {
    const cell = typeof c === "object" ? c : { text: String(c) };
    return { text: cell.text, options: Object.assign({ color: HEX.ink, border: [{ type: "none" }, { type: "none" }, { pt: 0.5, color: HEX.line }, { type: "none" }] }, cell.options || {}) };
  }));
  const size = o.fontSize ? (o.fontSize <= 12 ? o.fontSize + 1 : o.fontSize + 2) : 15;
  s.addTable([head, ...body], Object.assign({ fontFace: "Calibri", margin: [3, 5, 3, 5], valign: "middle" }, o, { fontSize: size }));
}
const notes = (s, t) => s.addNotes(t.trim().replace(/\n\s+/g, "\n"));

// ================================================================ 1. Opening
section("Opening");
let s = slide("TITLE");
s.addText("The Governed Data Product for AI", { placeholder: "title" });
s.addText("How eight raw banking files became data an AI assistant can query correctly — and only for the clients each user may see", { placeholder: "body" });
text(s, "Berka (PKDD'99) take-home · technical walkthrough · 9 November 2026", { x: 0.8, y: 6.55, w: 10, h: 0.4, fontSize: 14, color: "E7F1EE" });
notes(s, `
  Good morning. In the next thirty minutes I will walk through what I built for the take-home, step by step,
  and for each step the decision, why I made it, what it cost, and where it is weak. I will also tell you what
  I found wrong after I submitted it, because I would rather you hear it from me.
  Everything I show is from the delivered version, commit fc0c281. Where I mention later work I will say so.`);

s = slide();
title(s, "The brief, and the one idea behind my answer");
card(s, { x: 0.6, y: 1.45, w: 3.95, h: 2.35, fill: HEX.grey, head: "Task 1 · Data quality", body: "Rules for completeness, uniqueness, referential integrity, validity, consistency — each with a severity and a reason." });
card(s, { x: 4.69, y: 1.45, w: 3.95, h: 2.35, fill: HEX.grey, head: "Task 2 · AI-ready product", body: "A model, a semantic layer, and an LLM answering ten questions — generated SQL and result per question." });
card(s, { x: 8.78, y: 1.45, w: 3.95, h: 2.35, fill: HEX.grey, head: "Task 3 · Entitlements", body: "Each user sees only their own clients. Where the filter sits, why the LLM cannot bypass it, onboarding without code." });
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 4.1, w: 12.13, h: 2.6, rectRadius: 0.08, fill: { color: HEX.primary }, line: { color: HEX.primary }, objectName: "principle" });
text(s, "Treat the AI assistant as a dumb and dangerous client", { x: 0.95, y: 4.3, w: 11.5, h: 0.6, fontSize: 26, bold: true, color: "FFFFFF" });
text(s, [{ text: "Dumb ", options: { bold: true, color: "FBEFE6" } }, { text: "— it guesses at anything the data does not spell out. Every layer should remove a reason to guess.", options: { color: "FFFFFF" } }],
  { x: 0.95, y: 5.05, w: 11.4, h: 0.6, fontSize: 18 });
text(s, [{ text: "Dangerous ", options: { bold: true, color: "FBEFE6" } }, { text: "— whatever it writes runs against customer data. Every layer should remove a way to do harm.", options: { color: "FFFFFF" } }],
  { x: 0.95, y: 5.7, w: 11.4, h: 0.6, fontSize: 18 });
notes(s, `
  The brief has three tasks on the public Berka bank dataset and ten business questions. The expected effort was one
  to two days and it warns that time spent on infrastructure means you misread it — I will come back to that.
  The idea that organises everything: I treated the AI as a dumb and dangerous client. Dumb, because it will confidently
  guess any meaning the data does not state — a column name, a date, a definition. Dangerous, because the code it writes
  runs against customer data. So each layer you will see either removes a reason to guess, or removes a way to do harm.`);

s = slide();
title(s, "Six schemas in one PostgreSQL database");
const layers = [["raw", HEX.raw, "Bronze", "8 files verbatim as text, SHA-256 per file, line numbers"],
  ["stg", HEX.stg, "Silver", "Typed, decoded, sign resolved — nothing filtered, originals kept"],
  ["dq", HEX.dq, "Control", "124 rules, quarantine, flags, reconciliation, run log"],
  ["core", HEX.core, "Gold", "Star schema = stg − quarantine, verified each build"],
  ["ai", HEX.ai, "Surface", "11 business-named views, all security_invoker"],
  ["sec", HEX.sec, "Access", "Principals, grants, TOTP — read by 7 RLS policies"]];
layers.forEach(([n, col, tag, d], i) => {
  const x = 0.6 + i * 2.05;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.55, w: 1.9, h: 3.0, rectRadius: 0.08, fill: { color: col }, line: { color: col }, objectName: "layer " + n });
  text(s, n, { x: x + 0.15, y: 1.7, w: 1.6, h: 0.6, fontSize: 28, bold: true, color: "FFFFFF", fontFace: "Courier New" });
  text(s, tag.toUpperCase(), { x: x + 0.15, y: 2.32, w: 1.6, h: 0.3, fontSize: 11, bold: true, color: "FFFFFF" });
  text(s, d, { x: x + 0.15, y: 2.7, w: 1.62, h: 1.75, fontSize: 14, color: "FFFFFF" });
});
table(s, [["Contract", "Checked by", "Delivered result"],
  ["raw = stg on rows and money", "DQ step (dq.reconciliation)", "11 of 11 balanced"],
  ["core = stg − quarantine on rows and money", "build_model.reconcile_core", "9 of 9 balanced, every delta 0"],
  ["semantic layer = live schema", "make semantic", "0 problems (11 entities, 105 columns, 19 joins)"]],
  { x: 0.6, y: 4.85, w: 12.13, colW: [4.6, 3.9, 3.63] });
notes(s, `
  The whole thing is one PostgreSQL database with six schemas, each with a contract to the next.
  raw keeps the files exactly as they arrived, hashed. stg types and decodes but filters nothing. dq is the control plane.
  core is the star schema, which must equal staging minus the quarantine on rows and on money. ai is the only surface a
  consumer can query. And sec, beside core rather than on top, holds who may see what, read by seven row level security policies.
  Why PostgreSQL and not DuckDB or a warehouse: Task 3 is about enforcement, and the only honest proof that generated SQL
  cannot bypass a filter is to put the filter in the engine and log in as a restricted user. DuckDB has no row level security.`);

s = slide();
title(s, "How I worked: rules that explain most decisions");
const rules = [["Executed, not asserted", "Every number comes from a logged command; a step that did not run says NOT EXECUTED"],
  ["Land verbatim, never repair", "Originals survive in _raw columns with a note (D013)"],
  ["Grade, do not gate", "Staging filters nothing; rules decide afterwards (D020)"],
  ["A severity has a consequence", "block quarantines · warn flags travel to the answer · info logs"],
  ["One definition, one place", "Owner, problematic, incoming, month-end decided once (D006, D017)"],
  ["Distrust your own build", "Model verified every build; 20 seeded defects; security tested by logging in"]];
rules.forEach(([h, b], i) => {
  const x = 0.6 + (i % 3) * 4.09, y = 1.5 + Math.floor(i / 3) * 2.6;
  card(s, { x, y, w: 3.95, h: 2.4, fill: i % 2 ? HEX.tint : HEX.grey, head: h, headSize: 20, headH: 0.5, body: b, bodySize: 18 });
});
notes(s, `
  A few working rules explain most of the decisions before anyone asks. Every number is produced by a command whose run is
  logged — nothing typed from memory, and a step that did not run is printed NOT EXECUTED. Bronze is verbatim and silver
  never repairs: a repaired value looks exactly like an observed one a week later. Staging filters nothing, so the quality
  report describes the source, not what survived the loader. A severity must have a mechanical consequence. Each business
  term is decided once. And I distrust my own build: the model is verified after every build, the rules are proven by seeded
  defects, and security is tested by logging in as the restricted user and counting rows.
  I built it with an AI coding assistant under my direction; the disclosure names every model and role.`);

// ================================================================ 2. The pipeline
section("From raw files to a model");
s = slide("STEP");
stepTitle(s, 1, "Ingest: land everything exactly as it arrived");
stat(s, { x: 0.6, y: 1.55, w: 3.0, n: "8", l: "original .asc files from a verified public mirror (D003)" });
stat(s, { x: 3.75, y: 1.55, w: 3.0, n: "1,079,680", l: "rows landed as text, file + line on every row (C01, C02)" });
stat(s, { x: 6.9, y: 1.55, w: 3.0, n: "SHA-256", l: "per file in raw.load_audit — proof of which bytes" });
stat(s, { x: 10.05, y: 1.55, w: 2.7, n: "8 / 8", l: "row counts match the published reference" });
card(s, { x: 0.6, y: 3.65, w: 5.9, h: 2.95, fill: HEX.tint, head: "Why everything lands as text", headSize: 19, bodySize: 17, body: "A cast at load time destroys the evidence of the defect it trips over: a bad date aborts the load or vanishes. Bronze is the one layer that cleans nothing, so when a number is disputed I can show what actually arrived." });
card(s, { x: 6.8, y: 3.65, w: 5.93, h: 2.95, fill: HEX.grey, head: "Why defects are injected elsewhere (D004)", headSize: 19, bodySize: 17, body: "The public copy is clean enough that most rules never fire — and a rule that never fired proves nothing. A seeded, corrupted copy in its own schema proves the rules while the ten answers stay on untouched data." });
notes(s, `
  Step one. Eight original files from a public mirror whose row counts match the published reference exactly — all eight.
  Every field lands as text with its file and line number, and each file gets a SHA-256 in the load audit. The reason is
  simple: a cast at load time hides the defect it trips over. Bronze is the layer you can't argue with.
  Because the public copy is clean, I seed defects into a separate schema to prove the rules fire — never into the real data.`);

s = slide("STEP");
stepTitle(s, 2, "Profile, then clean without overwriting");
text(s, "21 cleaning steps — exactly one removes a row", { x: 0.6, y: 1.45, w: 12, h: 0.5, fontSize: 22, bold: true, color: HEX.accent });
table(s, [["Step", "What it does", "Measured"],
  ["C03", "Seven spellings of 'missing' ('', ?, NA, N/A, NULL, -, unknown) become NULL; original kept", "1,380 rows"],
  ["C05", "YYMMDD text becomes a date; two-digit years read as 19xx; a failed parse is NULL, not an error", "1,062,394 dates"],
  ["C07–C08", "Birth date and gender decoded from birth_number (women: month + 50) — labelled derived", "5,369 clients"],
  ["C09", "Czech codes decoded to English labels from one map; the code stays beside the label", "2,466,175 values"],
  ["C10", "Sign resolved once: PRIJEM credit; VYDAJ and VYBER debit (VYBER is not in the data description)", "1,056,320 postings"],
  ["C14", "The one row removed: a duplicate posting, quarantined with its reason", "1 row"]],
  { x: 0.6, y: 2.1, w: 12.13, colW: [1.2, 8.73, 2.2] });
text(s, "Profiling ran first: every column measured and 17 candidate defects written down with counts before any rule existed.", { x: 0.6, y: 6.25, w: 12.1, h: 0.5, fontSize: 14, color: HEX.muted, italic: true });
notes(s, `
  Before writing rules I profiled every column and wrote down candidate defects with counts — the rules came from the data,
  not from a checklist. Then cleaning: twenty-one steps, and exactly one removes a row, the quarantine of one duplicate.
  Everything else converts without overwriting. The step I would single out for AI-readiness is the sign: every question about
  money in or out turns on Czech words, and the data has VYBER, a debit that the documentation does not even list.
  A query that gets that wrong does not fail — it returns a plausible wrong number. So the sign is decided once, in staging.`);

s = slide("STEP");
stepTitle(s, 3, "Grade every defect — and give the grade a consequence");
const sev = [["block", HEX.block, HEX.blockTint, "Quarantined, excluded from core and the ai views, reversible", "1 rule · 1 row"],
  ["warn", HEX.warn, HEX.warnTint, "Kept; the flag travels onto the row and into the semantic layer as a caveat", "6 rules · 440 flags"],
  ["info", HEX.info, HEX.infoTint, "Standardised or logged; no answer changes", "12 rules"]];
sev.forEach(([n, col, tint, d, c], i) => {
  const x = 0.6 + i * 4.09;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.5, w: 3.95, h: 2.35, rectRadius: 0.08, fill: { color: tint }, line: { color: tint }, objectName: "severity " + n });
  chip(s, x + 0.2, 1.7, 1.1, n.toUpperCase(), col);
  text(s, d, { x: x + 0.2, y: 2.2, w: 3.55, h: 1.0, fontSize: 15 });
  text(s, c, { x: x + 0.2, y: 3.25, w: 3.55, h: 0.45, fontSize: 18, bold: true, color: col });
});
text(s, "124 rules (89 hand written + 35 completeness sweep) · 19 fire on the public copy · 14 defect types", { x: 0.6, y: 4.1, w: 12.1, h: 0.45, fontSize: 17, bold: true, color: HEX.primary });
card(s, { x: 0.6, y: 4.7, w: 12.13, h: 1.95, fill: HEX.grey, head: "Same check, opposite decision", bodySize: 17, body: "14 postings have amount zero. 'Amount must be positive' sounds right — but they are real interest runs that accrued nothing; blocking them would break 14 balance chains to fix nothing, so they are info. A negative amount would be block: the sign was applied twice and money moves the wrong way." });
notes(s, `
  Task one. 124 rules across six dimensions, and every one carries a severity with a reason written in terms of the questions
  it affects — the loader refuses a rule without one. The point is that a severity does something: block quarantines,
  warn flags the row and the flag reaches the answer, info logs.
  My favourite example is the zero-amount postings: same kind of check as a negative amount, opposite decision, and I can say
  why for each. Raise it yourself: the one blocked row is a 0.00 duplicate, because the rule needs an identical resulting
  balance — so it can only catch duplicates that didn't move money. I would add a warn rule for repeated identical batches.`);

s = slide("STEP");
stepTitle(s, 4, "Prove the rules fire, and prove nothing was lost");
card(s, { x: 0.6, y: 1.5, w: 5.95, h: 2.4, fill: HEX.tint, head: "20 of 20 seeded defects caught", headSize: 19, bodySize: 17, body: "A deterministic injector corrupts a copy of staging in its own schema, one defect per rule family; a test asserts each is caught by the rule meant to catch it." });
card(s, { x: 6.78, y: 1.5, w: 5.95, h: 2.4, fill: HEX.tint, head: "Reconciled after every build", headSize: 19, bodySize: 17, body: "raw = stg on 8 row counts and 3 money sums. core = stg − quarantine on 7 row counts and 2 money sums (transactions 6,257,793,560.30; loans 103,261,740.00)." });
card(s, { x: 0.6, y: 4.15, w: 12.13, h: 2.5, fill: HEX.accentTint, headColor: HEX.accent, head: "The bug that proved the point", headSize: 19, bodySize: 17, body: "The quarantine view was not scoped by schema, so running the rule tests made the injected defects exclude real rows: 76 districts instead of 77, 11,024 transactions orphaned. The model's grain and foreign-key checks failed before any deliverable was written (D008). A green build is not a correct build." });
notes(s, `
  Two kinds of proof. That the rules work: twenty seeded defects, each caught by the right rule. And that cleaning lost nothing:
  raw equals staging, and core equals staging minus the quarantine, on rows and money, after every build.
  And the best bug of the project: the self-test nearly deleted real data, because the quarantine view wasn't scoped to the real
  schema. The model checks caught it before anything was written out. That is the argument for verifying the model instead of
  trusting a green build.`);

s = slide("STEP");
stepTitle(s, 5, "A star schema with one definition per term");
s.addImage({ path: path.join(ASSETS, "04_star_schema.png"), x: 0.6, y: 1.35, w: 5.0, h: 5.2, sizing: { type: "contain", w: 5.0, h: 5.2 }, altText: "Core star schema" });
table(s, [["Term", "Decided once in", "Definition"],
  ["Account owner", "core.v_account_owner", "The OWNER disposition — exactly one per account (block rule)"],
  ["Problematic loan", "fact_loan.is_problematic", "Status B or D: 76 of 682 = 11.14% (A4)"],
  ["Incoming money", "fact_transaction.direction", "Credits (PRIJEM), unsigned amount (A7)"],
  ["Month-end balance", "fact_account_month_end_balance", "Last posting on or before month end; carried forward if none (D019)"]],
  { x: 5.9, y: 1.45, w: 6.83, colW: [1.55, 2.35, 2.93], fontSize: 12 });
card(s, { x: 5.9, y: 4.55, w: 6.83, h: 2.05, fill: HEX.grey, head: "Why a star with a bridge", body: "Four grains (client, account, loan, posting); a wide table turns every count into count(distinct), which generated SQL gets wrong quietly. One source, no history: natural keys, no Data Vault (D007)." });
notes(s, `
  The model: four dimensions from the source tables plus a generated calendar, a disposition bridge, two facts and a derived
  month-end balance fact, plus three curated views. The point is not the shape; it is that each business term is decided in
  exactly one place, so no query can quietly use another meaning.
  Raise it yourself here: the month-end fact breaks same-day ties by the highest transaction id. I disclosed that as a known
  limitation. I will show you on a later slide what I found when I went back to it.`);

// ================================================================ 3. Semantic layer and security
section("Meaning and access");
s = slide("STEP");
stepTitle(s, 6, "A semantic layer the build can refuse");
card(s, { x: 0.6, y: 1.5, w: 6.0, h: 5.1, fill: HEX.tint, head: "What the model is given — and nothing else", body: "" });
bullets(s, ["11 entities with grain, key and every column described", "12 certified metrics with their time column", "19 joins with measured cardinality", "A glossary of what each term is and is not", "7 data quality caveats with row counts", "12 query rules (ai only, one SELECT, half-open dates, never aggregate after a fan-out, say what is missing instead of guessing)"],
  { x: 0.85, y: 2.1, w: 5.6, h: 4.4, fontSize: 15 });
card(s, { x: 6.78, y: 1.5, w: 5.95, h: 3.05, fill: HEX.grey, head: "The build fails if …", body: "" });
bullets(s, ["a described column does not exist, or a column is undescribed", "a grain is not one row per key", "a join's cardinality differs from the declared one", "a metric names a column that does not exist"],
  { x: 7.0, y: 2.1, w: 5.5, h: 2.4, fontSize: 15 });
card(s, { x: 6.78, y: 4.75, w: 5.95, h: 1.85, fill: HEX.accentTint, headColor: HEX.accent, head: "Why a file, not prompt text", body: "A layer that drifted from the schema gives the model confident wrong information it cannot check." });
notes(s, `
  The semantic layer is one YAML file rendered into the text the model reads. The model never sees the data, the reference SQL
  or the evaluation. What makes it AI-ready is the 'is not' definitions — a disponent is not the owner, incoming is not a net
  flow — and the caveats with counts that the model is told to surface.
  And it is a build artefact: if a column is renamed or a grain stops holding, the build fails before any answer exists.
  Honest note: the pack also names which entity answers which question. That shows the model where to look without numbers,
  but it means my evaluation is tuned to these ten questions. I will come back to that.`);

s = slide("STEP");
stepTitle(s, 7, "Where the filter sits — and why the model cannot remove it");
s.addImage({ path: path.join(ASSETS, "05_where_the_filter_sits.png"), x: 0.6, y: 1.35, w: 7.3, h: 3.3, sizing: { type: "contain", w: 7.3, h: 3.3 }, altText: "Three places a filter can live" });
card(s, { x: 8.15, y: 1.4, w: 4.58, h: 1.65, fill: HEX.tint, head: "Where", headSize: 16, body: "7 RLS policies on the client-bearing core tables; every view between is security_invoker", bodySize: 13 });
card(s, { x: 8.15, y: 3.15, w: 4.58, h: 1.65, fill: HEX.tint, head: "Why no bypass", headSize: 16, body: "The predicate is not in the model's text; identity is session_user; no consumer has BYPASSRLS", bodySize: 13 });
card(s, { x: 8.15, y: 4.9, w: 4.58, h: 1.7, fill: HEX.tint, head: "Onboarding", headSize: 16, body: "Insert principal + portfolio, create the role, enrol TOTP. Offboarding: one UPDATE", bodySize: 13 });
table(s, [["Logged in as", "Clients", "Loans"], ["cro_global (portfolio of every client)", "5,369", "682"], ["rm_north", "1,481", "179"], ["rm_south (book + 1 delegated)", "1,387", "195"], ["rm_unassigned (no portfolio)", "0", "0"]],
  { x: 0.6, y: 4.85, w: 7.3, colW: [4.5, 1.4, 1.4], fontSize: 12 });
notes(s, `
  Task three asked me to explain; I built and tested it. The filter is a row level security policy on the base tables, so it
  sits inside the plan of every statement. Every view in between is security_invoker, so the policy runs as the caller.
  The caller is session_user, the role that logged in, which no SQL can change. The model only writes text, and the predicate is
  not in that text — there is nothing for it to remove.
  The bank-wide risk user is a portfolio of every client, not an exemption, and a new user with no portfolio sees zero, not
  everything. Nine bypass attempts in the tests fail. And the bug that taught me to test this way: one view missing
  security_invoker returned all 682 loans to a user entitled to none.`);

s = slide("STEP");
stepTitle(s, 8, "Access is data: four sources, two factors");
const src = [["Ownership", "derived", "view + operate on the client and their own accounts"],
  ["Disposition", "derived", "that one account only — never the owner (D024)"],
  ["Portfolio", "derived", "view only on the book (accountability ≠ payment authority)"],
  ["Delegation", "stored", "a human decision with grantor, reason and expiry"]];
src.forEach(([h, k, b], i) => {
  const y = 1.45 + i * 1.08;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y, w: 6.2, h: 0.95, rectRadius: 0.08, fill: { color: k === "stored" ? HEX.warnTint : HEX.grey }, line: { color: k === "stored" ? HEX.warnTint : HEX.grey }, objectName: "grant " + h });
  text(s, h, { x: 0.8, y: y + 0.12, w: 1.9, h: 0.4, fontSize: 17, bold: true, color: HEX.primary });
  text(s, k, { x: 0.8, y: y + 0.52, w: 1.9, h: 0.35, fontSize: 12, color: HEX.muted, italic: true });
  text(s, b, { x: 2.7, y: y + 0.12, w: 3.95, h: 0.75, fontSize: 14, valign: "middle" });
});
card(s, { x: 7.05, y: 1.45, w: 5.68, h: 2.55, fill: HEX.tint, head: "Two factors, enforced by the database", body: "Password, then a TOTP code verified inside PostgreSQL by a function that takes only the code and uses session_user. Single use; five committed failures lock for 15 minutes. Password alone → 0 rows (D026)." });
card(s, { x: 7.05, y: 4.15, w: 5.68, h: 1.6, fill: HEX.warnTint, headColor: HEX.warn, head: "Limit found at delivery", body: "A direct client can roll back failed guesses and is never locked out. Recorded as a strict expected failure; RLS unaffected." });
text(s, "Grants are derived live (D027): a materialised version once let a new portfolio do nothing until the next rebuild.", { x: 0.6, y: 5.95, w: 12.1, h: 0.6, fontSize: 14, color: HEX.muted, italic: true });
notes(s, `
  Access comes from four sources with one shape. Three are derived live from records the bank already keeps — ownership,
  dispositions, portfolios — and only delegation is stored, because only delegation is a human decision. Deriving them live came
  from a bug: a materialised grant table once made a new portfolio do nothing until the next rebuild.
  The second factor is verified by the database, so no application in front can skip it: the right password and no code reads
  nothing. One limit I found in the delivery audit and disclosed: the failure counter lives in the caller's transaction, so a
  direct client can roll its failed guesses back.`);

// ================================================================ 4. The LLM path
section("The LLM as a client");
s = slide();
title(s, "Defence in depth around a dumb and dangerous client");
table(s, [["Layer", "Enforces", "Does not"],
  ["Isolation", "No tools, no files, no database; one turn, one JSON object", "make the model right"],
  ["Semantic layer", "Meaning: certified metrics, 'is not' glossary, caveats, query rules", "check the model followed it"],
  ["SQL guard (sqlglot)", "One read-only SELECT on ai; no out-of-schema functions; LIMIT ≤ 10,000", { text: "resolve columns or judge meaning", options: { bold: true, color: HEX.block } }],
  ["Execution envelope", "Read-only transaction, 60 s timeout, at most cap + 1 rows, the user's own 2FA session", "—"],
  ["Row level security", "Which rows exist for this user, whatever the SQL says", "—"],
  ["PostgreSQL", "An unknown name is an error, recorded — never answered", "catch a valid but wrong query"],
  ["Evaluation", "Value-based comparison with independent reference SQL", "protect a live user"]],
  { x: 0.6, y: 1.45, w: 12.13, colW: [2.6, 6.33, 3.2], fontSize: 14 });
text(s, "The guard proves a query is safe to run. It does not prove it answers the question.", { x: 0.6, y: 6.2, w: 12.1, h: 0.5, fontSize: 18, bold: true, color: HEX.accent });
notes(s, `
  This is the AI path. The model runs as a pure text completion: no tools, no files, no database — if it could read the tables
  it would answer by looking, and I would be testing the agent instead of the semantic layer.
  Its SQL is parsed with sqlglot, not matched with a regex, and must be one read-only SELECT on the ai schema with a row cap it
  cannot raise. It runs read-only with a timeout, on the user's own two-factor session, so row level security decides the rows.
  The sentence on the bottom is the one I want you to remember: the guard proves the query is safe. It says nothing about
  whether it is right.`);

s = slide();
title(s, "Safe is not the same as correct");
text(s, "“Find male or female loans in Q1 1995.”", { x: 0.6, y: 1.4, w: 7, h: 0.5, fontSize: 20, bold: true, italic: true, color: HEX.primary });
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 2.0, w: 7.0, h: 2.45, rectRadius: 0.06, fill: { color: HEX.grey }, line: { color: HEX.line }, objectName: "sql" });
text(s, "SELECT COUNT(*) AS total_loans,\n  SUM(CASE WHEN T2.gender = 'male' THEN 1 ELSE 0 END) …\nFROM ai.loan T1\nJOIN ai.account_owner T2 ON T1.account_id = T2.account_id\nWHERE T1.loan_date >= '1995-01-01'\n  AND T1.loan_date <  '1995-04-01'",
  { x: 0.8, y: 2.12, w: 6.7, h: 2.25, fontSize: 13, fontFace: "Courier New", color: HEX.ink });
chip(s, 0.6, 4.65, 2.3, "GUARD: ALLOWED", HEX.info);
chip(s, 3.05, 4.65, 4.55, "DATABASE: column t2.gender does not exist", HEX.block);
text(s, "Gender lives on ai.client; ai.loan and ai.account_owner expose owner_gender. The metric text had said 'any entity with a gender column'. It failed safely — the dangerous case is valid SQL that is wrong.", { x: 0.6, y: 5.2, w: 7.0, h: 1.4, fontSize: 14 });
card(s, { x: 7.9, y: 1.4, w: 4.83, h: 5.2, fill: HEX.warnTint, headColor: HEX.warn, head: "A small local model, same layer", body: "" });
bullets(s, [{ text: "Q10: counted problematic loans instead of a share → 'monthly' (right: after transaction, 18.75%)" },
  { text: "Q6: joined to every day of the month → 279 new accounts in January instead of 106" },
  { text: "Q7: grouped by age instead of averaging it" },
  { text: "All safe. All allowed by the guard. All wrong.", options: { bold: true } }],
  { x: 8.1, y: 2.0, w: 4.45, h: 4.4, fontSize: 15 });
notes(s, `
  Here is the proof. This question came through the application. The SQL is one safe SELECT, so the guard allowed it; then the
  database rejected it because the column doesn't exist — gender lives on the client, the loan view calls it owner_gender. The
  root cause was my semantic layer saying 'any entity with a gender column'.
  That one failed safely. The dangerous version is valid SQL that is wrong, and a small local model shows exactly that: counting
  instead of a share, a fan-out join, the wrong aggregate. Every one allowed by the guard, because the guard only checks shape.
  In the delivered version my intent checker was a prototype. After submitting I built it in — I will show it at the end.`);

s = slide();
title(s, "Results — and why 10/10 is narrower than it sounds");
s.addChart(pres.charts.BAR, [
  { name: "match", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [10, 6] },
  { name: "partial", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [0, 2] },
  { name: "mismatch", labels: ["Claude Sonnet 5.5 (recorded)", "Ollama qwen2.5-coder:3b (local)"], values: [0, 2] }],
  { x: 0.6, y: 1.45, w: 6.3, h: 3.6, barDir: "bar", barGrouping: "stacked", chartColors: [HEX.info, HEX.warn, HEX.block],
    showValue: true, dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", dataLabelFormatCode: "0;;;", dataLabelFontSize: 13, dataLabelFontFace: "+mn-lt",
    showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: "+mn-lt", catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
    catAxisLabelColor: HEX.ink, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showTitle: true, title: "Ten questions, value-based verdicts", titleFontSize: 14, titleColor: HEX.primary, titleFontFace: "+mn-lt" });
text(s, "Claude: first attempt on all ten, about 2 minutes and USD 0.40, every call logged.", { x: 0.6, y: 5.2, w: 6.3, h: 0.8, fontSize: 14, color: HEX.muted });
card(s, { x: 7.15, y: 1.45, w: 5.58, h: 5.15, fill: HEX.grey, head: "What the 10/10 does not show", body: "" });
bullets(s, ["Recorded on the pack before the semantic audit (29,500 characters); not re-run with Claude at delivery",
  "The pack names which entity answers which question — no hold-out set",
  "One sample per question; one key measure compared",
  "Honest claim: the layer is good enough for a strong model on these ten — not yet proof that it generalises"],
  { x: 7.35, y: 2.05, w: 5.2, h: 4.4, fontSize: 15 });
notes(s, `
  Results. Claude answered all ten on the first attempt and all ten match independent reference SQL, compared by value, not by
  SQL text. The small local model scored six, with two partial and two wrong.
  Raise this yourself: that ten out of ten is narrower than it sounds. It was recorded on the pack before the audit, the pack
  names the questions, there is no hold-out, one sample each. What it shows is that the semantic layer is good enough for a
  strong model on these questions. A hold-out set is the next test — and after delivery I added four new questions on gender
  and quarters, which it also answered correctly with verification on.`);

s = slide();
title(s, "The ten answers, as delivered");
table(s, [["Q", "Question", "Answer"],
  ["1", "Clients per region", "south Moravia 937 · north Moravia 920 · … (client's own district, all 5,369)"],
  ["2", "Loans granted per year", "1993 2.62 m (half year) … 1997 peak 30.73 m · total 103,261,740"],
  ["3", "Share of problematic loans", "76 / 682 = 11.14% (B 31, D 45)"],
  ["4", "Average loan by owner's card", "junior 221,970 (n = 21) · gold 161,881 · no card 148,865 · classic 148,809"],
  ["5", "Top districts, incoming 1997", "Hl.m. Praha 115.13 m · Karvina 28.51 m · Ostrava 27.69 m …"],
  ["6", "New accounts per month 1996", "106 · 104 · 124 · 101 · 91 · 113 · 137 · … · 125 (1,363)"],
  ["7", "Owner age at loan start", "A 37.07 · B 39.60 · C 38.70 · D 37.00"],
  ["8", "Gold-card owners by gender", "male 53 (60.23%) · female 35 (39.77%)"],
  ["9", "Average balance end Dec 1998", "43,808.94 over 4,500 accounts (76 carried forward)"],
  ["10", "Frequency with highest problematic share", "after transaction 18.75% (6 of 32 — highest observed, not significant)"]],
  { x: 0.6, y: 1.4, w: 12.13, colW: [0.55, 3.6, 7.98], fontSize: 13 });
notes(s, `
  The ten answers. A few I would comment on if asked. Q1 counts all clients by where they live; places three to five are within
  four clients, so the definition matters. Q4: junior card owners borrow most, but on 21 loans to owners averaging seventeen —
  I'd flag that, not celebrate it. Q9 is 43,808.94 as delivered. Q10: after-transaction statements have the highest observed
  rate, but on 32 loans with a 9-to-35 percent interval — worth watching, not a finding.`);

// ================================================================ 5. Honesty
section("What went wrong, and what I learned");
s = slide();
title(s, "What I would challenge myself on");
const weak = [["The month-end tie-break", "Highest trans_id picks the closing posting; right 0.4% of the time where the balance chain decides", "Disclosed · fixed after"],
  ["Guard ≠ meaning", "A safe query can be wrong; the intent checker was a prototype", "Disclosed · fixed after"],
  ["The 10/10 is narrow", "Old pack, question labels in the pack, no hold-out, one sample", "Partly disclosed"],
  ["Disponent privacy", "Sees the owner's card; hidden values shown as 'no card'", "Found after delivery"],
  ["Scope", "Well beyond a 1–2 day brief: 2FA, web page, deployment guide, agents", "Tasks first; what I'd cut"]];
weak.forEach(([h, b, st], i) => {
  const y = 1.4 + i * 1.05;
  badge(s, i + 1, 0.6, y + 0.15, HEX.primary);
  text(s, h, { x: 1.45, y: y + 0.08, w: 3.4, h: 0.8, fontSize: 18, bold: true, color: HEX.primary, valign: "middle" });
  text(s, b, { x: 4.9, y: y + 0.08, w: 5.4, h: 0.8, fontSize: 15, valign: "middle" });
  text(s, st, { x: 10.4, y: y + 0.08, w: 2.33, h: 0.8, fontSize: 13, italic: true, color: HEX.muted, valign: "middle" });
});
notes(s, `
  Before you ask, here is what I would challenge myself on. The month-end tie-break and the guard are disclosed in the delivery,
  and I fixed both afterwards. The evaluation is narrower than ten out of ten suggests. A disponent sees the owner's card and,
  for a hidden owner, a 'no card' value that is false — row level security changed the meaning of a column, which is a lesson
  in itself. And scope: the tasks came first; the extras were requested; if I had to cut, the deployment guide, then the
  simulated agents, then the web page.`);

s = slide();
title(s, "My best-looking defect was my own bug");
stat(s, { x: 0.6, y: 1.45, w: 3.0, n: "0.4%", l: "how often the highest id was the true closing posting", color: HEX.block });
stat(s, { x: 3.75, y: 1.45, w: 3.0, n: "55 → 14", l: "material balance breaks once the order is read from the balance chain", color: HEX.accent });
stat(s, { x: 6.9, y: 1.45, w: 3.0, n: "+1.53", l: "CZK change in Q9's average (43,808.94 → 43,810.47)", color: HEX.primary });
stat(s, { x: 10.05, y: 1.45, w: 2.7, n: "107", l: "accounts with a different closing balance, up to 1,200 CZK", color: HEX.primary });
table(s, [["Account 3888, 31 Jan 1998", "trans_id", "Amount", "Balance after"],
  ["Interest credited", "3,467,643", "+1.30", "10,501.30"],
  ["Cash withdrawal — the real last posting", "1,137,901", "−1,200.00", "9,301.30"]],
  { x: 0.6, y: 3.35, w: 7.4, colW: [3.6, 1.2, 1.2, 1.4], fontSize: 13 });
card(s, { x: 8.25, y: 3.35, w: 4.48, h: 3.25, fill: HEX.accentTint, headColor: HEX.accent, head: "What I learned", body: "My report said this account was 'off by exactly 1,200 — a missing posting'. It was my tie-break reading the balance before the withdrawal. A derived check inherits the bugs of what it reads; and 'unknowable' is a hypothesis to test." });
text(s, "Each posting starts at balance_after − amount, so a day's postings form a chain; its end is the closing posting. The source did record the order.", { x: 0.6, y: 4.75, w: 7.4, h: 1.0, fontSize: 14, color: HEX.muted });
notes(s, `
  This is my favourite mistake. I assumed the source had no intra-day order and broke ties by the highest id. When I went back,
  the running balance records the order: each posting starts where the previous one ended. The highest id was right 0.4 percent
  of the time. Q9 barely moved — 1.53 CZK — but 107 accounts' closing balances changed.
  And the best-sounding defect in my report, an account off by exactly 1,200 with a 'missing posting', was this account: a 1.30
  interest credit has a higher id than the withdrawal that came after it. My reconciliation rule read my own wrong balance.
  Fifty-five material breaks became fourteen. That is the lesson I would take to any data team.`);

s = slide();
title(s, "My checks caught me — twice before delivery");
card(s, { x: 0.6, y: 1.45, w: 5.95, h: 2.55, fill: HEX.grey, head: "The self-test nearly deleted real data", headSize: 19, bodySize: 17, body: "Unscoped quarantine view: injected defects excluded real rows — 76 districts instead of 77. The grain checks failed before any deliverable was written." });
card(s, { x: 6.78, y: 1.45, w: 5.95, h: 2.55, fill: HEX.grey, head: "The filter leaked through one view", headSize: 19, bodySize: 17, body: "Three curated views were not security_invoker: ai.loan returned 682 loans to a user entitled to none. Found by logging in and counting." });
card(s, { x: 0.6, y: 4.2, w: 5.95, h: 2.4, fill: HEX.grey, head: "The demo's own query was wrong", headSize: 19, bodySize: 17, body: "sum(DISTINCT amount) as a reflex guard against fan-out dropped 37 loans that share an amount: −4,480,920 CZK. Now pinned by a test." });
card(s, { x: 6.78, y: 4.2, w: 5.95, h: 2.4, fill: HEX.grey, head: "A documented control without a test", headSize: 19, bodySize: 17, body: "The lockout was documented for weeks; writing its test at delivery found the rollback gap. Now a strict expected failure." });
notes(s, `
  The other side of the same habit: my own checks caught me. The rule self-test that almost deleted real data. The view that
  leaked every loan to a user entitled to none — the design was right, the DDL was one setting short, and only counting rows as
  the restricted user found it. A demo query that was itself wrong by four and a half million. And the lockout, which I had
  documented but never tested — writing the test found the gap. All of these are written down, not quietly fixed.`);

s = slide();
title(s, "After delivery: the two fixes, on a separate branch");
text(s, "Not merged into the submission: D028 changes a certified number, and that needs the business to sign off the rule.", { x: 0.6, y: 1.35, w: 12.1, h: 0.5, fontSize: 15, italic: true, color: HEX.post });
card(s, { x: 0.6, y: 1.95, w: 5.95, h: 4.65, fill: HEX.postTint, headColor: HEX.post, head: "D028 · closing posting = end of the balance chain", body: "" });
table(s, [["", "Delivered", "After"], ["Q9 average", "43,808.94", "43,810.47"], ["Material breaks", "55", "14"], ["Rounding band", "81", "70"], ["Ambiguous days marked", "—", "42 at book end"]],
  { x: 0.8, y: 2.55, w: 5.55, colW: [2.35, 1.6, 1.6], fontSize: 13 });
text(s, "Tested on synthetic postings and against an independent derivation: 180,000+ balances, 0 disagreements.", { x: 0.8, y: 5.25, w: 5.55, h: 1.2, fontSize: 14 });
card(s, { x: 6.78, y: 1.95, w: 5.95, h: 4.65, fill: HEX.postTint, headColor: HEX.post, head: "D029 · verify the intent, not only the shape", body: "" });
bullets(s, ["The model states metric, periods, grouping and filters next to its SQL",
  "Checked before any database session: every column, the date filter day by day, no fan-out joins",
  "Then EXPLAIN, run under RLS, recompute the certified metric — rows only if both agree",
  "The gender query is refused, naming owner_gender; 10/10 and 4 new questions 4/4, verified"],
  { x: 7.0, y: 2.55, w: 5.55, h: 3.95, fontSize: 14 });
notes(s, `
  After submitting I fixed the two most important limitations on a separate branch. I did not merge them into the delivery,
  because the first changes a certified number, and that is exactly what a governed product should not do without sign-off.
  The month-end rule now follows the balance chain and marks the days it cannot order. And the model now has to state its intent
  next to its SQL; the SQL is checked against that intent before it runs, and the certified metric is recomputed afterwards.
  The verifier's own first run refused two correct answers — a lesson too: a checker needs tests against correct answers.`);

// ================================================================ 6. Close
section("Scale and close");
s = slide();
title(s, "What breaks at 100,000× the volume");
table(s, [["What breaks", "Why", "What it becomes"],
  ["Rebuilds", "core is CREATE TABLE AS every run: hours rewriting unchanged data", "Month-partitioned facts, merge not replace"],
  ["Rule runs", "124 full scans", "Partition-scoped rules; info sampled, block exact"],
  ["Month-end fact", "32 bn rows rebuilt from scratch", "Maintained from last month + new postings"],
  ["Latency", "Ad-hoc SQL over 10 TB; one node; role-per-user pools", "Pruning on certified time columns, marts, a gateway doing SET ROLE"],
  ["Entitlement join", "Millions of accounts per large portfolio", "A materialised (role, account) set, co-partitioned"],
  ["Evaluation", "Ten questions are not a test set", "Hold-out set, frozen samples, monitoring"]],
  { x: 0.6, y: 1.45, w: 12.13, colW: [2.2, 5.0, 4.93], fontSize: 13 });
text(s, "What does not break: where the filter sits, onboarding as an insert, and the size of the semantic layer.", { x: 0.6, y: 6.15, w: 12.1, h: 0.5, fontSize: 17, bold: true, color: HEX.primary });
notes(s, `
  At a hundred thousand times — about a hundred billion postings — everything that is 'rebuild from scratch' becomes 'maintain
  incrementally', and the entitlement join becomes a materialised set. A single PostgreSQL node is the wrong host; Citus or a
  columnar engine, or a warehouse's row access policies, with the same schemas and policy model.
  What doesn't change is the design: the filter stays in the engine, onboarding stays an insert, the semantic layer stays the
  same size.`);

s = slide();
title(s, "Decisions that are not mine to make");
const open = [["Problematic loan = status B or D", "76 of 682 = 11.14% (A4)"], ["Interest counts as incoming money", "0.85% of 1997 incoming; same top ten (A7)"],
  ["Calendar, not fiscal, quarters", "There is no fiscal calendar in the source"], ["Repeated identical interest postings", "1,081 groups, 157,289.70 CZK: duplicates or not?"],
  ["Every amount is CZK", "No currency column (A19)"]];
open.forEach(([h, b], i) => {
  const y = 1.45 + i * 0.98;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y, w: 12.13, h: 0.85, rectRadius: 0.08, fill: { color: i % 2 ? HEX.grey : HEX.tint }, line: { color: i % 2 ? HEX.grey : HEX.tint }, objectName: "open decision" });
  text(s, h, { x: 0.85, y: y + 0.1, w: 5.6, h: 0.65, fontSize: 17, bold: true, color: HEX.primary, valign: "middle" });
  text(s, b, { x: 6.5, y: y + 0.1, w: 6.1, h: 0.65, fontSize: 15, valign: "middle" });
});
text(s, "Each is written down with what changes if it is wrong, and implemented in one place so it can change in one place.", { x: 0.6, y: 6.4, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: HEX.muted });
notes(s, `
  Some definitions are business decisions, and I would rather ask than guess. Problematic as B or D; interest as incoming money;
  calendar quarters; and the repeated interest postings — are they duplicates? Each is an assumption with 'what changes if it is
  wrong' next to it, and each lives in one place, so a different answer is one change.`);

s = slide("SECTION");
s.addText("Every number traceable, nothing silently repaired, the AI never trusted", { placeholder: "title" });
s.addText("The filter sits where the model's text cannot reach it. The weak spots are written down — with the evidence and the fix.", { placeholder: "body" });
notes(s, `
  To close: every number traces to a command; nothing is silently repaired or dropped; the AI is never trusted with anything it
  could get wrong quietly; and the filter sits where the model's text cannot reach it. Where it is weak, I have told you, with the
  evidence and the fix. Happy to take questions — and the backup slides cover the decision register, the security residuals and
  the Q9 detail.`);

// ================================================================ Backup
section("Backup");
s = slide();
title(s, "Backup · the decision register in one line each");
const dec = [["D002", "PostgreSQL: RLS makes Task 3 real"], ["D003", "Verified public mirror; counts match"], ["D004", "Seed defects in a separate schema"], ["D005", "Claude CLI as a sandboxed completion"],
  ["D006/17", "One code map, code beside label, checked"], ["D007", "Natural keys: one source, no history"], ["D008", "Scope the quarantine to stg"], ["D009", "Filter in the engine; identity = session_user"],
  ["D010", "Every view security_invoker"], ["D011", "Value-based evaluation"], ["D012", "Rebuilding core restores the ai surface"], ["D013", "Never repair in place"],
  ["D014", "Placeholders → NULL, original kept"], ["D015", "19xx years; failed parse = NULL"], ["D016", "Gender and birth date derived, labelled"], ["D018", "Sign resolved once (VYBER is a debit)"],
  ["D019", "Month-end decided once (tie-break)"], ["D020", "Graded, not gated"], ["D021", "A customer IS one client"], ["D023", "Customers see what they may operate"],
  ["D024", "A disposition grants the account, not the person"], ["D025", "Three identifiers, three exposures"], ["D026", "2FA enforced by the database"], ["D027", "Derive grants; store only human decisions"]];
dec.forEach(([id, t], i) => {
  const col = Math.floor(i / 12), row = i % 12;
  const x = 0.6 + col * 6.15, y = 1.4 + row * 0.45;
  text(s, id, { x, y, w: 1.05, h: 0.4, fontSize: 13, bold: true, color: HEX.accent, valign: "middle" });
  text(s, t, { x: x + 1.1, y, w: 4.9, h: 0.4, fontSize: 13, valign: "middle" });
});
notes(s, `Backup. D022 is superseded by D023. D001 (repository at the git root) is omitted. Full text in the study guide, chapter 18.`);

s = slide();
title(s, "Backup · security residuals, stated before they are asked");
table(s, [["Residual", "Status", "Fix"],
  ["Direct client rolls back failed second-factor guesses", "Disclosed (strict xfail)", "Count attempts outside the caller's transaction, or gateway-only logins"],
  ["Session bound to backend PID only", "A45", "Compare backend_start too"],
  ["Disponent sees the owner's card and disposition row", "Found after delivery", "Holder-based card policy; own-row dispositions; tests"],
  ["Hidden owner fields shown as 'no card' / NULL", "Found after delivery", "No coalesce over RLS-hidden joins; say 'not visible'"],
  ["TOTP secrets recoverable; demo shows codes", "A44, A46", "Encrypt with an external key; real enrolment"],
  ["No read audit, no field masking, role-per-user pooling", "Recommended", "Audit log; masking; pool per role or SET ROLE gateway"]],
  { x: 0.6, y: 1.45, w: 12.13, colW: [4.6, 2.6, 4.93], fontSize: 13 });
notes(s, `Backup for security questions. Row level security itself is not affected by any of these: without the second factor a principal reads no rows.`);

s = slide();
title(s, "Backup · Q9 under different closing-posting rules");
table(s, [["Rule for the closing posting of a busy day", "Average at 1998-12-31"],
  ["Highest trans_id (delivered)", "43,808.94"],
  ["Balance chain, lowest id where ambiguous (D028, after delivery)", "43,810.47"],
  ["Balance chain, highest id where ambiguous", "43,810.73"],
  ["Lowest trans_id only", "43,808.90"]],
  { x: 0.6, y: 1.45, w: 8.0, colW: [5.6, 2.4], fontSize: 14 });
table(s, [["Typical wrong answer", "Rows", "Average"],
  ["Join on max(date) without a tie-break", "4,707", "43,508.31"],
  ["Only accounts with a December posting", "4,424", "44,209.53"],
  ["Average of every December posting", "23,553", "46,908.00"]],
  { x: 0.6, y: 4.3, w: 8.0, colW: [4.6, 1.5, 1.9], fontSize: 14 });
card(s, { x: 8.9, y: 1.45, w: 3.83, h: 5.15, fill: HEX.grey, head: "What to say", body: "The average is robust to the rule — within 2 CZK. Individual balances are not: 107 accounts differ. That is why the rule had to be fixed, not the average." });
notes(s, `Backup for Q9. 76 accounts carry November forward; the average covers all 4,500 accounts with a known balance and counts none as zero.`);

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", path.relative(ROOT, OUT));
})();
