# <span class="num">16</span>What breaks at 100,000× the volume {#scale}

<p class="lede">The DDR's answer, reasoned rather than benchmarked: about 100 billion postings,
450 million accounts and some 10 TB of facts before indexes.</p>

| # | What breaks | Why | What it becomes |
|---:|---|---|---|
| 1 | **Ingestion and rebuilds** | `core` is rebuilt with `CREATE TABLE AS` on every run: hours rewriting unchanged data | Incremental: facts range-partitioned by month; only open partitions rebuilt; merge, not replace |
| 2 | **The data quality runner** | 124 full scans; violating keys sampled through Python | Partition-scoped rules (check what arrived); keys written by `INSERT … SELECT`; per-account state for the balance reconciliation; `info` rules sampled with a stated confidence; `block` stays exact |
| 3 | **The month-end fact** | 450 m accounts × 72 month ends = 32 bn rows rebuilt from scratch | A snapshot maintained from the previous month plus that month's postings (and the chain ordering decided once, at ingest) |
| 4 | **Latency and concurrency** | Ad-hoc generated SQL over 10 TB is a full scan unless it prunes; many users exhaust one node and a role-per-user pool | Partitions and indexes on certified time columns; pre-aggregated marts for certified metrics; per-tier timeouts; a pooled gateway doing `SET ROLE` |
| 5 | **The entitlement predicate** | A hash join over 4,500 accounts today; over millions for a large portfolio | A materialised `(role, account_id)` set, refreshed on change and co-partitioned with the facts. The design does not change: still a policy; onboarding still an insert |
| 6 | **Evaluation and operations** | Reference queries scanning everything are too slow per build; ten questions are not a test set | Frozen samples with checksums; a hold-out question set; monitoring of guard refusals, query cost, rule trends and entitlement changes |

**What does not break:** where the filter sits, and the semantic layer's size — about 8,400
tokens at any volume (though many more entities would need retrieval instead of one pack). A
single PostgreSQL node is the wrong host for 10 TB: PostgreSQL with Citus, or a columnar MPP
engine (ClickHouse, StarRocks), carrying the same schemas, rules and policy model, is the port
to evaluate — or a cloud warehouse's row access policies, with the semantic layer and the
policies moving as contracts.

:::say
"At a hundred thousand times, everything that is 'rebuild from scratch' becomes 'maintain
incrementally' — the core facts, the rule runs, the month-end snapshot — and the entitlement
join becomes a materialised set. What does not change is the design: the filter stays in the
engine, onboarding stays an insert, and the semantic layer stays the same size."
:::

# <span class="num">17</span>Question bank {#bank}

<p class="lede">The questions most likely to come up in the 15 minutes, with a short model
answer. Rehearse them out loud; the goal is the first two sentences, not the whole
paragraph. IDs in brackets point to decisions (D), assumptions (A) and lessons (L).</p>

## Brief, scope and design {#bank-design}

<div class="qa"><div class="q"><span class="id">1</span>Walk me through the architecture in two minutes.</div><div class="a">Six schemas, each with a contract: raw (verbatim, hashed) → stg (typed, decoded, nothing filtered) → dq (rules, quarantine, flags) → core (star schema = stg − quarantine, verified each build) → ai (business-named security-invoker views) — with sec beside core holding who may see what, read by seven RLS policies. Then the semantic layer, the guard and the login on the AI path.</div></div>

<div class="qa"><div class="q"><span class="id">2</span>The brief said 1–2 days and warned against infrastructure. Why 2FA, a web app, a deployment guide?</div><div class="a">The three tasks were built and evaluated first. The extras were added on request, and each demonstrates a governance point — the second factor enforced where the data is, onboarding as a data change — while the stack stayed minimal: one database, SQL files, plain Python. What I would cut first: the deployment guide and the simulated agents, then the web page. (L-19)</div></div>

<div class="qa"><div class="q"><span class="id">3</span>Why PostgreSQL rather than DuckDB or a warehouse?</div><div class="a">Task 3 is enforcement. The honest proof that generated SQL cannot bypass a filter is a filter in the engine and a test that connects as a restricted user. DuckDB has no row level security. At 100,000× I would change the engine, not the pattern. (D002)</div></div>

<div class="qa"><div class="q"><span class="id">4</span>What does "AI-ready" mean in your solution?</div><div class="a">Clean typed data with one definition per term; business names; caveats that reach the answer; a semantic layer the build validates; and an entitlement filter the model cannot see or change. Not "we added an LLM".</div></div>

