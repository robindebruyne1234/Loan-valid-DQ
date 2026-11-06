// "The evidence, in numbers": found insights and the ten answers as BI visuals.
// Called from build_defense.js; every figure comes from bi_stats.json (python study_pack/deck/bi_stats.py),
// which re-runs the delivered reference SQL and stops if any answer differs from the delivered one.
const S = require("./bi_stats.json");

module.exports = function addBiSlides(k) {
  const { pres, H, slide, title, notes, text, box, label, iconCircle, section } = k;
  const SLATE = "334E68", SLATE_TINT = "E4EAF1";
  const CAT = { clients: ["Clients", H.primary], loans: ["Loans", H.accent], money: ["Money", H.info], spread: ["Spread", SLATE] };
  const LIGHT = { [H.primary]: "7FB8A4", [H.accent]: "E3A27A", [H.info]: "7CC4A0", [SLATE]: "9FB3C8" };

  // ------------------------------------------------------------ helpers
  const f = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const m = (n, d = 2) => f(n / 1e6, d) + " m";
  const pct = (n, d = 1) => f(n, d) + "%";
  const ci = (c, d = 1) => `${f(c[0], d)}–${f(c[1], d)}%`;
  const FONT = "+mn-lt";
  function catStrip(s, keys, on, caption) {
    const w = keys.length === 4 ? 0.76 : 1.0, gap = 0.03, x0 = 12.73 - keys.length * w - (keys.length - 1) * gap, y0 = 0.48;
    keys.forEach((key, i) => {
      const [n, c] = CAT[key], lit = key === on;
      s.addText(n, { shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.05, x: x0 + i * (w + gap), y: y0, w, h: 0.5,
        fill: { color: lit ? c : H.off }, line: { color: lit ? c : H.off }, fontSize: 11, bold: true,
        color: lit ? "FFFFFF" : H.faint, align: "center", valign: "middle", margin: 0, objectName: "category " + n });
    });
    text(s, caption, { x: x0, y: y0 + 0.53, w: keys.length * (w + gap), h: 0.25, fontSize: 10, color: H.faint, align: "center" });
  }
  const INSIGHT = (s, on) => catStrip(s, ["clients", "loans", "money", "spread"], on, "insight category");
  const QUESTION = (s, on) => catStrip(s, ["clients", "loans", "money"], on, "question category");
  // a row of KPI tiles: [[value, label], ...]
  function kpis(s, items, color, y = 5.4, h = 1.25) {
    const gap = 0.15, w = (12.13 - gap * (items.length - 1)) / items.length;
    items.forEach(([v, l], i) => {
      const x = 0.6 + i * (w + gap);
      box(s, { x, y, w, h, fill: H.grey });
      s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.12, w: 0.06, h: h - 0.24, fill: { color }, line: { color }, objectName: "kpi bar" });
      text(s, v, { x: x + 0.2, y: y + 0.12, w: w - 0.3, h: 0.5, fontSize: v.length > 14 ? 17 : 21, bold: true, color, valign: "middle" });
      text(s, l, { x: x + 0.2, y: y + 0.62, w: w - 0.3, h: h - 0.7, fontSize: 11.5, color: H.muted });
    });
  }
  const AX = { catAxisLabelFontSize: 11, catAxisLabelFontFace: FONT, catAxisLabelColor: H.ink, valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
    dataLabelFontSize: 11, dataLabelFontFace: FONT, dataLabelColor: H.ink, showTitle: true, titleFontSize: 13,
    titleColor: H.primary, titleFontFace: FONT };
  function bars(s, title_, labels, values, o) {
    s.addChart(pres.charts.BAR, [{ name: title_, labels, values }], Object.assign({}, AX,
      { barDir: "col", chartColors: [o.color], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "#,##0",
        barGapWidthPct: 45, title: title_ }, o));
  }
  function pie(s, title_, labels, values, colors, o) {
    s.addChart(o.doughnut ? pres.charts.DOUGHNUT : pres.charts.PIE, [{ name: title_, labels, values }], Object.assign({
      chartColors: colors, showPercent: true, showValue: false, showLegend: true, legendPos: "b", legendFontSize: 10.5,
      legendFontFace: FONT, legendColor: H.ink, dataLabelColor: "FFFFFF", dataLabelFontSize: 11, dataLabelFontFace: FONT,
      dataLabelFormatCode: "0.0%", dataLabelPosition: o.doughnut ? undefined : "bestFit", holeSize: o.doughnut ? 55 : undefined,
      showTitle: true, title: title_, titleFontSize: 13, titleColor: H.primary, titleFontFace: FONT, firstSliceAng: 0,
      x: o.x, y: o.y, w: o.w, h: o.h }, o.opts || {}));
  }
  function card(s, x, y, w, h, lines, color) { // a small takeaway card under a chart
    box(s, { x, y, w, h, fill: H.grey });
    s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.1, w: 0.06, h: h - 0.2, fill: { color }, line: { color }, objectName: "card bar" });
    s.addText(lines.map((t, i) => ({ text: typeof t === "string" ? t : t.text, options: { breakLine: i < lines.length - 1, paraSpaceAfter: 4,
      bold: i === 0, italic: typeof t !== "string", color: typeof t !== "string" ? t.color : i === 0 ? H.ink : H.muted } })),
      { isTextBox: true, x: x + 0.2, y: y + 0.08, w: w - 0.3, h: h - 0.16, fontSize: 12, margin: 0, valign: "top" });
  }

  const C = S.clients, L = S.loans, T = S.money, A = S.accounts, Q = S.q;
  const q = (k_) => Q[k_].rows;

  // ------------------------------------------------------------ divider
  section("4 · Evidence in numbers");
  let s = slide("SECTION");
  s.addText("The evidence, in numbers", { placeholder: "title" });
  s.addText("First what the data says (found insights), then the ten answers — each grouped by category, each figure recomputed from the database and checked against the delivered answer.", { placeholder: "body" });
  [["users", "Clients"], ["balance", "Loans & risk"], ["chart", "Accounts & money"], ["search", "Spread & outliers"]].forEach(([ic, n], i) => {
    const x = 0.8 + i * 3.0;
    iconCircle(s, ic, x, 5.6, 0.75, i === 3 ? SLATE : i === 1 ? H.accent : i === 2 ? H.info : "1F6F64");
    text(s, n, { x: x + 0.9, y: 5.75, w: 2.0, h: 0.45, fontSize: 16, bold: true, color: "FFFFFF" });
  });
  notes(s, `
    [15 seconds] An optional block of about ten minutes. If time is short, show only 'the ten answers at a glance' and
    'spread and outliers'. Every number on these slides comes from bi_stats.json, produced by study_pack/deck/bi_stats.py:
    it re-runs the delivered reference SQL and stops if any answer differs from what I handed in.`);

  // ------------------------------------------------------------ insights: clients
  s = slide();
  title(s, "Clients: every age group, an even gender split");
  INSIGHT(s, "clients");
  bars(s, "Clients by age band (age on 31 Dec 1998)", C.age_bands.labels, C.age_bands.values,
    { x: 0.6, y: 1.4, w: 6.3, h: 3.85, color: H.primary });
  pie(s, "Gender (derived)", ["male", "female"], [C.gender.male, C.gender.female], [H.primary, LIGHT[H.primary]],
    { x: 7.1, y: 1.4, w: 2.75, h: 3.85 });
  const own = C.roles.find((r) => r.role === "owner").n, disp = C.roles.find((r) => r.role === "disponent").n;
  pie(s, "Role on an account", [`owner (${f(own)})`, `disponent (${f(disp)})`], [own, disp], [H.primary, H.accent],
    { x: 9.98, y: 1.4, w: 2.75, h: 3.85, doughnut: true });
  kpis(s, [[f(C.n), "clients (persons)"], [`${f(C.age.mean, 1)} ± ${f(C.age.sd, 1)}`, "mean age ± σ, years"],
    [`${f(C.age.p["5"], 0)} · ${f(C.age.p["50"], 0)} · ${f(C.age.p["95"], 0)}`, "P5 · median · P95 age"],
    [f(C.under_18), "clients under 18 on 31 Dec 1998"], [pct(100 * disp / C.n), "are only a disponent (helper) on someone else's account"]], H.primary);
  notes(s, `
    [1 minute] Clients are spread evenly from twenty to sixty, with a long tail past seventy: the mean age is ${f(C.age.mean, 1)}
    with a standard deviation of ${f(C.age.sd, 1)} years, and no statistical outliers. Gender is derived from the birth
    number and labelled as derived (D016): ${pct(100 * C.gender.male / C.n)} male. One client in six is only a disponent — that
    is why "clients" and "account owners" are different answers (A2). ${C.under_18} clients are under 18 at the end of the
    data. Source: bi_stats.json → clients.`);

  // ------------------------------------------------------------ insights: loans
  s = slide();
  title(s, "Loans: the ones that went wrong were bigger");
  INSIGHT(s, "loans");
  const st = L.status;
  pie(s, "Loan status (682 loans)", [`A paid (${st.A})`, `B default (${st.B})`, `C running (${st.C})`, `D in debt (${st.D})`],
    [st.A, st.B, st.C, st.D], [H.info, H.block, LIGHT[H.info], H.warn], { x: 0.6, y: 1.4, w: 3.9, h: 3.85 });
  bars(s, "Average loan amount (CZK)", ["healthy (A or C)", "problematic (B or D)"], [L.avg_amount_ok, L.avg_amount_problematic],
    { x: 4.65, y: 1.4, w: 3.9, h: 3.85, color: H.accent });
  bars(s, "Problematic share by loan duration", L.by_duration.map((d) => `${d.months} m`), L.by_duration.map((d) => d.pct / 100),
    { x: 8.7, y: 1.4, w: 4.03, h: 3.85, color: LIGHT[H.accent], dataLabelFormatCode: "0.0%" });
  kpis(s, [[`${f(L.amount.mean)}`, `mean loan, CZK (σ ${f(L.amount.sd)})`],
    [`${f(L.amount.p["25"] / 1000, 0)}k · ${f(L.amount.p["50"] / 1000, 0)}k · ${f(L.amount.p["75"] / 1000, 0)}k`, "P25 · median · P75 loan amount, CZK"],
    [`+${f(100 * (L.avg_amount_problematic / L.avg_amount_ok - 1), 0)}%`, "bigger, on average, when the loan went wrong"],
    [`${pct(L.share_by_volume, 2)}`, `problematic by volume, against ${pct(100 * (st.B + st.D) / L.n, 2)} by count`],
    [`${L.amount.out_hi}`, `outliers above ${f(L.amount.fence_hi)} (Tukey), max ${f(L.amount.max)}`]], H.accent);
  notes(s, `
    [1 minute] One loan in nine went wrong (B or D). The bad ones were bigger: ${f(L.avg_amount_problematic)} on average
    against ${f(L.avg_amount_ok)} — so by volume the problematic share is ${pct(L.share_by_volume, 2)}, not 11.14%. Duration does
    not explain it: 12-month loans look a little safer (${pct(L.by_duration[0].pct)}), but every duration's 95% interval overlaps
    the others (${ci(L.by_duration[0].ci95)} for 12 months, ${ci(L.by_duration[1].ci95)} for 24). Loan amounts are right-skewed:
    mean ${f(L.amount.mean)}, median ${f(L.amount.p["50"])}, σ ${f(L.amount.sd)}; ${L.amount.out_hi} loans sit above the Tukey
    fence. Source: bi_stats.json → loans.`);

  // ------------------------------------------------------------ insights: money flow
  s = slide();
  title(s, "Money flow: a cash bank, growing every year");
  INSIGHT(s, "money");
  bars(s, "Transaction volume per year (CZK m)", T.by_year.map((r) => String(r.year)), T.by_year.map((r) => r.volume / 1e6),
    { x: 0.6, y: 1.4, w: 4.3, h: 3.85, color: H.info });
  const ops = T.by_operation, opn = (n) => ops.find((r) => r.operation === n).volume;
  const other = T.volume - opn("cash deposit") - opn("cash withdrawal") - opn("collection from another bank") - opn("remittance to another bank");
  // the 0.7% slice sits between the two big cash slices so its label does not collide with a neighbour's
  pie(s, "Volume by operation", ["cash deposit", "interest + card", "cash withdrawal", "to another bank", "from another bank"],
    [opn("cash deposit"), other, opn("cash withdrawal"), opn("remittance to another bank"), opn("collection from another bank")],
    [H.info, H.faint, LIGHT[H.info], LIGHT[H.accent], H.primary], { x: 5.05, y: 1.4, w: 3.75, h: 3.85, doughnut: true });
  const cr = T.by_direction.find((r) => r.direction === "credit"), db = T.by_direction.find((r) => r.direction === "debit");
  s.addChart(pres.charts.BAR, [
    { name: "credit (in)", labels: ["postings", "value"], values: [cr.n / T.n, cr.volume / T.volume] },
    { name: "debit (out)", labels: ["postings", "value"], values: [db.n / T.n, db.volume / T.volume] }],
    Object.assign({}, AX, { x: 8.95, y: 1.4, w: 3.78, h: 3.85, barDir: "col", barGrouping: "stacked", chartColors: [H.info, H.accent],
      showValue: true, dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", dataLabelFormatCode: "0%", valAxisMaxVal: 1,
      showLegend: true, legendPos: "b", legendFontSize: 10.5, legendFontFace: FONT, barGapWidthPct: 60, title: "Credit vs debit" }));
  const cash = 100 * (opn("cash deposit") + opn("cash withdrawal")) / T.volume;
  kpis(s, [[f(T.n), `postings, ${f(T.volume / 1e9, 2)} bn CZK moved`],
    [`${f(T.amount.mean)} ± ${f(T.amount.sd)}`, "mean ± σ per posting (σ > mean: heavily skewed)"],
    [`${f(T.amount.p["50"] / 1000, 1)}k · ${f(T.amount.p["95"] / 1000, 1)}k · ${f(T.amount.p["99"] / 1000, 1)}k`, "median · P95 · P99 posting, CZK"],
    [pct(cash, 0), "of all value moved in cash"],
    [`${pct(T.amount.out_pct)} → ${pct(T.amount.out_hi_share_of_sum, 0)}`, `of postings are outliers (> ${f(T.amount.fence_hi)}) and carry this share of value`]], H.info);
  notes(s, `
    [1 minute] The bank grew every year: ${m(T.by_year[1].volume, 0)} moved in 1994, ${m(T.by_year[5].volume, 0)} in 1998.
    It is a cash bank: ${pct(cash, 0)} of the value is cash deposits and withdrawals; card withdrawals are a fraction of a percent.
    Debits are ${pct(100 * db.n / T.n, 0)} of postings but only ${pct(100 * db.volume / T.volume, 0)} of value. Amounts are very
    skewed: the mean posting is ${f(T.amount.mean)} against a median of ${f(T.amount.p["50"])}, and the ${pct(T.amount.out_pct)} of
    postings above the Tukey fence carry ${pct(T.amount.out_hi_share_of_sum, 0)} of all value — so an average transaction is
    not a typical one. Source: bi_stats.json → money.`);

  // ------------------------------------------------------------ insights: accounts and cards
  s = slide();
  title(s, "Accounts: monthly statements, few cards");
  INSIGHT(s, "money");
  bars(s, "Accounts opened per year", A.opened_by_year.map((r) => String(r.year)), A.opened_by_year.map((r) => r.n),
    { x: 0.6, y: 1.4, w: 4.3, h: 3.85, color: H.info });
  pie(s, "Statement frequency (4,500 accounts)", A.frequency.map((r) => r.f), A.frequency.map((r) => r.n), [H.info, LIGHT[H.info], H.accent],
    { x: 5.05, y: 1.4, w: 3.75, h: 3.85 });
  pie(s, `Card types (${f(A.cards.reduce((a, r) => a + r.n, 0))} cards)`, A.cards.map((r) => r.t), A.cards.map((r) => r.n), [H.primary, LIGHT[H.primary], "C9A227"],
    { x: 8.95, y: 1.4, w: 3.78, h: 3.85, doughnut: true });
  const monthly = A.frequency.find((r) => r.f === "monthly").n;
  kpis(s, [[f(A.n), "accounts, opened 1993–1997"], [pct(100 * monthly / A.n), "get a monthly statement"],
    [pct(100 * A.with_loan / A.n), `of accounts carry a loan (${f(A.with_loan)})`],
    [pct(100 * A.owners_with_card / A.n), `of owners hold a card (${f(A.owners_with_card)})`],
    [`${f(A.balance.mean)} ± ${f(A.balance.sd)}`, "balance on 31 Dec 1998, mean ± σ (delivered rule)"]], H.info);
  notes(s, `
    [1 minute] Openings came in two waves, 1993 and 1996. Almost every account (${pct(100 * monthly / A.n)}) gets a monthly
    statement, which is why Q10's 'after transaction' group is so small. Only one owner in five holds a card, mostly classic.
    The ${A.cards.find((r) => r.t === "junior").n} junior cards belong to owners aged ${f(A.card_owner_age.junior.min, 0)}–${f(A.card_owner_age.junior.max, 0)}
    on 31 Dec 1998 (mean ${f(A.card_owner_age.junior.mean, 1)}): the young population behind Q4's surprising junior result. The month-end
    balance uses the delivered rule (highest trans_id on the last day); the later balance-chain fix moves the mean by +1.53.
    Source: bi_stats.json → accounts.`);

  // ------------------------------------------------------------ insights: spread and outliers
  s = slide();
  title(s, "Spread and outliers: where the average misleads");
  INSIGHT(s, "spread");
  const rowsBP = [
    ["Client age", `years · ${f(C.n)} clients`, C.age, 0, 100, "0", "100", (v) => f(v, 1)],
    ["Loan amount", `CZK · ${f(L.n)} loans`, L.amount, 0, 600000, "0", "600k", (v) => f(v)],
    ["Monthly loan payment", `CZK · ${f(L.n)} loans`, L.payment, 0, 11000, "0", "11k", (v) => f(v)],
    ["Transaction amount", `CZK · ${f(T.n)} postings`, T.amount, 0, 90000, "0", "90k", (v) => f(v)],
    ["Balance, 31 Dec 1998", `CZK · ${f(A.n)} accounts`, A.balance, -30000, 140000, "−30k", "140k", (v) => f(v)]];
  const PX = 2.85, PW = 4.5, RY = 1.88, RH = 0.88;
  const hdr = { fontSize: 12, bold: true, color: H.primary };
  text(s, "Measure", Object.assign({ x: 0.6, y: 1.5, w: 2.1, h: 0.33, valign: "middle" }, hdr));
  text(s, "Distribution (each on its own scale)", Object.assign({ x: PX, y: 1.5, w: PW, h: 0.33, valign: "middle" }, hdr));
  rowsBP.forEach(([n, unit, d, lo, hi, loT, hiT], i) => {
    const yc = RY + i * RH + RH / 2, X = (v) => PX + (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo) * PW;
    text(s, n, { x: 0.6, y: yc - 0.3, w: 2.15, h: 0.3, fontSize: 13.5, bold: true, color: H.ink });
    text(s, unit, { x: 0.6, y: yc + 0.02, w: 2.15, h: 0.3, fontSize: 10.5, color: H.muted });
    s.addShape(pres.shapes.LINE, { x: PX, y: yc + 0.27, w: PW, h: 0, line: { color: H.line, width: 0.75 }, objectName: "axis" });
    text(s, loT, { x: PX - 0.2, y: yc + 0.29, w: 0.4, h: 0.16, fontSize: 8.5, color: H.faint, align: "center" });
    text(s, hiT, { x: PX + PW - 0.25, y: yc + 0.29, w: 0.5, h: 0.16, fontSize: 8.5, color: H.faint, align: "center" });
    if (d.out_hi > 0) {
      s.addShape(pres.shapes.RECTANGLE, { x: X(d.fence_hi), y: yc - 0.2, w: X(d.max) - X(d.fence_hi), h: 0.4, fill: { color: H.blockTint }, line: { color: H.blockTint }, objectName: "outlier zone" });
      s.addShape(pres.shapes.OVAL, { x: X(d.max) - 0.045, y: yc - 0.045, w: 0.09, h: 0.09, fill: { color: H.block }, line: { color: H.block }, objectName: "max" });
      text(s, `${f(d.out_hi)} outliers`, { x: X(d.fence_hi), y: yc - 0.42, w: Math.max(1.2, X(d.max) - X(d.fence_hi)), h: 0.2, fontSize: 9, bold: true, color: H.block });
    }
    s.addShape(pres.shapes.LINE, { x: X(d.p["5"]), y: yc, w: Math.max(0.001, X(d.p["95"]) - X(d.p["5"])), h: 0, line: { color: H.ink, width: 1.25 }, objectName: "whisker" });
    [d.p["5"], d.p["95"]].forEach((v) => s.addShape(pres.shapes.LINE, { x: X(v), y: yc - 0.09, w: 0, h: 0.18, line: { color: H.ink, width: 1.25 }, objectName: "cap" }));
    s.addShape(pres.shapes.RECTANGLE, { x: X(d.p["25"]), y: yc - 0.16, w: Math.max(0.03, X(d.p["75"]) - X(d.p["25"])), h: 0.32, fill: { color: SLATE_TINT }, line: { color: SLATE, width: 1 }, objectName: "box" });
    s.addShape(pres.shapes.LINE, { x: X(d.p["50"]), y: yc - 0.16, w: 0, h: 0.32, line: { color: SLATE, width: 2.5 }, objectName: "median" });
    s.addShape(pres.shapes.DIAMOND, { x: X(d.mean) - 0.075, y: yc - 0.075, w: 0.15, h: 0.15, fill: { color: H.accent }, line: { color: "FFFFFF", width: 0.5 }, objectName: "mean" });
  });
  const tb = [["Mean", "σ", "P5", "Median", "P95", "Outliers"]].concat(rowsBP.map(([, , d, , , , , fm]) => [
    fm(d.mean), fm(d.sd), fm(d.p["5"]), fm(d.p["50"]), fm(d.p["95"]),
    d.out_hi + d.out_lo === 0 ? "none" : `${f(d.out_hi + d.out_lo)}\n${pct(d.out_pct)}`]));
  s.addTable(tb.map((r, ri) => r.map((c, ci_) => ({ text: c, options: ri === 0
    ? { bold: true, color: H.primary, fontSize: 12, border: [{ type: "none" }, { type: "none" }, { pt: 1.5, color: H.primary }, { type: "none" }] }
    : { color: ci_ === 5 && c !== "none" ? H.block : ci_ === 1 ? SLATE : H.ink, bold: ci_ === 1 || (ci_ === 5 && c !== "none"),
        border: [{ type: "none" }, { type: "none" }, { pt: 0.5, color: H.line }, { type: "none" }] } }))),
    { x: 7.55, y: 1.45, w: 5.18, colW: [0.86, 0.86, 0.76, 0.86, 0.86, 0.98], rowH: [0.43].concat(rowsBP.map(() => RH)),
      fontFace: "Calibri", fontSize: 12, align: "right", valign: "middle", margin: [2, 4, 2, 4] });
  s.addShape(pres.shapes.LINE, { x: 0.6, y: 1.88, w: 6.85, h: 0, line: { color: H.primary, width: 1.5 }, objectName: "header rule" });
  s.addText([{ text: "Box = P25–P75 · bar = median · " }, { text: "◆", options: { color: H.accent } },
    { text: " = mean · whiskers = P5–P95 · red zone = Tukey outliers (above Q3 + 1.5 × IQR) · σ = sample standard deviation" }],
    { isTextBox: true, x: 0.6, y: 6.33, w: 12.13, h: 0.3, fontSize: 10.5, color: H.muted, margin: 0, valign: "top" });
  notes(s, `
    [1–2 minutes] Five measures, each on its own scale. Where the diamond (mean) sits right of the bar (median), the average is
    pulled up by a long tail. Ages and loan payments are well behaved: no outliers. Loan amounts have ${L.amount.out_hi} large loans
    above the fence. Transactions are the extreme case: σ (${f(T.amount.sd)}) is larger than the mean (${f(T.amount.mean)}), and
    ${f(T.amount.out_hi)} postings above ${f(T.amount.fence_hi)} carry ${pct(T.amount.out_hi_share_of_sum, 0)} of all value. These
    are not errors: the data quality rules check validity, and a large salary is valid. Outliers are reported, never removed.
    Balances: ${A.balance.out_hi} accounts above ${f(A.balance.fence_hi)}, and ${Q.Q9.rows[0].accounts_overdrawn} overdrawn.
    Method: sample standard deviation; percentiles by linear interpolation, the same as PostgreSQL percentile_cont.`);

  // ------------------------------------------------------------ the ten answers at a glance
  s = slide("WIDE");
  title(s, "The ten answers at a glance");
  const r1 = q("Q1"), r2 = q("Q2"), r3 = q("Q3")[0], r4 = q("Q4"), r5 = q("Q5"), r6 = q("Q6"), r7 = q("Q7"), r8 = q("Q8"), r9 = q("Q9")[0], r10 = q("Q10");
  const male = r8.find((r) => r.gender === "male");
  const card4 = (c) => r4.find((r) => r.owner_card_type === c);
  const peak2 = r2.reduce((a, r) => (r.total_amount > a.total_amount ? r : a));
  const peak6 = r6.reduce((a, r) => (r.accounts_opened > a.accounts_opened ? r : a));
  const ages = r7.map((r) => r.average_age_at_loan_start), sds = Object.values(Q.Q7.by_status).map((v) => v.sd);
  const cols = [
    ["Clients · Q1 Q7 Q8", H.primary, [
      ["Q1 · Clients per region", f(r1[0].clients), `${r1[0].region} (${pct(r1[0].pct_of_clients)})`, `8 regions · ${f(C.n)} clients · top two ${pct(C.regions_top2_pct)}`],
      ["Q7 · Owner age at loan start", `${f(Math.min(...ages), 1)}–${f(Math.max(...ages), 1)}`, "years, by status", `B oldest (${f(r7[1].average_age_at_loan_start, 2)}) · σ ${f(Math.min(...sds), 1)}–${f(Math.max(...sds), 1)} yrs per status`],
      ["Q8 · Gold-card owners by gender", pct(male.pct_of_gold_card_owners, 2), `male (${male.gold_card_owners} of ${r8.reduce((a, r) => a + r.gold_card_owners, 0)})`, `95% CI ${ci(Q.Q8.male_ci95)} · all owners ${pct(Q.Q8.male_pct_all_owners)} male`]],
      "The owner is decided once: whose district, card and age (A1, A5, A10). Q8 leans male, but its 95% interval includes 50%."],
    ["Loans & risk · Q2 Q3 Q4 Q10", H.accent, [
      ["Q2 · Loans granted, 1993–1998", m(r2.reduce((a, r) => a + r.total_amount, 0)), `CZK, ${f(r3.total_loans)} loans`, `peak ${peak2.year}: ${m(peak2.total_amount)} · 1993 is a half year`],
      ["Q3 · Problematic loans (B or D)", pct(r3.problematic_pct, 2), `${r3.problematic_loans} of ${r3.total_loans}`, `95% CI ${ci(Q.Q3.ci95)} · ${pct(Q.Q3.share_by_volume, 2)} by volume`],
      ["Q4 · Average loan by owner's card", f(card4("junior").average_loan_amount), `junior (n = ${card4("junior").loans})`, `±${f(Q.Q4.by_card.junior.ci95)} (95%) · classic ${f(card4("classic").average_loan_amount)}`],
      ["Q10 · Problematic share by statements", pct(r10[0].problematic_pct, 2), r10[0].statement_frequency, `${r10[0].problematic_loans} of ${r10[0].loans} · CI ${ci(r10[0].ci95)} · Fisher p = ${f(Q.Q10.fisher_p_top_vs_rest, 2)}`]],
      null],
    ["Accounts & money · Q5 Q6 Q9", H.info, [
      ["Q5 · Top district, incoming 1997", m(r5[0].total_incoming_amount), r5[0].district_name, `${pct(100 * r5[0].total_incoming_amount / Q.Q5.total_incoming_1997)} of all incoming · ${f(r5[0].total_incoming_amount / r5[1].total_incoming_amount, 1)}× the next district`],
      ["Q6 · New accounts, 1996", f(r6.reduce((a, r) => a + r.accounts_opened, 0)), "in the year", `${f(Q.Q6.mean, 1)} a month · σ ${f(Q.Q6.sd, 1)} · peak ${peak6.month_name.slice(0, 3)} ${peak6.accounts_opened} (+${f(Q.Q6.z_max, 1)}σ)`],
      ["Q9 · Average balance, 31 Dec 1998", f(r9.average_balance, 2), `CZK, ${f(r9.accounts_with_known_balance)} accounts`, `median ${f(r9.median_balance)} · σ ${f(Q.Q9.dist.sd)} · ${r9.accounts_overdrawn} overdrawn`]],
      "Q9 is the delivered closing rule. The later balance-chain fix gives 43,810.47 (+1.53) — not in the delivered version."]];
  const TH = 1.12, TG = 0.08, CW = 3.95;
  cols.forEach(([hd, c, tiles, note], ci_) => {
    const x = 0.6 + ci_ * (CW + 0.14);
    label(s, hd, { x, y: 1.38, w: CW, h: 0.45, fill: c, fontSize: 14 });
    tiles.forEach(([t, v, sub, det], ti) => {
      const y = 1.93 + ti * (TH + TG);
      box(s, { x, y, w: CW, h: TH, fill: H.grey });
      s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.1, w: 0.06, h: TH - 0.2, fill: { color: c }, line: { color: c }, objectName: "tile bar" });
      text(s, t, { x: x + 0.2, y: y + 0.07, w: CW - 0.3, h: 0.27, fontSize: 12, bold: true, color: c });
      s.addText([{ text: v, options: { fontSize: 22, bold: true, color: H.ink } }, { text: "  " + sub, options: { fontSize: 12, color: H.muted } }],
        { isTextBox: true, x: x + 0.2, y: y + 0.34, w: CW - 0.3, h: 0.42, margin: 0, valign: "middle", fit: "shrink" });
      text(s, det, { x: x + 0.2, y: y + 0.78, w: CW - 0.3, h: 0.28, fontSize: 10.5, color: H.muted, fit: "shrink" });
    });
    if (note) {
      const y = 1.93 + 3 * (TH + TG);
      box(s, { x, y, w: CW, h: TH, fill: ci_ === 2 ? H.postTint : H.tint });
      text(s, note, { x: x + 0.2, y: y + 0.1, w: CW - 0.35, h: TH - 0.2, fontSize: 11.5, italic: true, color: ci_ === 2 ? H.post : H.primary, valign: "middle" });
    }
  });
  notes(s, `
    [90 seconds] All ten on one page, grouped the way the business would ask them: who the clients are, how the loans
    behave, how the money moves. Each tile has the delivered answer, then the number that tells you how much to trust it:
    a standard deviation, a 95% interval or a test. Two answers deserve the caution out loud: Q10's 18.75% rests on 32 loans
    (Fisher p = ${f(Q.Q10.fisher_p_top_vs_rest, 2)}, not significant), and Q4's junior average rests on 21 loans of very young
    owners. Every value was recomputed from the database with the delivered reference SQL and matched exactly.`);

  // ------------------------------------------------------------ questions: clients
  s = slide();
  title(s, "Q1 · Q7 · Q8 — clients and demographics");
  QUESTION(s, "clients");
  s.addChart(pres.charts.BAR, [{ name: "clients", labels: r1.map((r) => r.region), values: r1.map((r) => r.clients) }], Object.assign({}, AX,
    { x: 0.6, y: 1.4, w: 4.6, h: 3.85, barDir: "bar", chartColors: [H.primary], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "#,##0", catAxisOrientation: "maxMin", barGapWidthPct: 40, title: "Q1 · Clients per region (own district)" }));
  bars(s, "Q7 · Average owner age at loan start", r7.map((r) => ({ A: "A paid", B: "B default", C: "C running", D: "D in debt" })[r.status_code]),
    r7.map((r) => r.average_age_at_loan_start), { x: 5.35, y: 1.4, w: 3.9, h: 3.85, color: H.primary, dataLabelFormatCode: "0.00", valAxisMinVal: 0 });
  pie(s, "Q8 · Gold-card owners by gender", r8.map((r) => `${r.gender} (${r.gold_card_owners})`), r8.map((r) => r.gold_card_owners),
    [H.primary, LIGHT[H.primary]], { x: 9.4, y: 1.4, w: 3.33, h: 3.85 });
  const under15 = Object.values(Q.Q7.by_status).reduce((a, v) => a + v.under_15, 0);
  card(s, 0.6, 5.4, 4.6, 1.25, [`Top two regions hold ${pct(C.regions_top2_pct)} of clients`, `All ${f(C.n)} clients, by their own district (A1, A2)`,
    `Places 3–5 differ by ${r1[2].clients - r1[4].clients} clients: the reading decides their order`], H.primary);
  card(s, 5.35, 5.4, 3.9, 1.25, [`σ ${f(Math.min(...sds), 1)}–${f(Math.max(...sds), 1)} years in every status`, `B ±${f(Q.Q7.by_status.B.ci95, 1)} yrs (95%): the gaps are noise`,
    `${under15} owners under 15, flagged · without them A ${f(r7[0].average_age_excluding_flagged, 2)}, C ${f(r7[2].average_age_excluding_flagged, 2)}`], H.primary);
  card(s, 9.4, 5.4, 3.33, 1.25, [`95% CI ${ci(Q.Q8.male_ci95)}`, `All owners: ${pct(Q.Q8.male_pct_all_owners)} male — a lean, not proven`,
    "The owner's own card; gender derived (A12, A13)"], H.primary);
  notes(s, `
    [1 minute] Q1 counts persons by their own district, all ${f(C.n)}, including disponents; places three to five differ by four
    clients, so the reading decides their order. Q7: the averages range ${f(Math.min(...ages), 2)} to ${f(Math.max(...ages), 2)},
    but each status has a standard deviation of about 13 years, and B's interval is ±${f(Q.Q7.by_status.B.ci95, 1)} — the
    difference is not meaningful. Q8: 60% of gold-card owners are male, against ${pct(Q.Q8.male_pct_all_owners)} of all owners,
    but the 95% interval (${ci(Q.Q8.male_ci95)}) still includes 50%.`);

  // ------------------------------------------------------------ questions: loans and risk
  s = slide();
  title(s, "Q2 · Q3 · Q4 · Q10 — loans and risk");
  QUESTION(s, "loans");
  const G = { x1: 0.6, x2: 6.75, w: 5.98, y1: 1.4, y2: 4.12, ch: 2.12 };
  bars(s, "Q2 · Loans granted per year (CZK m, number of loans)", r2.map((r) => `${r.year} (${r.loans})`), r2.map((r) => r.total_amount / 1e6),
    { x: G.x1, y: G.y1, w: G.w, h: G.ch, color: H.accent, dataLabelFormatCode: "#,##0.0" });
  const sd2 = Object.values(Q.Q2.sd_by_year);
  text(s, `σ of a loan within a year: ${f(Math.min(...sd2) / 1000, 0)}k–${f(Math.max(...sd2) / 1000, 0)}k · 1993 starts in July`, { x: G.x1, y: G.y1 + G.ch + 0.04, w: G.w, h: 0.32, fontSize: 11.5, color: H.muted, align: "center" });
  text(s, "Q3 · Problematic loans", { x: G.x2, y: G.y1 + 0.05, w: 2.4, h: 0.3, fontSize: 13, color: H.primary });
  text(s, pct(r3.problematic_pct, 2), { x: G.x2, y: G.y1 + 0.5, w: 2.4, h: 0.7, fontSize: 36, bold: true, color: H.block });
  text(s, `${r3.problematic_loans} of ${r3.total_loans} (B ${r3.status_b_finished_unpaid} + D ${r3.status_d_running_in_debt})\n95% CI ${ci(Q.Q3.ci95)}\nby volume ${pct(Q.Q3.share_by_volume, 2)}`,
    { x: G.x2, y: G.y1 + 1.22, w: 2.4, h: 0.9, fontSize: 11.5, color: H.muted });
  pie(s, "", ["healthy (A, C)", "problematic (B, D)"], [r3.total_loans - r3.problematic_loans, r3.problematic_loans], [LIGHT[H.info], H.block],
    { x: G.x2 + 2.45, y: G.y1, w: 3.53, h: G.ch + 0.3, doughnut: true, opts: { showTitle: false, legendPos: "b" } });
  bars(s, "Q4 · Average loan by the owner's card (CZK)", r4.map((r) => `${r.owner_card_type} (${r.loans})`), r4.map((r) => r.average_loan_amount),
    { x: G.x1, y: G.y2, w: G.w, h: G.ch, color: H.accent });
  text(s, `95% margin: junior ±${f(Q.Q4.by_card.junior.ci95 / 1000, 1)}k · gold ±${f(Q.Q4.by_card.gold.ci95 / 1000, 1)}k · no card ±${f(Q.Q4.by_card["no card"].ci95 / 1000, 1)}k`,
    { x: G.x1, y: G.y2 + G.ch + 0.04, w: G.w, h: 0.32, fontSize: 11.5, color: H.muted, align: "center" });
  bars(s, "Q10 · Problematic share by statement frequency", r10.map((r) => `${r.statement_frequency} (${r.loans})`), r10.map((r) => r.problematic_pct / 100),
    { x: G.x2, y: G.y2, w: G.w, h: G.ch, color: H.block, dataLabelFormatCode: "0.00%" });
  text(s, `after transaction CI ${ci(r10[0].ci95)} · vs the rest: Fisher p = ${f(Q.Q10.fisher_p_top_vs_rest, 2)} → not significant`,
    { x: G.x2, y: G.y2 + G.ch + 0.04, w: G.w, h: 0.32, fontSize: 11.5, color: H.muted, align: "center" });
  notes(s, `
    [1 minute] Q2: lending grew to a 1997 peak; 1993 is only half a year. Within any year a loan's size varies by about
    ±${f(Math.min(...sd2) / 1000, 0)}–${f(Math.max(...sd2) / 1000, 0)}k, so the totals are driven by the number of loans as much as their size.
    Q3: 11.14% by count, ${pct(Q.Q3.share_by_volume, 2)} by volume, with a 95% interval of ${ci(Q.Q3.ci95)}. Q4: junior leads, but on
    21 loans with a margin of ±${f(Q.Q4.by_card.junior.ci95)}; classic and no card are the same within their margins.
    Q10: 'after transaction' has the highest share, but on 32 loans; its interval (${ci(r10[0].ci95)}) contains the overall
    11.14%, and a Fisher exact test against the other frequencies gives p = ${f(Q.Q10.fisher_p_top_vs_rest, 2)}. Highest share, yes;
    proven, no.`);

  // ------------------------------------------------------------ questions: accounts and money
  s = slide();
  title(s, "Q5 · Q6 · Q9 — accounts and money");
  QUESTION(s, "money");
  s.addChart(pres.charts.BAR, [{ name: "incoming", labels: r5.map((r) => r.district_name.replace(" - ", " – ")), values: r5.map((r) => r.total_incoming_amount / 1e6) }], Object.assign({}, AX,
    { x: 0.6, y: 1.4, w: 4.75, h: 3.85, barDir: "bar", chartColors: [H.info], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "#,##0.0", catAxisOrientation: "maxMin", barGapWidthPct: 35, catAxisLabelFontSize: 10.5, title: "Q5 · Top 10 districts, incoming 1997 (CZK m)" }));
  bars(s, "Q6 · New accounts per month, 1996", r6.map((r) => r.month_name.slice(0, 3)), r6.map((r) => r.accounts_opened),
    { x: 5.5, y: 1.4, w: 3.85, h: 3.85, color: H.info, catAxisLabelFontSize: 9.5, dataLabelFontSize: 9.5, barGapWidthPct: 30 });
  bars(s, "Q9 · Balances, 31 Dec 1998 (CZK k)", Q.Q9.hist.labels, Q.Q9.hist.values,
    { x: 9.5, y: 1.4, w: 3.23, h: 3.85, color: H.info, catAxisLabelFontSize: 9, dataLabelFontSize: 9.5, barGapWidthPct: 25 });
  card(s, 0.6, 5.4, 4.75, 1.25, [`Praha: ${pct(100 * r5[0].total_incoming_amount / Q.Q5.total_incoming_1997)} of all 1997 incoming`,
    `by size, not intensity: ${f(Q.Q5.per_account["Hl.m. Praha"] / 1000, 1)}k per account vs Usti nad Orlici ${f(Q.Q5.per_account["Usti nad Orlici"] / 1000, 1)}k`,
    "Credits only, by the account's district (A7, A8)"], H.info);
  card(s, 5.5, 5.4, 3.85, 1.25, [`${f(Q.Q6.mean, 1)} a month, σ ${f(Q.Q6.sd, 1)}`, `the July peak (${peak6.accounts_opened}) is +${f(Q.Q6.z_max, 1)}σ: normal variation`,
    "From the calendar: an empty month shows 0 (A9)"], H.info);
  card(s, 9.5, 5.4, 3.23, 1.25, [`${f(r9.average_balance, 2)} (delivered)`, `median ${f(r9.median_balance)} · σ ${f(Q.Q9.dist.sd)}`,
    { text: "later fix: 43,810.47 — not delivered", color: H.post }], H.info);
  notes(s, `
    [1 minute] Q5: Prague takes ${pct(100 * r5[0].total_incoming_amount / Q.Q5.total_incoming_1997)} of all incoming money in 1997,
    four times the next district — but per account it is not the highest; it leads because it has the most accounts (${r5[0].accounts}).
    Q6: ${f(r6.reduce((a, r) => a + r.accounts_opened, 0))} accounts, about ${f(Q.Q6.mean, 0)} a month; even the July peak is within two
    standard deviations, so there is no real seasonality to report. Q9: the average balance is ${f(r9.average_balance, 2)} — the
    delivered figure — and the distribution is right-skewed (median ${f(r9.median_balance)}); ${r9.accounts_overdrawn} accounts are
    overdrawn and ${r9.accounts_carried_forward} carried forward from November. The later balance-chain fix moves the average to 43,810.47.`);
};
