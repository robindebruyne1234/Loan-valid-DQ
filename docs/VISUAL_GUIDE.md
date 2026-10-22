# Visual guide

Six figures. Each one is here because it shows a mechanism that would otherwise
have to be assembled from prose; where a sentence says it faster, there is a
sentence instead.

Sources are in `docs/diagrams/`. The four flow and schema figures are Mermaid
(`.mmd`), which GitHub renders inline, and the two decision comparisons are
hand-authored SVG, because their point is to draw *the difference* between
options rather than to lay out a graph. Every figure is committed as both
`.svg` (for reading and for documents) and `.png` at 2x (for slides), so
nothing needs to be rendered to look at them. `make diagrams` regenerates them.

Figures are numbered to match where they belong in a walkthrough.

---

## 1. The build-time pipeline

![Pipeline from source files to the governed surface](diagrams/01_pipeline.svg)

**What it shows:** what happens to a row between a source file and the surface
an AI consumer may query, and where the data quality control plane sits in
that path. The two dashed branches are the parts people usually ask about: the
`inject` schema is a corrupted copy used only to prove the rules fire and never
reaches `core`, and the quarantine and flag tables are what the `block` and
`warn` severities mechanically *do*.

**Read it alongside:** `sql/00_schemas.sql` (the layer contract, written in the
file), `DECISIONS.md` D008.

---

## 2. The query path, and where the entitlement filter lives

![Query path from question to entitlement-filtered rows](diagrams/02_query_path.svg)

**What it shows:** the answer to "why can an LLM-generated query not bypass the
filter". The model holds no connection -- it emits **text**. The guard checks
the shape of that text. The connection is authenticated as a particular role,
and the row level security policy is evaluated inside the plan, in the engine,
against entitlement data the model cannot see or reach. The predicate is never
in the query, so rewriting the query cannot remove it.

The green boxes are the ones that actually enforce anything. The amber guard is
a second line, not the control.

**Read it alongside:** `sql/50_sec_rls.sql`, `tests/test_rls.py` (nine bypass
attempts, all refused), `DECISIONS.md` D009 and D010.

---

## 3. What a severity actually does

![Block, warn and info each have a mechanical consequence](diagrams/03_severity.svg)

**What it shows:** that `block`, `warn` and `info` are not labels on a report --
each one has a different mechanical consequence, and the consequence is the
reason the severity has to be justified. A `block` removes the row from the
product and the removal is counted and reversible. A `warn` keeps the row and
puts a flag on it that travels all the way into the answer the LLM gives. An
`info` changes no reported number.

This is the figure to have open when defending a severity call. The clearest
case in this dataset: 14 transactions have an amount of exactly zero, and
`block` would quarantine 14 valid interest postings and break 14 accounts'
balance chains -- following the top lane -- to fix nothing. So it is `info`.

**Read it alongside:** `dq/dq_rules.yaml`, `deliverables/defects.csv`.

---

## 4. The core star schema

![Core star schema with grains, keys and join paths](diagrams/04_star_schema.svg)

**What it shows:** the model an AI consumer queries through, with primary and
foreign keys and the relationship labels. The shape worth noticing is
`bridge_disposition`: clients do not join to accounts directly, they join
through a disposition that says in what capacity. That is what makes "the
account owner" a well-defined phrase in Q4, Q7, Q8 and Q9, and it is why a card
-- which hangs off the disposition -- can belong to someone who is not the owner.

Grain and key for every object, with the reason for each shape, are in
`deliverables/model_explanation.md`.

---

## 5. Decision: where the entitlement filter sits

![Three places the filter could sit, and what defeats each](diagrams/05_where_the_filter_sits.svg)

**What it shows:** the same request path three times, with the filter in a
different place, and what defeats it in each case. The lozenge labelled "filter
lives here" moves; everything else is held constant, so the choice is the only
thing changing.

The argument in one line: in the prompt, the thing being filtered is the thing
asked to apply the filter; in the gateway, one unanticipated query shape
defeats it and the blast radius is every user; in the engine, there is nothing
the model can emit, because the predicate is not in the query.

**Read it alongside:** `DECISIONS.md` D009, the Design Decision Record
section 5, and the Entitlements tab of the workbook (which shows what each role
actually sees).

---

## 6. Decision: star schema versus one big table

![Star schema and one big table compared on the same two questions](diagrams/06_model_shape.svg)

**What it shows:** the same two tasks -- counting clients, and applying the
entitlement filter -- priced against both shapes. One big table is the shape many
text-to-SQL tools prefer because it removes joins, and the figure shows what it
costs instead: every grain other than the posting becomes a `count(DISTINCT
...)` that the query author has to remember, and the entitlement predicate is
evaluated 1,056,319 times rather than 5,369.

The bottom line is the generalisation: the ten questions have four grains, and
one table can only have one of them.

**Read it alongside:** `deliverables/model_explanation.md` ("Alternatives
considered"), the Design Decision Record section 2.

---

## Regenerating

```
make diagrams
```

Renders every `.mmd` to SVG and PNG with mermaid-cli, and rasterises the
hand-authored SVGs to PNG with the bundled Chromium. It needs `npx` and a
Chromium binary and is **not** part of `make all`: the diagrams are committed,
and no part of the data pipeline depends on them.