<div class="qa"><div class="q"><span class="id">5</span>Which single assumption, if wrong, invalidates the most?</div><div class="a">The owner definition: one OWNER disposition per account. It underlies Q4, Q7, Q8 and the ownership grant. It is checked by a block rule (4,500 owners for 4,500 accounts). A close second is the sign convention (PRIJEM credit; VYDAJ and VYBER debit), confirmed by the running balance. (A5, A11, A29)</div></div>

<div class="qa"><div class="q"><span class="id">6</span>What would you do with one more day?</div><div class="a">Fix the month-end tie-break with the balance chain and a test; add intent verification so a safe-but-wrong query is refused; fix the disponent card visibility and the "no card" coalesce; run a hold-out evaluation. I have since done the first two on a branch. (L-01, L-07)</div></div>

## Data quality and cleaning {#bank-dq}

<div class="qa"><div class="q"><span class="id">7</span>Give one block, one warn and one info, and why.</div><div class="a">Block: a duplicate posting by business key — it double-counts a flow, so it is quarantined. Warn: owner under 15 at loan start (6 loans) — impossible, but removing the loans would break loan totals used by four other questions, so flag it. Info: 14 zero-amount postings — real interest runs that accrued nothing; changes no sum.</div></div>

<div class="qa"><div class="q"><span class="id">8</span>Your only blocked row is a 0.00 CZK posting. What did blocking protect?</div><div class="a">Nothing measurable in money — and the rule's construction explains why: it requires the same resulting balance, so it can only catch duplicates that did not move the balance. A real duplicated payment would change the balance and slip past it. A warn rule on repeated identical batches is the fix; 1,081 groups of repeated identical interest postings would need a business decision. (L-04)</div></div>

<div class="qa"><div class="q"><span class="id">9</span>Why never repair a value?</div><div class="a">Because a repaired value is indistinguishable from an observed one a week later, and someone will eventually reconcile a number against a statement. The original stays in a _raw column with a note; the rules decide what reaches the product. (D013)</div></div>

<div class="qa"><div class="q"><span class="id">10</span>How do you know the cleaning lost nothing?</div><div class="a">raw = stg on eight row counts and three money sums; core = stg − quarantine on seven row counts and two money sums, after every build. The one quarantined row shows in the row count, not in money (it is 0.00).</div></div>

<div class="qa"><div class="q"><span class="id">11</span>124 rules — how many are meaningful?</div><div class="a">89 are written by hand with a rationale; 35 are a generated completeness sweep. 19 fire on the public copy; the other rules are proven by 20 seeded defects. I would not defend 124 as a quality metric — the rationale per rule is the point.</div></div>

<div class="qa"><div class="q"><span class="id">12</span>What does "graded, not gated" mean?</div><div class="a">Staging never filters. If it dropped the duplicate, the uniqueness rule would have nothing to count and the report would say the data is clean. Grading after the fact makes the report describe the source. (D020)</div></div>

<div class="qa"><div class="q"><span class="id">13</span>What is the intra-day ordering problem?</div><div class="a">The source has no time of day and trans_id is not chronological, so the closing posting of a busy day is ambiguous. I broke ties by the highest id and disclosed it. Later I found the running balance does record the order — each posting starts where the previous one ended — and the chain resolves 98.8% of cases. The honest part: I accepted "unknowable" without testing the chain. (L-01)</div></div>

<div class="qa"><div class="q"><span class="id">14</span>What was the most useful bug?</div><div class="a">The rule self-test nearly deleted real data: the quarantine view was not scoped by schema, so injected defects excluded real rows — 76 districts instead of 77. The model checks failed before any deliverable was written. Verify a model; do not trust a green build. (D008)</div></div>

## Model and SQL {#bank-model}

<div class="qa"><div class="q"><span class="id">15</span>Why a star schema with a bridge?</div><div class="a">The questions live at four grains; a disposition is many-to-many with a type. A wide table would turn every count into count(distinct), which generated SQL gets wrong quietly. Data Vault is for many sources with history; there is one source and one snapshot.</div></div>

<div class="qa"><div class="q"><span class="id">16</span>Explain v_account_owner.</div><div class="a">The one place that decides "the owner": the OWNER disposition, one per account. Q4, Q7, Q8 and the pre-joined ai.loan all go through it, so the definition cannot fork. Under RLS, for a disponent, the inner join to the filtered client dimension drops the owner — which is where the "no card" problem comes from. (L-06)</div></div>

<div class="qa"><div class="q"><span class="id">17</span>How is the month-end balance built, and is it right?</div><div class="a">One row per account per month end from the first posting month: the balance after the last posting in the month, carried forward with a flag when the month is empty. The average is robust; individual balances on busy closing days were not, because of the highest-id tie-break. (D019, L-01)</div></div>

