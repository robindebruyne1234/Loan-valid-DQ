# <span class="num">16</span>A school 100,000 times bigger 🏙️ {#k-bigger}

<p class="lede">Imagine 100,000 Berka Schools in one archive: about 100 billion entries. What would
stop working, and what would we do instead?</p>

| What gets too slow | Why | What we would do |
|---|---|---|
| **Rebuilding the cabinet** | Today we rebuild every drawer from scratch each time — hours of copying files that did not change | Split drawers by month and only redo the months that changed |
| **The 124 checks** | Each check reads everything, every time | Check only the new paperwork; sample the green checks; keep the red checks exact |
| **Month-end totals** | 32 billion month-end cards rebuilt from scratch | Next month's total = last month's total + this month's entries |
| **Answering quickly** | A robot's slip that reads everything takes forever; many people at once overload one archive | Ready-made summaries for the official sums, faster drawer labels for dates, and a front desk that shares connections safely |
| **Checking the drawer locks** | A tutor with millions of books makes every lock check heavy | Keep a ready list of "who may open which book", updated when something changes |
| **Marking the robot** | Ten questions are not a real exam | A big set of surprise questions, saved samples, and someone watching for strange slips |

**What stays the same:** the lock stays on the drawers, a new teacher still joins by being added to
a list, and the dictionary stays about the same size. One archive building would be too small; we
would move the same rooms, checks and locks into a bigger kind of archive.

:::evidence In grown-up words
DDR "What breaks at 100,000×": incremental month-partitioned facts, partition-scoped rules, a
maintained month-end snapshot, marts and a `SET ROLE` gateway, a materialised `(role, account_id)`
set, a hold-out evaluation. Engine: PostgreSQL with Citus, or a columnar MPP engine, or warehouse
row access policies.
:::

# <span class="num">17</span>Questions people might ask 🙋 {#k-qa}

<p class="lede">Short answers in school words. The grown-up answers are in chapter 17 of the original
study guide — same numbers.</p>

<div class="qa"><div class="q"><span class="id">1</span>Why did you build so much? It was a one-or-two-day job.</div><div class="a">The three jobs were finished first. The extras were asked for, and each shows a safety idea. The building stayed simple. If I had to drop things: the online instructions, the pretend assistants, then the website tour.</div></div>

<div class="qa"><div class="q"><span class="id">2</span>Why that archive?</div><div class="a">Because it can lock each drawer, so I could prove the robot can't sneak past by actually trying to.</div></div>

<div class="qa"><div class="q"><span class="id">3</span>Why never correct the original paperwork?</div><div class="a">Because a week later nobody could tell my correction from what was really written. The original stays next to the tidy version.</div></div>

<div class="qa"><div class="q"><span class="id">4</span>Give one red, one orange and one green.</div><div class="a">Red: the same entry written twice — into the tray. Orange: owners younger than 15 when a plan started — kept, with a sticker. Green: zero-point bonus entries — real, so just noted.</div></div>

<div class="qa"><div class="q"><span class="id">5</span>Your only red line is worth zero points. What did it protect?</div><div class="a">Honestly, nothing in points. The check can only ever catch twins worth zero. I'd add an orange check for repeated identical entries and ask the school office about the 1,081 repeated bonus entries.</div></div>

<div class="qa"><div class="q"><span class="id">6</span>How do you know nothing got lost?</div><div class="a">Count everything and add up all the points in every room: the tidy pile equals the copy, and the cabinet equals the tidy pile minus the tray.</div></div>

<div class="qa"><div class="q"><span class="id">7</span>Where is the lock, and why can't the robot open it?</div><div class="a">On the drawers. It asks who holds the key card. The robot only writes slips, and the lock isn't on the slip — there's nothing to remove.</div></div>

<div class="qa"><div class="q"><span class="id">8</span>How does a new teacher start?</div><div class="a">Add her to the staff list, give her a group, make her key card and code. No rebuilding. Leaving is one switch.</div></div>

<div class="qa"><div class="q"><span class="id">9</span>Can a helper see anything of the owner?</div><div class="a">Not her personal file. But yes, her badge and her owner line — I promised too much there. The fix is a lock that checks the person, not the book.</div></div>

<div class="qa"><div class="q"><span class="id">10</span>If the desk clerk lets a slip through, is the answer right?</div><div class="a">No. The clerk only checks that it's safe. The gender question proved it: allowed by the clerk, refused by the archive.</div></div>

<div class="qa"><div class="q"><span class="id">11</span>Is 10 out of 10 really that good?</div><div class="a">It's good, but narrower than it sounds: old dictionary, the dictionary points at the answers, no surprise questions, one try each. It shows the dictionary works for these ten.</div></div>

<div class="qa"><div class="q"><span class="id">12</span>How do you know the robot didn't just read the answers?</div><div class="a">It never sees the archive or the answer key, and a test checks no answer number is in the dictionary.</div></div>

