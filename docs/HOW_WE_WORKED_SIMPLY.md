# How we did it, in plain words

No jargon. If a word has to be technical, it is explained right where it
appears. This is the whole way of working, and then every one of the ten
questions, one at a time.

---

## 1. What the bank asked for

A bank has eight big lists: people, accounts, loans, bank cards, who is
allowed to use which account, every payment, standing orders, and a list of
towns.

They want their staff to be able to ask a computer helper a normal question,
like *"how many customers do we have in each part of the country?"*, and get
the right answer back.

For that to work, three things have to be true. All three. Miss one and the
helper gives an answer that **looks** right and **is** wrong, which is worse
than no answer at all.

1. **The data has to be tidy.** If the same payment is written down twice,
   every total that includes it is too big.
2. **The words have to mean one thing.** If "a bad loan" means one thing to
   you and another thing to me, we will both be sure, and we will disagree.
3. **People must only see their own customers.** A bank is not allowed to let
   everyone see everything.

---

## 2. The way of working, as four steps

Think of it like cooking a meal from a messy box of shopping.

### Step 1 — Bronze: copy everything exactly, change nothing

Take a photocopy of the shopping list. Do not fix the spelling. Do not throw
away the squashed tomato.

Why be so strict? Because later, when somebody argues about a number, you must
be able to say *"here is exactly what arrived, before anybody touched it."*

We also write down the size of each file and give it a fingerprint (a long
code that changes if even one letter changes), so we can always prove the
files never changed behind our backs.

> **What it looks like:** 1,079,680 rows copied in under four seconds, and
> every count matched the number the dataset is published with.

### Step 2 — Silver: tidy up, and write down everything that is broken

Now we sort the shopping. Dates become real dates. Czech codes become English
words, so `POPLATEK MESICNE` becomes `monthly`.

And we check everything. We wrote **123 checks** — things like *"every payment
must belong to a real account"* and *"no two customers can have the same
customer number"*.

Here is the important bit. **We never throw a row away quietly.** When a check
finds something broken, we decide how bad it is, using three colours:

| Colour | What it means | What we do |
|---|---|---|
| 🔴 **Red** | This breaks a number people rely on | Put the row in a box marked "do not use", write down why, and keep the box |
| 🟠 **Orange** | The row is still usable, but anyone using it should be warned | Keep the row and stick a note on it. The note travels all the way to the final answer |
| 🟢 **Green** | Untidy, but no answer changes | Tidy it up and write it in the log |

The colour is the hard part, not the check. Here is the best example:

> We found 14 payments with an amount of **zero**. A rule saying "every payment
> must be more than zero" sounds obviously right. But those 14 are real — they
> are interest payments where the interest worked out to nothing. If we marked
> them 🔴 red and threw them out, we would break the running total of 14
> customers' accounts **to fix nothing at all**. So they are 🟢 green.
>
> But a payment with a **negative** amount is 🔴 red, because that means a
> minus sign got added twice, and money would move the wrong way.

Same kind of problem, opposite decision, and we can say why for each one.

### Step 3 — Gold: build the shelves, and agree what words mean

Now we arrange everything into neat shelves: one shelf for customers, one for
accounts, one for loans, one for payments.

Each shelf has a rule about what one row means. The customer shelf has exactly
one row per customer. That sounds obvious. It matters enormously: if that shelf
accidentally had a customer twice, then *every* count of customers would be too
high, and **nothing would show an error**. The computer would happily give you
a confident wrong number. So we check it every single time we build.

This is also where we decide what words mean, **once**:

- *"a problematic loan"* = a loan that finished without being paid back, **or**
  one that is still running with the customer in debt.
- *"money coming in"* = a payment that adds to the balance.
- *"the account owner"* = the one person who legally owns the account (not a
  husband or wife who is merely allowed to use it).

Writing these down once is the single most useful thing in the whole project,
because now nobody can quietly use a different meaning.

### Step 4 — Let the helper answer questions, safely

Now the computer helper (the AI) can be let in. We gave it three things:

**A dictionary.** A written guide that says what every shelf holds, what every
word means, and — this is the clever part — what each word does **not** mean.
The helper is not allowed to look at the data. It only gets the dictionary and
the question. That way, if it answers correctly, we know the dictionary was
good, not that the helper went digging.

