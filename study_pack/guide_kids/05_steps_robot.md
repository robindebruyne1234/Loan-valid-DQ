# <span class="num">12</span>Step 10 — The robot: clever, clumsy and a bit risky 🤖 {#k-step-robot}

<p class="lede">Treat the robot like a very fast new helper who has never been inside the archive:
it will guess when it isn't sure, and whatever it asks the archive for really happens.</p>

## What could go wrong {#k-robot-risks}

| Clumsy — wrong without knowing it | Risky — its slips really run |
|---|---|
| Asks for a label that sounds right but isn't there ("gender" where it's called "owner_gender") | Asks the archive to delete or change something |
| Uses the wrong date (when the book was opened instead of when the study plan started) | Hides a second, sneaky request inside the first one |
| Links study plans to every entry, so each plan is counted hundreds of times | Peeks into back rooms where labels mean something else |
| Counts *how many* when the question asks *what share* | Asks for millions of pages, or for something that takes forever |
| Thinks "Q1" means test question 1 instead of January–March | Tries to see more pupils than the person asking may see |
| Makes up its own meaning of "went wrong" | |

## How the robot is protected against — layer by layer {#k-robot-layers}

| Protection | What it does | What it can't do |
|---|---|---|
| **No peeking** | The robot gets only the dictionary and the question: no archive, no files, no tools, one answer | Make the robot right |
| **The dictionary** | Takes away the reasons to guess | Check that the robot used it |
| **The desk clerk** | Reads every slip properly (like reading grammar, not looking for bad words): one "please show me", only the reading shelf, at most 10,000 pages | **Check whether the slip asks the right question** |
| **The reading rules** | Read-only visit, stops after 60 seconds, the person's own key card and code | — |
| **The drawer locks** | Decide which files exist for this person, whatever the slip says | — |
| **The archive itself** | A label that doesn't exist is an error — never an answer | Catch a slip that is valid but wrong |
| **Marking afterwards** | Compares the robot's numbers with the answer key | Protect someone asking right now |

:::danger Never say
"The desk clerk let it through, so the answer is right." The clerk only checks that a slip is
**safe**. It does not check that it asks the **right question**.
:::

## The day the robot asked for a drawer that doesn't exist {#k-gender}

Someone asked: *"Find male or female loans in Q1 1995."* (In school words: *how many study plans in
January–March 1995 belong to boys, and how many to girls?*) The robot wrote a slip asking the
**owner** folder for a label called **"gender"**.

- The desk clerk said: ✅ *safe* — one "please show me" on the reading shelf.
- The archive said: ❌ *"there is no label called gender here"*.

Boy/girl lives in the **pupil** folder. In the owner and study-plan folders the label is called
**owner_gender**. The dictionary had said the sum could use "any folder with a gender label" — that
was the real cause. Nothing bad happened (no wrong number, just an error). But a slip with a label
that **does** exist, asking the wrong thing, would have given a believable wrong answer.

:::post Later we fixed it
After the hand-in, the robot must also write down **what it intends**: which official sum, which
dates, grouped by what. Before the archive is even opened, the clerk checks the slip against that
promise: every label must exist, the dates must cover exactly January–March, no link may count
plans many times. Afterwards the school works out the same sum itself, and only shows the answer if
both agree. The gender question is now refused with "use owner_gender", and the right answer is
28 study plans: 18 boys' and 10 girls'. (D029)
:::

## The little robot shows what "clumsy" looks like {#k-little-robot}

A small free robot on the laptop, with the same dictionary and the same doors, got 6 right, 2
half right and 2 wrong. Every mistake was a **safe** slip that the clerk correctly let through:

- **Report frequency (Q10):** it counted *how many* plans went wrong per report frequency and picked
  *monthly* — but the question asks for the **share**. The right answer is *after every entry*,
  18.75%. That is exactly the trap the dictionary warns about.
- **New record books per month (Q6):** it linked each book to *every day* of its month, so January
  showed 279 new books instead of 106.
- **Age at study-plan start (Q7):** it grouped by age instead of working out the average age.

:::say Try saying it
"The big robot with a good dictionary got all ten right. The little robot made exactly the mistakes
the dictionary warns about. Every one of those slips was safe — so safety alone isn't enough; wrong
answers have to be caught too."
:::

:::evidence In grown-up words
LLM as a sandboxed completion (D005, D011): no tools, no MCP, cwd outside the repo, `num_turns: 1`.
`src/sql_guard.py` (sqlglot; one read-only SELECT on `ai`, no out-of-schema functions, LIMIT ≤
10,000), `execute_guarded` (read-only, 60 s, cap + 1 rows), RLS. The observed failure: `T2.gender`
on `ai.account_owner` → `column t2.gender does not exist`. Intent checker was a prototype at
delivery (L-07); integrated afterwards (D029). Ollama qwen2.5-coder:3b: 6 / 2 / 2.
:::