<div class="qa"><div class="q"><span class="id">13</span>What's your biggest mistake?</div><div class="a">The "who wrote last" rule. I guessed the highest number instead of following the dominoes. It even created a fake "missing 1,200 points" story in my own report.</div></div>

<div class="qa"><div class="q"><span class="id">14</span>Why didn't you put the fix into the homework?</div><div class="a">Because it changes an official answer, and an official answer should only change when the school agrees with the new rule. So I wrote it down as a known weak spot and fixed it separately.</div></div>

<div class="qa"><div class="q"><span class="id">15</span>Who did the work — you or the AI?</div><div class="a">An AI helper wrote most of it while I directed and checked every step. The robot being tested is a different one, and it never saw the answer key.</div></div>

<div class="qa"><div class="q"><span class="id">16</span>What are you proudest of?</div><div class="a">That my own checks caught me — twice. And that the lock sits where the robot's words can't reach it.</div></div>

# <span class="num">18</span>The big decisions, one line each 🧭 {#k-decisions}

<p class="lede">The 27 decisions of the handed-in homework, in school words. The full versions — with
the other options and what each one cost — are in chapter 18 of the original study guide.</p>

<div class="splittable" markdown="1">

| # | The decision, in school words |
|---|---|
| D001 | Put the homework where the teacher will look first (the top of the folder) |
| D002 | Choose an archive that can lock each drawer (and run it even without the usual container tool) |
| D003 | Get the paperwork from a trusted public copy whose counts match the official list |
| D004 | Hide practice mistakes in a separate practice room, never in the real paperwork |
| D005 | Ask the robot through a sealed window: it only receives text — no tools, no archive |
| D006 | Keep one list of Czech-word translations, and check that every copy agrees with it |
| D007 | Use the pupils' and books' own numbers as labels; don't invent new ones |
| D008 | The "do not use" tray must say which pile a line came from |
| D009 | The lock is on the drawer and asks who holds the key card — not a note anyone could write |
| D010 | Every folder between the reader and the drawer must honour the locks |
| D011 | The robot never peeks, and its homework is marked by the numbers, not the handwriting |
| D012 | Rebuilding the cabinet also puts the reading shelf back |
| D013 | Never correct the original; keep the old version next to the new one |
| D014 | Seven ways of writing "nothing" become one real "empty"; the original stays |
| D015 | Two-digit years are 19xx; an unreadable date becomes "empty" instead of stopping everything |
| D016 | Birthday and boy/girl are worked out from the secret code, and labelled "worked out" |
| D017 | One translation list; the Czech word stays next to the English one; an unknown word stops the build |
| D018 | Plus or minus is decided once, in the tidying room |
| D019 | The month-end total is worked out once, with the "who was last" rule written down |
| D020 | The tidying room throws nothing away; the checking room decides |
| D021 | A pupil who logs in *is* one pupil — not a teacher with a group of one |
| D022 | *(Replaced by D023)* At first, a pupil only saw the books they own |
| D023 | A pupil sees every book they are allowed to use, not only their own |
| D024 | Being allowed to sign in a book gives you that book — never the person |
| D025 | Three names for a pupil: an inside number, a code safe to share, and the book number they recognise |
| D026 | The secret code is checked by the archive itself, not just at the front door |
| D027 | Access is worked out live from the lists; only a human decision (a substitute) is stored |
| *D028* | *Later:* the domino rule decides which entry was last |
| *D029* | *Later:* the robot must say what it intends, and its slip must match that |

</div>

# <span class="num">19</span>The guesses we had to make 🤔 {#k-assumptions}

<p class="lede">When the paperwork or the question didn't say, we chose — and wrote the choice down,
with what changes if it's wrong. Here are all 46, in school words.</p>

## How we understood the questions {#k-ass-questions}