**A bouncer.** The helper writes out an instruction for the database. Before
that instruction runs, a bouncer reads it properly — like reading a sentence
for its grammar, not just looking for rude words — and throws it out unless it
is a single harmless "please show me" request about the public shelves.

**A lock, on the shelves themselves.** This is the part people get wrong. You
could ask the helper nicely to only show someone their own customers. That is
not a lock, that is a *request* — you are asking the thing you are limiting to
limit itself.

So instead, the lock is **on the shelf**. When Anna from the northern branch
asks a question, the shelf itself only hands over northern customers. The
helper never even knows there was a lock, and nothing it could possibly write
can unlock it, because the lock is not part of the question.

> **Proof, not promises:** we logged in as four different staff members and
> counted. Anna sees 1,481 customers. Ben in the south sees 1,386. The risk
> manager sees all 5,369. A brand-new employee with no customers assigned sees
> **0** — not everything, which is what a badly built system would do.
>
> Then we tried nine ways to break in: pretending to be someone else, going
> round the back of the shelves, turning the lock off. All nine failed.

---

## 3. How we know it is right, and not just finished

Three habits, and they are the real answer to *"how do you work?"*

**We wrote the answers out by hand first.** Before the helper saw anything, a
person worked out all ten answers the slow, careful way. Those are the marking
scheme. The helper's answers are compared against them. The helper got
**10 out of 10 right, first try.**

**We broke our own data on purpose.** The bank's copy of the data is clean, so
nearly all our checks found nothing. A check that has never caught anything is
not proof of anything. So we made a damaged copy — one broken thing for each
kind of check, 20 in total — and made sure every single one got caught by the
check meant to catch it.

**We assume we have made a mistake, and go looking.** This one earned its keep.
Twice:

> Our own testing almost deleted real data. The "do not use" box was not
> labelled with which copy of the data it came from, so when we tested our
> checks on the damaged copy, the damaged results started removing rows from
> the **real** data. The build failed and told us before anything was sent
> anywhere. Nothing was wrong with the data; the filing was wrong.

> The lock leaked. Because of one missing setting, a shelf was handing over all
> 682 loans to a user entitled to none — while the shelf underneath it was
> correctly handing over zero to the same person at the same moment. The design
> was right and one line of setup was missing. We only found it because we
> logged in as a restricted user and counted, instead of reading our own
> settings and nodding.

Both are written down in the project rather than quietly fixed. A system that
has never caught itself being wrong has not been tested.

---

## 4. The ten questions

For each one: what makes it harder than it looks, and what the answer is.

### Q1 — How many clients do we have per region?

**The catch:** people move. 409 customers (9 in every 100) live in a different
part of the country from where their account was opened. So "their region" has
two possible meanings and they give different answers.

**What we did:** used the region where the **person** lives, because the
question is about people. We wrote that choice down, so nobody has to guess.

**Answer:** south Moravia 937, north Moravia 920, central Bohemia 664,
Prague 663, and four more regions. All eight add up to exactly 5,369, which is
every customer — a good sign that nobody fell through a crack.

### Q2 — What is the total amount of loans granted per year?

**The catch:** "the amount of a loan" could mean the money handed over, or
everything paid back including interest. Those are very different numbers.

**What we did:** used the money handed over.

**Answer:** 1993: 2.6m · 1994: 13.4m · 1995: 13.3m · 1996: 18.3m, then 1997 and
1998. All 682 loans are counted, none missing.

### Q3 — What percentage of our loans are problematic?

**The catch:** what counts as "problematic"? If you only count loans where the
money is definitely lost, you get 4.5%. If you also count loans where the
customer is currently behind, you get 11%. Same data, two very different
stories for a bank.

**What we did:** counted both — finished-and-unpaid **and** still-running-and-
behind — and wrote that definition into the system so it is used everywhere.

**Answer:** **76 problematic loans out of 682 — 11.14%.** This is the one
number the dataset is published with, and ours matches it exactly, which is a
useful check that the whole pipeline is sound.

### Q4 — What is the average loan amount per card type of the account owner?

**The catch:** two of them. First, a bank card can belong to a husband or wife
who is allowed to use the account but does not own it — their gold card must
not make the owner look like a gold card holder. Second, most owners have no
card at all, and if you quietly drop them you are secretly answering a
different question.