# <span class="num">13</span>Step 11 — Marking the robot's homework 📝 {#k-step-marking}

<p class="lede">Compare the robot's numbers with the answer key — the numbers, not the handwriting.</p>

**How each question is asked.** The question and the dictionary go to the robot; it sends back a
slip and a short explanation; the clerk checks it; it runs on the head teacher's card (her list has
every pupil, so the answers can be compared with the answer key); everything is written in the
logbook. If the slip is refused or can't be read, the robot gets **one more try**, with the reason.
**Nobody ever fixes the robot's slip by hand.**

**How it is marked.** Two right answers can use different names for their columns ("pupils" or
"pupil_count"), so we don't compare the slips or the names. We compare the **numbers**: every number
in the answer key must appear in the robot's answer, next to the right label, within a tiny rounding
difference (0.011). For the three "top" questions, the order must match too.

:::weak Oops! — getting the marking itself right
The first marking rules allowed a "close enough" of 0.01% — which would have accepted the biggest
topic being wrong by 11,513 points. Now only rounding is allowed. And once, the marker said the
robot was wrong about Q6 just because it wrote "1996-01" where the key said "1". Now any normal way
of writing a month counts — and we wrote down that we changed this. (D011)
:::

## The results {#k-results}

| Robot | When | Result |
|---|---|---|
| **Big robot** (Claude Sonnet 5.5) — the official run | 25 October 2026, with the older dictionary | **10 out of 10** right, all on the first try, about 2 minutes, about 40 cents |
| **Little robot** (qwen2.5-coder:3b on the laptop) | 27 October 2026, own folder | 6 right, 2 half right, 2 wrong |

:::weak Oops! — 10 out of 10 sounds better than it is
The big robot used the dictionary from **before** it was improved, and wasn't asked again with the
new one (there was no big robot on the laptop). The dictionary points at which folder answers which
question. There were no surprise questions, and each question was asked only once. Fair summary:
*the dictionary is good enough for a strong robot on these ten questions — it doesn't yet prove it
works on new ones.* (L-08)
:::

:::post Later we fixed it
After the hand-in, the big robot was asked again with the new dictionary and the new intent check:
10 out of 10. Four brand-new questions were added (boys and girls, and quarters of the year): 4 out
of 4.
:::

:::evidence In grown-up words
`src/run_questions.py` (one retry, never hand-corrected, run as `cro_global`), `src/evaluate.py`
(value-based, absolute tolerance 0.011, order checked for Q5, Q6, Q10), `dq/results/llm_results.json`
(2026-10-25, `a7da25a`, 29,500-character pack), local run in `dq/results/local/`.
:::

# <span class="num">14</span>Step 12 — Showing it to the parents 👨‍👩‍👧 {#k-step-show}

- **The console tour:** seven short scenes — key card only → nothing; key card + code → your own
  pupils; switching between people; a pupil and her tutor asking the same question and getting
  different, correct answers.
- **The website tour:** seven steps in a browser — copy, tidy, check, cabinet, access, login, ask the
  robot. You can only ask after a real login. It even works offline with the little robot.
- **One pupil, start to finish:** a story that follows one pupil from a line of raw paperwork, through
  tidying, into the cabinet and through the locks.

**What we handed in**

| Item | What's in it |
|---|---|
| The workbook (11 tabs) | Kinds of mistakes, the cabinet, the questions and answers, the checks, the tidying steps, guesses, decisions, who-sees-what, the logbook |
| The decision paper (2 pages) | The seven biggest decisions: the options, the choice, why, the cost, and what breaks if the school becomes 100,000 times bigger |
| The zip file | The dictionary, all the instructions, the tests and the results |
| The hand-in check (`DELIVERY_AUDIT.md`) | Every claim → where its proof is → which papers repeat it |

Every step writes a line in the **logbook** with the exact version it ran on. A step that never ran
shows *NOT EXECUTED*.

:::say Try saying it
"Every number in the workbook came from a step that ran and is in the logbook. A step that didn't
run says NOT EXECUTED — it's never filled in."
:::

:::evidence In grown-up words
`make demo-login` (console), `make web-open` (web walkthrough, `/api/ask` requires a completed
login), `make demo` (worked example). Deliverables: workbook (11 tabs), DDR (2 pages), ZIP (183
members), `docs/DELIVERY_AUDIT.md`, `run_log.jsonl` → `STATUS_REPORT.md`.
:::
