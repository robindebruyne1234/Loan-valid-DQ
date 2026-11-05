# <span class="num">8</span>Step 6 — The answer key, written before the test ✅ {#k-step-key}

<p class="lede">Before the robot is asked anything, write down the right answers yourself — and keep
them where the robot can never see them.</p>

- For each of the 10 test questions we wrote the right request slip ourselves, against the filing
  cabinet, and stored the answers. That is the **answer key**.
- Above every answer we wrote **how we understood the question** — for example "region means the
  wing of the pupil's *own* home topic, not the topic their book is filed under". Where a question
  could be understood another way, we wrote down the other way too, and how much it changes.
- The robot **never** sees the answer key, the slips, or how it will be marked. A test checks that
  no answer number appears anywhere in the dictionary.
- On hand-in day we ran the answer key again: all ten identical. And every answer was worked out
  **a second time** from the original copied paperwork, with different slips, and matched.

:::weak Oops! — who wrote the answer key?
It was written in the AI-assisted building session — not by the robot being tested, and not
literally by hand. That is fine for the test (the robot never saw it), but say it exactly. The
strongest argument is the second, independent calculation from the original paperwork. (L-12)
:::

:::evidence In grown-up words
`sql/60_reference_queries.sql` → `dq/results/reference_results.json`, interpretations A1–A16;
`tests/test_semantic.py::test_context_pack_contains_no_answers`; independent re-derivation from
`raw` text tables.
:::

# <span class="num">9</span>Step 7 — The school dictionary 📖 {#k-step-dictionary}

<p class="lede">One book holds every word the robot is allowed to use, and the school refuses the
book if it disagrees with the real filing cabinet.</p>

## What is in the dictionary {#k-dict-content}

- **11 folders** on the reading shelf, with what one card means and every label explained.
- **12 official sums** ("certified metrics"), like *share of study plans that went wrong*, each with
  the date it uses.
- **19 links** between folders, each saying whether one card on the left can match many on the right.
- **10 words**, each with what it **is** and what it is **not**: *a helper is not the owner*;
  *points coming in is not "points in minus points out"*; *"Q1" in a question means January–March,
  not test question 1*.
- **7 warnings** with how many lines they affect (the orange stickers), which the robot must
  mention in its answer.
- **12 rules for the robot's request slips**, in short:

| # | Rule |
|---:|---|
| 1 | Only ask for folders on the reading shelf |
| 2 | One "please show me" request per slip |
| 3 | Never ask to change, add or delete anything |
| 4 | Never try to see more than you are allowed, and don't mention the locks |
| 5 | Use the official sums exactly as written; never invent your own "went wrong" |
| 6 | "Per month / per year" → use the calendar, so a month with nothing shows 0 |
| 7 | Use the ready-made folders that already join things together |
| 8 | Give the counts next to a percentage, and mention the warnings |
| 9 | Round percentages to 2 decimals; don't round point totals |
| 10 | If the question can't be answered, **say what is missing** instead of guessing a label |
| 11 | Filter dates on the right date column, from the first day included to the first day *not* included |
| 12 | Count at the right drawer; never add up after linking to a drawer with many cards per card |

## The school checks the dictionary every time {#k-dict-check}

Every time we rebuild, the school compares the dictionary with the real cabinet. The build
**stops** if: a label in the dictionary doesn't exist, a real label is missing from the dictionary,
"one card means one thing" is not true, a link has a different shape than promised, or an official
sum uses a label that doesn't exist.

**Why so strict?** A dictionary that is out of date gives the robot confident wrong information —
and the robot has no way to check.

:::weak Oops! — the dictionary told the robot where to look
The dictionary says which folder answers which test question ("Relevant to: Q1"). It doesn't give
the answers, but it does point at them, so the test is easier than real life. A fair test needs
questions the robot has never seen. (L-08)
:::

:::weak Oops! — one sum said "any folder with a gender label"
The *share of boys and girls* sum didn't say which folder. Later the robot looked for a label called
"gender" on the owner folder, where it is called "owner_gender" — see chapter 12. (L-07)
:::

:::evidence In grown-up words
`semantic/semantic_layer.yaml` (11 entities, 105 columns, 19 joins with measured cardinality, 12
metrics, 7 caveats, 12 query rules QR1–QR12, 10 glossary terms) → `semantic/context_pack.md`
(33,662 characters at delivery). Validated by `src/semantic_context.py` on every `make semantic`.
:::

# <span class="num">10</span>Step 8 — A lock on every drawer 🔐 {#k-step-locks}

<p class="lede">Every staff member and every pupil sees only the files they are allowed to see — and
the lock is on the drawer itself, so the robot can't open it, whatever it writes.</p>

## Where the lock is {#k-where-lock}

There are three places you could put a rule like "Ms North may only see her own pupils":

1. **In the instructions to the robot** ("please only show Ms North's pupils"). That is a *request*,
   not a lock — you are asking the helper to limit itself.
2. **At the archive desk**, rewriting every slip. Better, but one cleverly shaped slip gets past.
3. **On the drawers themselves.** The drawer only opens for files the person may see. ✅ This is
   what we built.

The lock asks: *who is holding the key card?* — not *who does the slip say it is?*. The robot only
writes slips; it never has a key card. **The lock is not written on the slip, so there is nothing on
the slip to remove.** Even the head teacher sees everyone only because her list contains every
pupil — not because she has a master key.