<div class="qa"><div class="q"><span class="id">18</span>Why natural keys?</div><div class="a">One source, one extract, no history. Surrogates buy conformance and SCD tracking, which this data does not need; they would add a join per dimension and longer SQL for the model. With history: surrogates plus SCD2 on client, account and district. (D007)</div></div>

<div class="qa"><div class="q"><span class="id">19</span>Why is security_invoker on every view?</div><div class="a">Otherwise a view runs as its owner, who is exempt from the policies. That leaked once: ai.loan returned all 682 loans to a user entitled to none. A test now reads pg_class.reloptions and fails if any view between consumer and policy lacks it. (D010)</div></div>

## The ten questions {#bank-ten}

<div class="qa"><div class="q"><span class="id">20</span>Q1: which district, and what changes with the other one?</div><div class="a">The client's own district, all 5,369 clients. Places 3–5 are within four clients; owners only by account district, north Moravia passes south Moravia. Which one the business means depends on the use: marketing (where people live) or branch performance (where accounts are). Ask. (A1)</div></div>

<div class="qa"><div class="q"><span class="id">21</span>Q4: junior card owners borrow the most. Do you believe it?</div><div class="a">It is mechanically correct — 21 loans averaging 221,970 — but those owners average 17.4 years old at loan start. I would report it with n and the age caveat as a data artefact, not a finding.</div></div>

<div class="qa"><div class="q"><span class="id">22</span>Q5: does incoming include interest?</div><div class="a">Yes — PRIJEM includes the bank's interest credits. Excluding them keeps the same top ten in the same order; whether interest counts as incoming money is still a business decision. (A7)</div></div>

<div class="qa"><div class="q"><span class="id">23</span>Q9: what is account 31's balance at the end of November 1998?</div><div class="a">The delivered fact says 13,312.90 — the balance after interest. The 14.60 statement fee came after it in the chain, so the true closing balance is 13,298.30. That is the tie-break limitation, and it carries forward into December. (L-01)</div></div>

<div class="qa"><div class="q"><span class="id">24</span>Q10: is "after transaction" really riskier?</div><div class="a">Highest observed, not significant: 6 of 32 loans, interval 8.9–35.3%, Fisher p ≈ 0.16. I would say it is worth watching, not that it is riskier.</div></div>

<div class="qa"><div class="q"><span class="id">25</span>Which answer are you least confident in?</div><div class="a">Q10 (small n) and Q4 (an odd population) for interpretation; Q9 at account level, because of the tie-break.</div></div>

## Semantic layer, LLM and evaluation {#bank-llm}

<div class="qa"><div class="q"><span class="id">26</span>How do you know the LLM isn't just reading your answers?</div><div class="a">No reference figure is in the pack — a test asserts it — and the model had no database, no files and no tools. But the pack does tell it which entity answers which question; that shows it where to look, not what the answer is. A hold-out set is the remedy. (L-08)</div></div>

<div class="qa"><div class="q"><span class="id">27</span>Is 10/10 meaningful?</div><div class="a">It is a narrow pass: one sample per question, one key measure compared, questions known to the author of the layer, run on the earlier pack. It shows the layer is good enough for a strong model on these questions; it does not show generalisation. The local 3B model's 6/10 shows what weaker reasoning does with the same layer.</div></div>

<div class="qa"><div class="q"><span class="id">28</span>Does passing the guard mean the query is right?</div><div class="a">No. The guard proves a query is safe — one read-only SELECT on the governed surface, bounded in rows and time. It does not resolve columns or judge meaning. The gender question proved it: guard allowed, database rejected an unknown column. (L-07)</div></div>

<div class="qa"><div class="q"><span class="id">29</span>Why sqlglot rather than a regex?</div><div class="a">Comments, casing and string literals defeat string matching. SELECT/**/1; DROP TABLE x is one line to a regex and two statements to a parser.</div></div>

<div class="qa"><div class="q"><span class="id">30</span>What does the semantic validator catch?</div><div class="a">A described column that does not exist, an undescribed one, a false grain, a wrong join cardinality, a stale row count, and a metric naming a missing column. It does not check whether the model used the layer correctly — that is what intent verification adds. (D029)</div></div>

<div class="qa"><div class="q"><span class="id">31</span>What happens when a disponent asks Q4?</div><div class="a">Their one loan shows owner_card_type = 'no card' and a NULL frequency, because the owner is hidden by RLS and the view coalesces. The answer is wrong, not just restricted. The fix: no coalesce on hidden joins, or an explicit "not visible". (L-06)</div></div>

<div class="qa"><div class="q"><span class="id">32</span>Why run the LLM as cro_global?</div><div class="a">A portfolio of every client, so the answers are comparable with the reference — still through the policies (rolbypassrls = false). The same SQL as rm_north returns her slice.</div></div>

