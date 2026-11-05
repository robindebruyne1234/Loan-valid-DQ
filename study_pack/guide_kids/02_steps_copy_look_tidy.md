# <span class="num">3</span>Step 1 — Copy the paperwork exactly 📦 {#k-step-copy}

<p class="lede">Before anyone touches anything, make a perfect copy of what arrived, and prove it is
complete.</p>

The school office handed over **8 boxes** of paperwork: pupils, record books, who-may-use-which-book,
entries, study plans, badges, standing arrangements and the list of topics. All together
**1,079,680 lines**.

- We copied every line **exactly as written** — even the messy ones. Nothing was corrected here.
- Every copied line got a little label: *which box* and *which line number* it came from.
- Every box got a **fingerprint** (a SHA-256 code). If even one letter changes, the fingerprint
  changes, so we can always prove nothing was swapped behind our backs.
- We counted the lines in each box and compared them with the official list that comes with the
  dataset. All 8 matched: 4,500 record books, 5,369 pupils, 5,369 who-may-use lines, 892 badges,
  682 study plans, 77 topics, 6,471 standing arrangements, 1,056,320 entries.

**Why so strict?** Because one day somebody will say *"that number is wrong"*. Then the first
question is: what actually arrived? The copy room answers that, and nobody can argue with it.

**Why not fix things straight away?** If you try to turn messy text into a date while copying, a
broken date either stops the whole copy or quietly disappears — and then you can never find it
again. So the copy room fixes nothing, on purpose.

**The practice room.** The real paperwork is quite tidy, so most checks would never find
anything — and a check that never finds anything proves nothing. So we made a separate practice
copy with 20 mistakes hidden on purpose, to test the checks, and never mixed it with the real
paperwork.

:::say Try saying it
"The copy room is the one room nobody can argue with: here is exactly what arrived, with its
fingerprint and line number."
:::

:::evidence In grown-up words
Bronze `raw`: 8 `.asc` files from the public mirror (D003), every field as text (C01), `_source_file`
/ `_source_row` (C02), SHA-256 per file in `raw.load_audit`, counts match the published reference.
Defects injected only into schema `inject` (D004). Command `make ingest`.
:::

# <span class="num">4</span>Step 2 — Look before you sort 🔍 {#k-step-look}

<p class="lede">Before writing any checks, look at every column and write down what looks strange,
with a count.</p>

We went through every column of every list and wrote down: how many are empty, how many different
values there are, the smallest, the biggest, the most common. Then we made a **list of
suspicions** — before writing a single check. A few of them:

| Suspicion | How many |
|---|---:|
| Entries with no "from which school" information (normal for cash-like entries) | 760,931 |
| One column writes "nothing" in three different ways | 535,314 |
| Entries with no type, because they are bonus points the school adds by itself | 183,114 |
| Record books that went below zero points for a while | 2,999 |
| Pupils whose home topic is different from the topic their book is filed under | 409 |
| Books with several entries on their very last day, so "the last entry" is unclear | 183 |
| Owners who were younger than 15 when their record book was opened | 114 |
| Entries worth exactly zero points | 14 |
| Owners younger than 15 when a study plan started | 6 |
| One topic with a "?" instead of a number | 1 |
| Two entries that look exactly the same | 1 |

Four more suspicions found **nothing** in this copy (for example, a badge belonging to a helper
instead of the owner). We kept those checks anyway, because the real school's paperwork might have
exactly that mistake.

:::weak Oops! — "it doesn't depend on the order"
The suspicion list says one test "does not depend on the order of entries". It does: it needs to
know which entry was the *last* one on a busy day, and it guessed wrong in the same way as the
filing cabinet does (chapter 7). (L-03)
:::

:::evidence In grown-up words
`make profile` writes `dq/results/profile.md` and `candidates.md` (13 candidates present, 4 absent)
from staging. Rules were written from the candidates, not from a checklist.
:::

# <span class="num">5</span>Step 3 — Tidy up, but never erase 🧹 {#k-step-tidy}

<p class="lede">Make the paperwork readable without crossing anything out: the original always stays
right next to the tidy version.</p>

**There were 21 tidying steps, and only one of them takes something away** — a single entry that
was written twice. Everything else changes *how it looks*, never *what was written*:

| Step | What we did | How much |
|---|---|---:|
| C03 | The paperwork writes "nothing" in seven ways ('', ?, NA, N/A, NULL, -, unknown). We turned all of them into one real "empty", and kept the original next to it | 1,380 lines |
| C04 | Numbers became real numbers; if one could not be read, it became "empty" instead of stopping everything | 0 failed |
| C05 | Dates like `950103` became real dates (3 January 1995). Two-digit years mean 19xx — safe, because everything is between 1993 and 1998 | 1,062,394 dates |
| C06 | Badge dates had a clock time stuck on the end (`931107 00:00:00`); we took it off | 892 |
| C07–C08 | **The secret birthday code.** A pupil's number hides their birthday, and for girls the month has 50 added (May = 55). We decoded birthdays and girl/boy from it, and labelled both "worked out, not written down" | 5,369 pupils |
| C09 | Czech words became English: `POPLATEK MESICNE` → *monthly*. The Czech word stays beside the English one | 2,466,175 |
| C10 | **Plus or minus, decided once.** `PRIJEM` means points coming in (+). `VYDAJ` and `VYBER` mean points going out (−). The official description doesn't even mention `VYBER`! | 1,056,320 entries |
| C11 | "Went wrong" (status B or D) is written on every study plan, once | 76 plans |
| C12 | Every change is written in a note on the line it changed | 1,380 lines |

**Why never erase?** If you correct a value and throw the old one away, a week later nobody can
tell your correction from what was really written. And if you quietly throw a line away, every
"how many" and every percentage changes without anyone knowing.

**Why decide plus and minus only once?** Every question about points coming in or going out
depends on reading those Czech words right. If the robot gets `VYBER` wrong, it doesn't crash — it
gives a confident, believable, **wrong** number. So the tidying room decides it once, and the
running totals in the record books confirm that the choice is right.

**Mark, don't hide.** The tidying room never throws anything away. If it threw away the double
entry, the checking room would have nothing to find, and the report would say "all clean".

:::say Try saying it
"Twenty-one tidying steps, and exactly one removes a line — the double entry. Everything else is
converted, with the original one column away. And I can prove nothing got lost: the tidy pile has
exactly the same lines and points as the copy."
:::

:::evidence In grown-up words
Silver `stg` (`sql/10_stg.sql`): C03–C12 of `docs/CLEANING_LEDGER.md`. Decisions D013 (never repair
in place), D014 (placeholders → NULL, original kept), D015 (19xx; failed parse = NULL), D016
(gender and birth date derived from `birth_number`), D017 (one code map; LEASING lesson), D018
(sign resolved once; `VYBER` is a debit, A29), D020 (graded, not gated). `is_problematic` is
computed in both staging and core (L-18).
:::