## Who sees how many pupils {#k-who-sees}

<div class="people">
<div><span class="e">👩‍🏫</span><b>Head teacher</b>list with every pupil<span class="n">5,369</span></div>
<div><span class="e">🧑‍🏫</span><b>Ms North</b>tutor, north group<span class="n">1,481</span></div>
<div><span class="e">🧑‍🏫</span><b>Mr South</b>tutor, south group + 1 substitute pupil<span class="n">1,387</span></div>
<div><span class="e">🆕</span><b>New teacher</b>no group yet<span class="n">0</span></div>
<div><span class="e">🧒</span><b>Pupil 3764</b>a helper on pupil 3763's book<span class="n">1</span></div>
</div>

A brand-new teacher with no group sees **nobody**, not everybody. A badly built lock usually does
the opposite.

## Four ways to be allowed {#k-four-ways}

| Way | Example | What it allows |
|---|---|---|
| **It's yours** | Pupil 3763 and her own record book | See and use her own record and her own books |
| **You may sign in it** | Big brother 3764 may sign in his sister's book | That **one book** — not his sister's personal file, not her other books |
| **It's in your group** | Ms North and the north group | **See** only — a tutor looks after pupils but doesn't spend their points |
| **A substitute** (stored with a reason and end date) | Mr South covers one of Ms North's pupils while she's away — like the counsellor helping one pupil | Only that pupil, only until the end date (about 14 days) |

**A new teacher joins without rebuilding anything:** add her to the staff list, give her a group,
make her key card, set up her code. Leaving is one change: switch her off.

## Tested by trying to break in {#k-break-in}

We logged in as people who should **not** get in and tried nine tricks: pretending to be someone
else, writing a "who I am" note, going round the reading shelf straight to the cabinet, giving
yourself access, switching a lock off, writing into a drawer, combining folders to see more. All
nine failed. Two pupils of the same tutor tried 13 ways to see each other — all failed.

:::weak Oops! — one shelf folder didn't honour the locks
Once, three folders between the reading shelf and the cabinet were missing one setting
(`security_invoker`). The study-plans folder showed all 682 plans to a teacher allowed to see none,
while the drawer underneath correctly showed 0. We only found it because we logged in as that
teacher and counted. (D010)
:::

:::weak Oops! — the big brother sees a bit more than promised
Our papers say a helper sees the book "and nothing else of hers". But brother 3764 can also see his
sister's **badge** (junior, its date, her pupil number) and her "owner" line, because those two
drawers check *the book* instead of *the person*. (L-05)
:::

:::weak Oops! — "hidden" turned into "no badge"
When the brother looks at the study plan on that book, the owner's details are hidden — correct.
But the folder then writes **"no badge"** instead of "hidden", and leaves the report frequency
empty. The truth is a junior badge and monthly reports. A hidden value became a wrong value. (L-06)
:::

:::evidence In grown-up words
Seven RLS policies on the seven client-bearing core tables; every view between consumer and policy
`security_invoker` (D010); identity = `session_user` (D009); no `BYPASSRLS`; grants from ownership,
disposition (D023, D024), portfolio, delegation (stored, D027) in `sec.v_access_grant`; measured
counts per role; 9 bypass tests in `tests/test_rls.py`. Weak spots L-05, L-06, L-11 (the "who can
reach this pupil" report has a gap for pupils without a login).
:::

# <span class="num">11</span>Step 9 — Key card and secret code 🪪 {#k-step-code}

<p class="lede">Your key card (the password) alone opens nothing. You also need a code that changes
every 30 seconds — and the archive itself checks it.</p>

1. Show your **key card** (the password of your own login).
2. Type the **code** from your code app. It changes every 30 seconds and works only **once**.
3. The archive checks the code **itself**. The check only asks for the code — it already knows who
   is holding the key card, so nobody can type a code "for someone else".
4. If it's right, you get a **visit pass** for 30 minutes on that connection.
5. Every drawer lock also asks: *does this person have a visit pass?* No pass → **0 files**, even
   with the right key card.
6. Five wrong codes in a row lock your code for 15 minutes.

**Why in the archive and not at the front door?** If only the front door checked codes, someone who
found another way into the building would skip it. The archive checks it itself, so you can prove
it: right key card, no code, nothing to see.

:::weak Oops! — the "undo" trick
The archive counts wrong codes inside your own visit. Our normal door saves every attempt, so five
wrong codes really do lock you out. But someone using the archive's back door with a stolen key
card could press "undo" after each wrong guess, and the counter never goes up. We found this while
writing the test, and wrote it down. The drawer locks are not affected: no code, no files. (L-09)
:::

:::weak Smaller things to know
The visit pass is tied to a connection number that can be reused (L-10); the code secrets are
stored so they can be read back (A44); and in the demo, the codes are shown on screen and everyone
shares a demo password — fine for a demo, never for real (A46).
:::

:::evidence In grown-up words
TOTP (RFC 6238) in SQL, `sec.verify_second_factor(code)` uses `session_user`, single-use codes, 5
committed failures lock for 15 minutes, session bound to `(db_role, pg_backend_pid)` for 30 minutes,
`sec.has_verified_session()` ANDed into the entitlement resolution (D026). Identifiers D025.
Rollback gap = strict xfail in `tests/test_auth.py`.
:::