**What we did:** only counted the owner's own card, and made "no card" a proper
category instead of dropping it.

**Answer:** junior 221,970 · gold 161,881 · no card 148,865 · classic 148,809.
The loan counts add back up to 682, so nobody was dropped.

### Q5 — Which 10 districts had the highest incoming money in 1997?

**The catch:** this one deliberately uses the *other* meaning of region from
Q1. Money arrives at an **account**, not at a person, so here we use where the
account lives. Also "incoming" must mean money arriving, not money arriving
minus money leaving.

**Answer:** Prague is far ahead with 115.1m, then Karvina 28.5m, Ostrava 27.7m,
Brno 23.1m, and six more.

### Q6 — How many new accounts were opened per month in 1996?

**The catch:** a sneaky one. If no accounts were opened in some month, and you
just count what is there, that month **disappears from the list entirely**. The
reader sees eleven months and assumes that is all the data. "No accounts" and
"no information" are different things and must not look the same.

**What we did:** started from a calendar of all twelve months and counted into
it, so an empty month shows up as a proper zero.

**Answer:** all twelve months present. January 106, February 104, March 124,
April 101, and so on.

### Q7 — What was the average age of the owner at loan start, per loan status?

**The catch:** if you work out age by subtracting the birth year from the loan
year, everyone comes out about half a year too old. You have to count the
actual days.

**We also found something odd:** six loans were given to owners recorded as
being under 15 years old, the youngest 10. A ten-year-old cannot take out a
loan, so something in those records is wrong. We did not delete them — the loan
amounts are fine and deleting them would spoil other answers. We flagged them
🟠 orange and report the average both with and without them, so the reader can
see how much it matters.

**Answer:** paid in full 37.1 · finished unpaid 39.6 · running fine 38.7 ·
running in debt 37.0.

### Q8 — What is the gender split of owners with a gold card?

**The catch:** same as Q4 — only the owner's own gold card counts.

**Answer:** **53 men (60.2%) and 35 women (39.8%).** They add to 100%, and the
88 card holders are 88 different people, so nobody is counted twice.

### Q9 — What was the average account balance at the end of December 1998?

**The hardest question of the ten**, and the only one where we had to admit we
could not be perfectly certain.

**Catch one:** some accounts had no activity at all in December. They still
have a balance — the one from whenever they were last used. We carry it
forward, and mark it as carried forward so nobody mistakes it for fresh.

**Catch two:** when several payments happen on the **same day**, the data does
not record what order they happened in. For 183 accounts, that uncertainty
lands on their very last day — so "the closing balance" is a sensible choice we
made, not a fact the data contains. We wrote down exactly which choice.

**Catch three:** we checked whether each account's payments add up to its
stated balance. For most, the gap is a few pennies from rounding. But **55
accounts are off by more than 100**, and one by exactly 1,200 with only 55
payments — that is a missing or duplicated payment, not rounding.

**What we did:** we did not hide any of that. We give the number *and* the
warnings next to it.

**Answer:** **43,808.94 on average**, across all 4,500 accounts. Middle value
38,494.55. Lowest −25,821 (overdrawn), highest 138,317. 76 accounts carried
forward; 55 flagged as not adding up.

### Q10 — Which statement frequency has the most problematic loans?

**The catch:** "highest share" means *within each group*, not each group's slice
of the total. And watch the group sizes — a group of 32 can look dramatic.

**Answer:** **"after each transaction" is highest at 18.75%** — but that is only
6 problem loans out of 32. Weekly is 12.09% (11 of 91), monthly 10.55% (59 of
559). We show the full list with the counts, because 6 out of 32 is a much
shakier basis for a decision than 59 out of 559, and a reader deserves to see
that rather than just the winning percentage.

---

## 5. The shortest possible summary

> Copy the data exactly. Tidy it up and grade everything broken by how much it
> actually hurts. Decide what the words mean, once, and write it down. Put the
> lock on the shelf, not in the request. Work out the answers by hand first, so
> you have something to check against. Break your own system on purpose, so you
> know the checks work. And when you find you were wrong, write that down too.

Ten questions asked, ten answered correctly, first try.
