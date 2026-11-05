# <span class="num">0</span>Start here 🏫 {#k-start}

<p class="lede">This is the same study guide, chapter for chapter, but told as a story about a
school. If a grown-up word ever feels heavy, come back here: everything in the project has a
school twin.</p>

## The story in one breath {#k-story}

> Berka School keeps a **record book** for every pupil in its archive. Every time a pupil earns
> points, or uses them, somebody writes an **entry** in the book with the new total. The school
> also has **study plans** for pupils who get extra tutoring, and **badges** (junior, classic,
> gold).
>
> Now the pupils and the teachers want a **robot 🤖** they can ask questions in normal words:
> *"How many pupils are in each wing?"*, *"How many study plans went wrong?"*. The robot is clever
> with words, but it has never been inside the archive. It guesses when it is not sure, and
> whatever it asks the archive for, the archive hands over.
>
> So we treated the robot as a helper who is **a bit clumsy** (it will guess) and **a bit
> risky** (what it asks for really happens). We tidied the paperwork, wrote a dictionary of what
> every word means, put a clerk at the archive desk who checks every request, and — most
> important — put a **lock on every drawer** that only opens for the right person. The robot
> never has the key.

## The map: the bank and its school twin {#k-map}

Keep this page open the first time you read. On the left is the real project, on the right its
school twin. The numbers are the real ones. One thing to know: **Berka School is a school for all
ages** — the real customers are adults, so some of our "pupils" are 60 years old.

<div class="splittable" markdown="1">

| In the real project (the bank) | In the school |
|---|---|
| The bank (Berka, a Czech bank, 1993–1998) | **Berka School** |
| 8 source files | 8 boxes of paperwork from the school office |
| Client — 5,369 | **Pupil** |
| Account — 4,500 | **Record book**: a pupil's file in the archive, with points in, points out and a running total |
| Transaction — 1,056,320 | **An entry** in a record book: points earned (+) or used (−), and the total after it |
| Balance (in CZK) | The **point total** of a record book |
| Disposition: owner / disponent — 5,369 | Who may use a record book: the **owner** (the pupil it belongs to) or a **helper** allowed to sign in it, like a big brother |
| Loan — 682 | A **study plan** (extra tutoring) the school gave to a record book |
| Loan status A / B / C / D | A finished and passed · B finished, **not** passed · C still running, going fine · D still running, **falling behind** |
| "Problematic" loan (B or D) | A study plan that **went wrong** (not passed, or falling behind) |
| Card — 892: junior / classic / gold | A **badge**: junior / classic / gold |
| Permanent order — 6,471 | A standing arrangement: points moved automatically every month |
| Interest (`UROK`) | **Bonus points** the school adds by itself |
| District — 77 | A **topic** (geology, maths, science …). Every pupil has a *home topic*, and every record book is filed under a topic |
| Region — 8 | A **wing** of the school that groups topics (like the Science wing) |
| Statement frequency | How often a **report goes home**: monthly, weekly, or after every entry |
| Bank staff: relationship managers `rm_north`, `rm_south` | **Tutors** (Ms North, Mr South), each responsible for a group of pupils |
| Portfolio | A tutor's **group list** |
| `cro_global` (group risk) | The **head teacher**, whose list contains every pupil |
| `rm_unassigned` | A **new teacher** with no group yet |
| Delegation | A **substitute** or the **counsellor**: temporary access to one pupil, with a reason and an end date |
| `client_3763`, `client_3764` | Two **pupils** who log in to see their own book (3764 is a helper on 3763's book) |
| The database (PostgreSQL) | **The archive building** |
| The LLM (Claude Sonnet 5.5; Ollama qwen2.5-coder:3b) | **The robot 🤖** (the big robot; the little robot) |
| SQL | The robot's **request slip** to the archive |

</div>

## The school in numbers {#k-numbers}

<div class="stats">
<div><span class="n">5,369</span><span class="l">pupils (clients)</span></div>
<div><span class="n">4,500</span><span class="l">record books (accounts)</span></div>
<div><span class="n">1,056,320</span><span class="l">entries in the record books (transactions)</span></div>
<div><span class="n">682</span><span class="l">study plans (loans)</span></div>
<div><span class="n">77</span><span class="l">topics (districts), in 8 wings (regions)</span></div>
<div><span class="n">124</span><span class="l">checks on the paperwork (data quality rules)</span></div>
<div><span class="n">1</span><span class="l">entry put in the "do not use" tray (quarantine)</span></div>
<div><span class="n">10 / 10</span><span class="l">questions the big robot answered right (recorded run)</span></div>
</div>

## Two versions of the homework {#k-versions}

The school handed in its homework on **28 October 2026** (the *delivered version*,
`delivery-freeze-2026-10-28`, commit `fc0c281`). After handing it in, two things were improved
on a separate page (a separate branch): how the school decides which entry was *last* on a busy
day, and an extra check that the robot's request really asks for what it says it wants. In this
guide those later improvements are always marked **"Later we fixed it"**.

:::key The one thing to remember
When you talk about the homework you handed in, use the numbers you handed in. The average point
total at the end of December 1998 was **43,808.94** in the delivered version. The later fix makes
it 43,810.47 — that is "what I improved afterwards", never "what I handed in".
:::

## How to use this edition {#k-how}

1. Read this school edition first, in one go, to get the whole picture.
2. Then read the same chapter in the original study guide (01): the chapter numbers match.
3. Each chapter here ends with **In grown-up words** — the real terms and IDs (D for decisions,
   A for assumptions, L for lessons) so you can switch back instantly.
4. Boxes called **Oops!** are the weak spots. The full list is in the Lessons Learned document.
