# <span class="num">3</span>Step 1 — Acquire and ingest (Bronze) {#step-ingest}

<p class="lede">Land the eight files exactly as they arrived, prove they arrived complete, and
make every later value traceable to a file and a line.</p>

<div class="stepcard">
<div><b>Command</b><code>make ingest</code> · <code>scripts\windows.ps1 ingest</code></div>
<div><b>Code</b><code>src/ingest.py</code>, <code>sql/00_schemas.sql</code></div>
<div><b>Output</b><code>raw.*</code> (8 tables, all text), <code>raw.load_audit</code></div>
</div>

## What it does {#ingest-what}

- Reads the eight original `.asc` files (semicolon-separated, quoted headers; `trans.asc` is
  gzipped in the repository) from `data/raw/`. A bank-supplied copy dropped in
  `data/raw/provided/` would take precedence; none was received (A23).
- Loads **every field as text, unchanged** (C01: 1,079,680 rows) and stamps each row with
  `_source_file` and `_source_row` (C02).
- Writes a load audit per file: row count expected and loaded, and a **SHA-256** of the file,
  so a later reviewer can prove which bytes the numbers came from.
- Checks the counts against the published reference: account 4,500 · client 5,369 · disp
  5,369 · card 892 · loan 682 · order 6,471 · trans 1,056,320 · district 77. All eight match.

## Why it is built this way {#ingest-why}

| Decision | Reason | Cost |
|---|---|---|
| Everything lands as text (C01) | A cast at load time destroys the evidence of the defect it trips over: a bad date would abort the load or vanish. Bronze is the one layer that cleans nothing | Typing is deferred to staging |
| Public mirror `github.com/jlacko/berka-dataset` (D003) | It ships the unmodified `.asc` originals and the original data description; its counts match the published figures exactly | Dependence on a mirror; mitigated by the hash and the count check |
| Public copy is primary; defects are injected into a **separate** schema (D004) | The public copy is clean enough that most rules would never fire, and a rule that has never fired proves nothing. Seeding defects into `inject` proves the rules while the ten answers stay on untouched data | The injector has to be kept in step with the rule families |
| Repository at the git root (D001) | `make all` from the clone root is what a reviewer tries first | — |

:::say Why bronze matters for an AI product
"When somebody disputes a number, the first question is what actually arrived. Bronze
answers that with the file, its hash and the line number. Every later layer can be argued
with; this one cannot."
:::

:::weak Questions to expect
- *Why not type the columns on load?* Because the cast is where defects hide; staging casts
  with NULL-on-failure and keeps the original text.
- *How do you know the mirror is genuine?* Row counts match the published reference exactly
  for all eight files, and the files are the original `.asc` format, not a re-export.
- *Bronze has no dedicated tests* (said in the deck). The load audit and
  `RI_RAW_ROWCOUNT_MATCHES` are the checks; a bronze test module is listed as a next step.
:::

# <span class="num">4</span>Step 2 — Profile before writing rules {#step-profile}

<p class="lede">Measure every column first, write down what looks wrong with a count, and only
then write the rules — so the rules come from the data and not from a checklist.</p>

<div class="stepcard">
<div><b>Command</b><code>make profile</code></div>
<div><b>Code</b><code>sql/10_stg.sql</code>, <code>src/profile_data.py</code></div>
<div><b>Output</b><code>dq/results/profile.md</code>, <code>profile.json</code>, <code>candidates.md</code></div>
</div>

## What it does {#profile-what}

The profiler runs over the staging layer and reports, per column: type, nulls, null rate,
distinct count, min, max and top values, including the lineage and `_raw` audit columns (a
non-zero `_raw` count is itself a defect signal: it only fills when a cast changed or dropped
a value). It then evaluates a list of **candidate defects** and writes them with counts to
`dq/results/candidates.md` — *before* the rules exist. Each candidate is a hypothesis; the
count and its note together decide the severity of the rule that follows.

| Candidates present in the public copy (13) | Count |
|---|---:|
| Partner bank and account missing together on postings | 760,931 |
| Three encodings of "no value" in the same column (`k_symbol`) | 535,314 |
| Structural NULL operation (interest postings) | 183,114 |
| Negative balance after a posting (overdraft) | 2,999 |
| Client district differs from the district of the account they own | 409 |
| Intra-day order undefined (accounts with several postings on their last date) | 183 |
| Running balance off by more than 1 CZK per account | 136 |
| Owner younger than 15 at account opening | 114 |
| Running balance off by more than 100 CZK per account | 55 |
| Amount is zero | 14 |
| Owner younger than 15 at loan start | 6 |
| District placeholder `?` in the 1995 columns (district 69, Jeseník) | 1 |
| Duplicate business key (same account, date, type, amount, balance) | 1 |

Four candidates return zero on this copy and ship anyway, because a bank's own feed may
carry them: a card held by a disponent, an account without transactions, a date outside the
1993–1998 window, an unparsable date or amount.

:::weak The balance candidates are not order independent
`candidates.md` calls the running-balance test "order independent". It is not quite: "the
last reported balance" depends on which of several same-day postings is taken as last, and
the profiler took the highest `trans_id`. That is how the tie-break problem of step 5 leaked
into these counts (Lessons Learned, L-03).
:::

