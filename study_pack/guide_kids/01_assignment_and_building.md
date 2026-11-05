# <span class="num">1</span>The assignment, and the school rules 📝 {#k-brief}

<p class="lede">What the school asked for, what we built for each part, and the house rules we
followed the whole way.</p>

## What the school asked for {#k-asked}

The pupils and teachers want to ask a robot questions about the archive in normal words. A robot
can only answer well if the paperwork is tidy, the words mean one thing, and every person sees
only the files they are allowed to see. So the school gave us three jobs and ten test questions.

| Job | In school words | What we made |
|---|---|---|
| **1. Check the paperwork** | Find the mistakes in the record books, give each kind of mistake a colour (red, orange, green) and say *why* that colour | 124 checks, every one with its colour and its reason; 14 kinds of mistakes found |
| **2. Make it robot-ready** | Build a tidy filing cabinet, write a dictionary so the robot understands the words, and let the robot answer the 10 test questions | A filing cabinet, a dictionary the school checks every time, and the robot's answers next to the answer key |
| **3. The right files for the right people** | Explain how each teacher only sees their own pupils, why the robot cannot sneak past, and how a new teacher joins without rebuilding anything | Not just explained — built: a lock on every drawer, a key card plus a code, and tests that try to break in |

The school also said: **"This should take one or two days. If you spend most of your time
building the building instead of sorting the paperwork, you misunderstood the job."**

:::weak Oops! — we built more than a fence
We also built a key-card-and-code door, a website tour, instructions for putting it online, a
55-slide presentation and pretend robot assistants. Be ready for the question. The honest answer:
the three jobs were done first; the extras were asked for and each one shows a safety idea; the
building itself stayed simple (one archive, plain instructions). What we would drop first: the
online instructions, the pretend assistants, then the website tour. (L-19)
:::

## Nine house rules {#k-rules}

1. **Show, don't tell.** Every number comes from a step we actually ran, and the logbook says
   which. If a step did not run, it says *NOT EXECUTED* — we never fill in a guess.
2. **Photocopy first, never correct the original.** When something is fixed, the old version
   stays right next to it.
3. **Mark mistakes, don't hide them.** The tidying room throws nothing away; the checking room
   decides later.
4. **A colour must *do* something.** Red goes in the "do not use" tray, orange gets a warning
   sticker that travels with the answer, green is just noted.
5. **One word, one meaning, one place.** "Struggling study plan", "owner", "points in" are
   decided once.
6. **Don't trust a green tick.** We double-check the cabinet after every build, hide 20 fake
   mistakes on purpose to see if the checks catch them, and test the locks by logging in as
   the person who should *not* get in.
7. **The robot is a guest.** It reads the dictionary and the question, nothing else; whatever it
   writes is checked before it reaches the archive.
8. **Keep the answer key away from the robot.** And keep each robot's homework in its own folder.
9. **Write every big decision down**, with the other options and what it costs.

## Who helped {#k-helpers}

| Helper | What they did |
|---|---|
| An AI building assistant (Claude Code), directed by you | Wrote most of the work — every step run and checked against the archive |
| **The big robot** (Claude Sonnet 5.5) — the one being tested | Wrote the request slips for the 10 questions, seeing only the dictionary. No tools, no archive, no peeking |
| **The little robot** (a small free model on the laptop) | Answered the same questions through the same doors, in its own folder |

:::weak Oops! — "written by hand"
Some papers say the answer key was "hand written" or "worked out by a person". The exact truth is:
it was written in the same AI-assisted building session, **not by the robot being tested**, and
every answer was later worked out a second time from the original paperwork. Say it that way.
(L-12)
:::

## Why this archive building {#k-stack}

We chose an archive (PostgreSQL) that can put **a lock on each drawer** (row level security).
A simpler archive (DuckDB) has no drawer locks, so job 3 would have been just a story instead of
something we could prove by trying to break in.

