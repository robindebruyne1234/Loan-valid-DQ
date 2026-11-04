# <span class="num">9</span>The lessons, generalised {#lessons}

<p class="lede">Twelve rules that the findings above taught. These are what an interviewer is
really asking for when they say "what did you learn?" — each comes with the finding that taught
it.</p>

| # | Lesson | Taught by |
|---:|---|---|
| 1 | **A derived check inherits the bugs of the derivation it reads.** Test it against an independent derivation | L-02, L-03 |
| 2 | **"Unknowable" is a hypothesis.** Look for indirect evidence in the data before documenting a tie-break; measure how often it matters | L-01 |
| 3 | **A green build is not a correct build.** Verify the model's grains, keys and reconciliation after every build | H-01, H-03 |
| 4 | **Test security as the attacker.** Log in as the restricted user and count rows; never trust reading your own DDL | H-02, L-05 |
| 5 | **Safe and correct are different properties.** A query can be harmless and wrong; governance must make wrong answers detectable, not only harmful queries impossible | L-07 |
| 6 | **Hidden is not absent.** Never let a view turn "not visible to you" into a value | L-06 |
| 7 | **Do not tune the evaluation to the test.** Keep a hold-out set, keep question ids out of the context, sample more than once | L-08 |
| 8 | **Hand-typed numbers drift.** Generate every figure from the command that measures it, or keep it in one document the others link to | L-14 |
| 9 | **Precise disclosure beats generous disclosure.** Say exactly who wrote what; overstatement costs more credibility than the fact | L-12 |
| 10 | **A documented control without a test is a hope.** Writing the lockout test found the rollback gap | L-09 |
| 11 | **A checker needs tests against correct answers too**, or it trades false answers for false refusals | P-03 |
| 12 | **Commit and push from every working copy, every day**, and scope to the brief — demonstrate governance, not infrastructure | L-19, L-20 |

# <span class="num">10</span>The conversation playbook {#playbook}

## Questions about mistakes, and how to answer them {#mistake-questions}

<div class="qa"><div class="q"><span class="id">1</span>What was your biggest mistake?</div><div class="a">The month-end tie-break. I accepted that the source had no intra-day order and documented a rule instead of testing it; the running balance did encode the order. It was right only 0.4% of the time, it produced a fake "1,200 CZK missing posting" in my own defect report, and it inflated my material reconciliation breaks from 14 to 55. The average was robust; the account-level balances were not. I fixed it after delivery with the chain rule and a test. (L-01–L-03)</div></div>

<div class="qa"><div class="q"><span class="id">2</span>What would you do differently?</div><div class="a">Three things. Test every "the data cannot tell us" claim against the data before writing it down. Verify the meaning of generated SQL, not only its shape, from the start. And keep a hold-out set of questions so the evaluation measures generalisation, not my own semantic layer.</div></div>

<div class="qa"><div class="q"><span class="id">3</span>Did you find anything wrong after you submitted?</div><div class="a">Yes, and I prefer to tell you than to have you find it: the tie-break artefacts, the disponent seeing the owner's card, hidden values shown as "no card", a duplicate rule that can only catch zero-amount duplicates, and a few mislabels in generated reports. Two of them I fixed on a branch, with before/after evidence; the rest are listed with their fix.</div></div>

<div class="qa"><div class="q"><span class="id">4</span>Why didn't you merge the fix into the submission?</div><div class="a">It changes a certified number and its reference answer. Changing a certified number during a delivery freeze, without the business signing off the new rule, is exactly what a governed product should not do. So the submission discloses the limitation, and the fix waits on a branch with its tests.</div></div>

<div class="qa"><div class="q"><span class="id">5</span>How much of this did the AI write?</div><div class="a">Most of the code, under my direction, with every step executed and checked against the database; the disclosure names each model and role. The model under test never saw the reference SQL or the data. One wording in my disclosure is too generous — "hand written" — and the precise version is "not written by the model under test, and independently re-derived from raw". (L-12)</div></div>

<div class="qa"><div class="q"><span class="id">6</span>If the guard does not check meaning, why should anyone trust an answer?</div><div class="a">In the delivered version, because the semantic layer removes most reasons to guess, a wrong name fails safely in the database, and the evaluation compares values with independent SQL. That is not enough for live users, which is why the next step — built after delivery — verifies the model's declared intent against its SQL and recomputes the certified metric before any number is shown. (L-07)</div></div>

<div class="qa"><div class="q"><span class="id">7</span>Isn't this over-engineered for a 1–2 day take-home?</div><div class="a">The extras are, and I can say what I would cut first: the deployment guide, the simulated agents, then the web page. The core stayed deliberately small — one database, SQL files, Python — so that the time went into the data, the definitions and the enforcement, which is what the brief is about. (L-19)</div></div>

<div class="qa"><div class="q"><span class="id">8</span>What are you most proud of?</div><div class="a">That the system caught me twice — the self-test that nearly deleted real data and the view that leaked — because I built checks that distrust the build. And that the entitlement filter is somewhere the model's text cannot reach.</div></div>

## Phrases that help {#phrases}

| Situation | Say |
|---|---|
| Admitting a defect | "That is a real defect. Here is what it changes, by how much, and the fix." |
| A number you do not have | "I did not measure that. The closest figure I have is …, and I would measure it with …" |
| A claim that was too broad | "I stated that too broadly. What is true is …" |
| A design choice under attack | "The alternative was …; I chose this because …; the cost is …" |
| Delivered vs later work | "In what I submitted … ; after submitting I …" |
| Pressure to agree with a wrong premise | "I don't think that is quite right — the evidence is …" |

:::danger Never say
- "The guard guarantees the SQL is correct."
- "No derived table can resolve what the source did not record."
- "A person wrote all the reference answers by hand."
- "The disponent cannot see anything of the owner's."
- "Q9 is 43,810.47" — as the delivered answer. Delivered: 43,808.94.
- "There are 241 tests." Delivered: 327 passed, 1 skipped.
:::