# <span class="num">5</span>Step 3 — Clean and transform (Silver) {#step-clean}

<p class="lede">Make the data usable without overwriting what the bank recorded: type it,
normalise it, decode it, derive what the source leaves implicit — and filter nothing.</p>

<div class="stepcard">
<div><b>Command</b><code>make profile</code> (builds <code>stg</code>)</div>
<div><b>Code</b><code>sql/10_stg.sql</code> (functions <code>stg.norm_text</code>, <code>parse_numeric</code>, <code>parse_date</code>)</div>
<div><b>Evidence</b><code>docs/CLEANING_LEDGER.md</code>, measured from the database</div>
</div>

## The cleaning ledger, steps C03–C12 {#ledger}

Every step is in the generated ledger with what it did, how much, where the original
survives ("reversible") and which rule watches what it could not clean.

| Step | What | Measured | Decision |
|---|---|---:|---|
| C03 | Trim, then map `''`, `?`, `NA`, `N/A`, `NULL`, `-`, `unknown` to NULL | 1,380 rows | D014, A25 |
| C04 | Cast to numeric, returning NULL rather than raising | 0 failed amounts | D013 |
| C05 | Parse `YYMMDD` into a real date; two-digit year read as 19xx | 1,062,394 dates | D015, A17 |
| C06 | Strip the trailing clock time from `card.issued` | 892 | D015 |
| C07 | Decode `birth_number`: women carry month + 50 | 5,369 birth dates | D016, A18 |
| C08 | Derive gender from the same month offset | 5,369 | D016 |
| C09 | Decode every Czech code to an English label from one map | 2,466,175 values, 28 codes | D017, A28 |
| C10 | Resolve the sign once: `PRIJEM` credit +, `VYDAJ` and `VYBER` debit − | 1,056,320 postings | D018, A29 |
| C11 | Materialise "problematic" (status B or D) as a boolean | 76 loans | A4 |
| C12 | Record every changed or dropped value in `_conversion_notes` | 1,380 rows | D013 |

## The decisions that matter most {#clean-decisions}

**Never repair in place (D013).** Options were: repair bad values, drop defective rows, or
transform without overwriting and let a rule layer decide. The third was chosen because a
repaired value is indistinguishable from an observed one a week later, and dropping silently
changes every denominator. Every changed value survives in a `_raw` column and a conversion
note.

**Placeholders become NULL, the original stays beside them (D014).** Left alone, `?` counts
as a value and every completeness number is wrong; replaced without a trace, the cleaning
cannot be checked. The source spells "missing" seven ways; `k_symbol` alone arrives as a
quoted empty string, an unquoted empty field and a single space.

**Two-digit years are 19xx; a failed parse is NULL, not an error (D015).** Safe because the
dataset window is 1993–1998 and `VAL_DATE_OUT_OF_RANGE` fires on anything outside it. NULL on
failure matters more than the century: a cast that throws aborts the load and hides exactly
the defect a quality report needs to see.

**Gender and birth date are derived, and labelled as derived (D016).** Leaving
`birth_number` packed would make every age question re-implement the decoding — and an LLM
reading a context pack will get the month offset wrong. All 5,369 decode on this extract.

**Codes and labels from one map, both kept (D017).** `POPLATEK MESICNE` becomes `monthly`,
but the code stays beside the label, and the build fails if a staged code has no label. The
check earned its place: the order category `LEASING` (341 standing orders) had shipped
unlabelled because the check did not cover that table (A28).

**The sign is resolved once, in staging (D018).** Every "incoming", "net flow" or "largest
withdrawal" question turns on a `CASE` over Czech words. The documentation lists `PRIJEM`
and `VYDAJ`; the data also has `VYBER`, which is a debit. A query that gets this wrong does
not fail — it returns a confident, plausible, wrong number. So `signed_amount` and
`direction` are computed once, and the running balance confirms the convention.

**Graded, not gated (D020).** `sql/10_stg.sql` states it as a contract: *nothing is filtered
out here*. If staging dropped the duplicate posting, the uniqueness rule would have nothing
to count and the report would say the data is clean.

:::say The cleaning in one breath
"Twenty-one cleaning steps, and exactly one of them removes a row — the quarantine of one
duplicate posting. Everything else converts without overwriting: the original value is one
column away and the conversion is noted on the row. And I can prove nothing was lost:
staging equals raw on every row count and every money sum."
:::

:::weak Questions to expect
- *Isn't decoding gender from a birth number a business assumption?* Yes — A18, labelled as
  derived, and it is the only gender source in the data.
- *Why is `VYBER` a debit?* The data description only names `PRIJEM`/`VYDAJ`; the running
  balance decides it: under this convention the chain reconciles within 1 CZK for almost all
  accounts, under any other for almost none (A29).
- *What does `operation IS NULL` mean?* A bank-generated posting: all 183,114 such rows are
  interest credits (`UROK`). It is labelled "not applicable", not imputed (A27).
- *Is `is_problematic` defined in one place?* In meaning, yes; in code it is computed twice,
  in staging and again in core, with the same predicate (L-18).
:::