:::evidence In grown-up words
Tasks 1–3 of the brief; deliverables: workbook tabs, ZIP, two-page DDR. Expected 1–2 days. Working
rules = chapter 1 of the study guide (D013, D020, D004, D010, D011). Stack: PostgreSQL 16/18
(D002), SQL files + Python + Makefile, sqlglot guard, Claude CLI as a sandboxed completion (D005),
natural keys (D007).
:::

# <span class="num">2</span>The archive building, room by room 🏛️ {#k-building}

<p class="lede">The archive has six rooms. Paperwork walks through them in order, and each room has
one job and a promise to the next.</p>

<div class="rooms">
<div class="r-raw"><b>1 · Copy room</b>The 8 boxes of paperwork, copied exactly — not one letter changed — with a fingerprint for each box.<i>raw (bronze)</i></div>
<div class="r-stg"><b>2 · Tidying room</b>Dates made readable, codes turned into words, + and − decided. Nothing thrown away, originals kept beside.<i>stg (silver)</i></div>
<div class="r-dq"><b>3 · Checking room</b>124 checks with red, orange or green stickers, the "do not use" tray and the logbook.<i>dq</i></div>
<div class="r-core"><b>4 · Filing cabinet</b>Neat drawers: pupils, record books, study plans, entries. One meaning per word. Checked after every build.<i>core (gold)</i></div>
<div class="r-ai"><b>5 · Reading shelf</b>The only shelf anyone may read from — 11 labelled folders, each one honouring the drawer locks.<i>ai</i></div>
<div class="r-sec"><b>6 · Key office</b>Who is who, which group belongs to which tutor, substitutes, key cards and codes. The drawer locks ask this office.<i>sec</i></div>
</div>

There is also a seventh, a **practice room** (`inject`): a copy of the tidying room with 20 fake
mistakes hidden on purpose, used only to test the checks. Nothing from it may ever reach the
filing cabinet.

## One question, all the way through {#k-one-question}

Ms North, a tutor, asks the robot: *"What percentage of study plans went wrong?"*

<div class="chain">
<div><b>1 · Dictionary</b>The robot gets the question and the school dictionary — nothing else.</div>
<div><b>2 · Request slip</b>The dictionary says "went wrong = not passed or falling behind", already marked on every plan. The robot writes a slip.</div>
<div><b>3 · Desk clerk</b>Checks the slip: one "please show me" request, only from the reading shelf, at most 10,000 pages.</div>
<div><b>4 · Key card + code</b>The slip is carried in on Ms North's own key card and code.</div>
<div><b>5 · Drawer locks</b>The drawers only open for her own pupils' files. The robot never sees the lock.</div>
<div><b>6 · Answer</b>Ms North gets her group's answer. The head teacher, who has every pupil, gets 76 of 682 = 11.14%.</div>
</div>

:::say Try saying it
"Three things protect the archive and they do different jobs. The dictionary stops the robot from
having to guess. The desk clerk stops dangerous request slips. And the drawer locks decide which
files exist for *you* — that one would hold even if the other two failed."
:::

## Three promises between the rooms {#k-promises}

| Promise | Kept? |
|---|---|
| The tidying room has exactly the same pages and points as the copy room | Yes — 11 checks, all equal |
| The filing cabinet = the tidying room minus the "do not use" tray | Yes — 9 checks, all equal |
| The dictionary matches the real cabinet (every folder and label exists) | Yes — 0 problems |

:::evidence In grown-up words
Schemas `raw` → `stg` → `dq` → `core` → `ai`, with `sec` beside `core`; `inject` for seeded defects.
The path: prompt + context pack → model JSON → `sql_guard` (one read-only SELECT on `ai`, LIMIT ≤
10,000) → two-factor login → `BEGIN READ ONLY`, 60 s timeout → RLS on `core.fact_loan` via the
`security_invoker` view `ai.loan`. Reconciliation: raw = stg (11 checks), core = stg − quarantine
(9 checks).
:::