<div class="qa"><div class="q"><span class="id">33</span>Isn't 0.011 tolerance loose?</div><div class="a">It absorbs two-decimal rounding and nothing larger. A relative 1e-4 — the first version — would have accepted the top Q5 district wrong by 11,513 CZK. It did absorb one real difference I can name: Q7 status B, 39.61 vs 39.60, from rounding before averaging.</div></div>

## Entitlements and authentication {#bank-sec}

<div class="qa"><div class="q"><span class="id">34</span>Where does the filter sit, and why can't the LLM bypass it?</div><div class="a">Policies on the seven client-bearing core tables, evaluated as the caller through security-invoker views, keyed on session_user. The model emits text; the predicate is not in the text; no consumer has bypass or superuser. Nine bypass tests fail as they should.</div></div>

<div class="qa"><div class="q"><span class="id">35</span>Onboard a new relationship manager without code.</div><div class="a">Insert into sec.app_user and sec.user_portfolio, create the login role with its credential, enrol the TOTP factor. Grants are derived live, so access works immediately. Offboarding is one UPDATE. (D027)</div></div>

<div class="qa"><div class="q"><span class="id">36</span>Can a disponent see anything about the owner?</div><div class="a">The owner's client record, no. But the owner's card (type, issue date, holder id) and the owner's disposition row, yes — the card and disposition policies key on the account. The documents over-promise here; the fix is a holder-based policy on cards and own-row-only dispositions, with tests. (L-05)</div></div>

<div class="qa"><div class="q"><span class="id">37</span>How is the second factor enforced, and what are its limits?</div><div class="a">has_verified_session() is ANDed into the entitlement resolution; the verify function takes only a code and uses session_user; codes are single use; five committed failures lock for 15 minutes. Limits: a direct client can roll back failed guesses (found and disclosed at delivery), the session is bound to the backend PID only, secrets are stored recoverable, TOTP is phishable. (L-09, L-10)</div></div>

<div class="qa"><div class="q"><span class="id">38</span>A role per user does not pool. What then?</div><div class="a">A pool per role, or a trusted gateway that does SET ROLE on a privileged connection — the gateway, not the model, chooses the role. Identity then moves from session_user to current_user and the session binding from PID to a gateway token: a design change to plan and test.</div></div>

<div class="qa"><div class="q"><span class="id">39</span>What is missing for a real bank?</div><div class="a">A read audit log, column masking, secrets encrypted with an external key, joiner-mover-leaver automation, periodic access recertification from v_access_grant, and a break-glass procedure.</div></div>

<div class="qa"><div class="q"><span class="id">40</span>Is the public web demo secure?</div><div class="a">No, by design: it shows the one-time codes, personas share a password, there is no rate limit, and the process holds owner credentials for the tour pages. Acceptable only because Berka is public 1999 data, and labelled as a demo affordance.</div></div>

## Testing and operations {#bank-ops}

<div class="qa"><div class="q"><span class="id">41</span>How many tests, and what do they prove?</div><div class="a">At delivery the full suite passed with 327 passed and 1 skipped (the opt-in live-model test); the auth module 40 passed and 1 strict expected failure that records the rollback gap. Collected count 330. They prove rules fire, the model's grains and reconciliation hold, the guard refuses hostile SQL, RLS cannot be bypassed and the second factor is required. Older documents quote 137, 202 or 241. (L-14)</div></div>

<div class="qa"><div class="q"><span class="id">42</span>What is not tested?</div><div class="a">Disponent card and disposition visibility, RLS-induced NULL semantics, PID reuse, the who-can-reach NULL branch, repeated interest batches — and, in the delivered version, the tie-break against the balance chain and the meaning of generated SQL.</div></div>

<div class="qa"><div class="q"><span class="id">43</span>How do I reproduce it?</div><div class="a">make up && make all on Linux or Docker; scripts\windows.ps1 build on native Windows with a local PostgreSQL; make build runs everything except the LLM steps. The run log records every command with its commit.</div></div>

<div class="qa"><div class="q"><span class="id">44</span>Why did you not merge your later fixes into the delivery?</div><div class="a">Because they change a certified number (Q9) and the reference results, and a delivery freeze is the wrong moment to change a certified number without the business signing off the new rule. So the delivery discloses the limitation, and the fix sits on a branch with its tests and before/after evidence. (Lessons Learned, chapter 8)</div></div>

## When you do not know {#bank-unknown}

1. Say what you do know, with the evidence: "I measured X; I did not measure Y."
2. Say how you would find out: a concrete query or test.
3. Do not guess numbers. "I don't have that figure; the closest I have is …"
4. If it exposes a flaw, own it and give the fix and its cost.