| # | The guess |
|---|---|
| A1 | "Wing" means the wing of the pupil's **own** home topic |
| A2 | Count **all** pupils, also helpers who own no book |
| A3 | A plan is dated by its start day; its size is its own size |
| A4 | "Went wrong" = B or D — **needs the school's OK** |
| A5 | The owner's badge means the owner's own badge, not a helper's |
| A6 | Owners without a badge are shown as "no badge", not left out |
| A7 | "Points coming in" = entries that add points, counted positive (bonus points included — **needs the school's OK**) |
| A8 | Q5 uses the topic the book is filed under |
| A9 | Show all twelve months, even a month with zero |
| A10 | Age is exact, with decimals |
| A11 | The owner is the owner of the plan's book; impossible ages are shown both ways |
| A12 | Gold-badge owners are owners whose own badge is gold |
| A13 | Count owner lines (one per book), with the number of different pupils beside it |
| A14 | The month-end total is after the last entry on or before that day; same-day ties go to the highest number (the weak spot) |
| A15 | Books with no total yet are left out, not counted as zero |
| A16 | The share is worked out inside each report frequency |

## The paperwork, the archive and the tidying {#k-ass-paper}

| # | The guess |
|---|---|
| A17 | Two-digit years are 19xx |
| A18 | Girls' birth months have 50 added; that is the only source of boy/girl |
| A19 | All points are the same kind (in the bank: all amounts are Czech crowns) |
| A20 | Points have one decimal, so totals are checked with a small rounding margin (1 point, and 100 points for "serious") |
| A21 | A tutor sees the pupil, the books that pupil owns, and everything in them |
| A22 | The topic list, the calendar and the translation list are open to everyone |
| A23 | The public copy is the real paperwork (no copy from the school office arrived) |
| A24 | The robot is a guest who never sees the archive; its slips are always checked |
| A25 | The seven ways of writing "nothing" are the full list |
| A26 | "Empty" after tidying means "never written down", never "we lost it" |
| A27 | An entry with no type is a bonus point the school added itself |
| A28 | A code we don't know stops the build instead of being guessed |
| A29 | Only `PRIJEM` adds points; `VYDAJ` and `VYBER` take points away |
| A30 | The book's own written total is believed; we never recalculate it |
| A31 | The paperwork is one snapshot, with no history |
| A32 | Everything happens between 1 January 1993 and 31 December 1998 |
| A33 | The order of lines in a box means nothing |

## Logging in and who may see what {#k-ass-access}

| # | The guess |
|---|---|
| A34 | A pupil logs in with their own login, never a shared one |
| A35 | The school office decides which login belongs to which pupil |
| A36 | *(Replaced by A39)* A pupil only sees the books they own |
| A37 | The topic list is not secret, so a pupil may see all 77 topics |
| A38 | A "who read what" logbook is not needed for this homework |
| A39 | A pupil sees every book they are allowed to use |
| A40 | Being a helper gives you the book only — not the owner's file, not their other books |
| A41 | A tutor's group means "see", never "spend" |
| A42 | The share-safe code (`BRK-…`) is safe enough to show on screen |
| A43 | A 30-second code is good enough for this demonstration |
| A44 | The code secrets are stored so the archive can read them back (needed to check codes) |
| A45 | Tying a visit pass to the connection number is enough to stop copying it |
| A46 | Showing the code on screen in the demo is fine — for a demo |
| *A47* | *Later:* the boy/girl of a study plan is the owner's — **needs the school's OK** |
| *A48* | *Later:* "Q1" means January–March (calendar quarters), one row per period — **needs the school's OK** |
| *A49* | *Later:* bonus points count as points coming in — **needs the school's OK** |

# <span class="num">20</span>Word list 📚 {#k-words-list}

<div class="splittable" markdown="1">

| School word | Real word | Meaning |
|---|---|---|
| Berka School | the bank | Where all the paperwork comes from |
| Pupil | client | A person; 5,369 of them |
| Record book | account | A pupil's file: points in, points out, total; 4,500 |
| Entry | transaction | One line in a record book; 1,056,320 |
| Point total | balance | How many points the book holds right now |
| Owner / helper | owner / disponent (disposition) | Whose book it is / who else may sign in it |
| Study plan | loan | Extra tutoring given to a book; 682 |
| Went wrong | problematic (status B or D) | Not passed, or falling behind |
| Badge | card | junior, classic or gold; 892 |
| Topic / wing | district / region | 77 topics in 8 wings |
| Report frequency | statement frequency | monthly, weekly, after every entry |
| Bonus points | interest (`UROK`) | Points the school adds by itself |
| Tutor, group list | relationship manager, portfolio | A staff member and the pupils they look after |
| Head teacher | `cro_global` | Sees everyone, because her list has everyone on it |
| Substitute / counsellor | delegation | Temporary access to one pupil, with a reason and an end date |
| Copy room | `raw` (bronze) | Paperwork exactly as it arrived |
| Tidying room | `stg` (silver) | Readable, decoded, nothing thrown away |
| Checking room | `dq` | Checks, stickers, the "do not use" tray |
| Red / orange / green | block / warn / info | Into the tray / sticker that travels / just noted |
| Filing cabinet | `core` (gold) | The neat drawers, one meaning per word |
| Reading shelf | `ai` | The only place anyone may read from |
| Key office | `sec` | Who is who and who may see what |
| Drawer lock | row level security | Opens only for files this person may see |
| Key card + code | password + TOTP (two-factor login) | Both needed; the archive checks the code itself |
| School dictionary | semantic layer / context pack | Every word the robot may use, and what it is *not* |
| Robot 🤖 | the LLM (Claude Sonnet 5.5; qwen2.5-coder:3b) | Writes request slips from questions in normal words |
| Request slip | SQL query | What the robot asks the archive for |
| Desk clerk | SQL guard | Checks a slip is safe — not that it is right |
| Answer key | reference SQL and results | The right answers, written before the test |
| Marking | evaluation | Comparing the robot's numbers with the answer key |
| Dominoes | the balance chain | Each entry starts where the previous one ended |
| Logbook | run log | Which step ran, when, on which version |

</div>
