<div class="cheat" markdown="1">

<div class="cheat-head"><b>Cheat sheet</b> — Berka governed data product · delivered version <code>fc0c281</code> (branch <code>delivery-freeze-2026-10-28</code>), 2026-10-28 · 45-minute walkthrough: ~30 min talk, 15 min questions</div>

<div class="cheat-grid" markdown="1">
<div markdown="1">

### The story in 30 seconds
The AI assistant is a **dumb and dangerous client**: it guesses at anything the data does not spell out, and its SQL runs against customer data. So every layer removes a reason to guess or a way to do harm. Land verbatim → convert without repairing → grade every defect with a consequence → one definition per term in a star schema → a semantic layer the build validates → SQL parsed and bounded → runs on the user's own two-factor session, where **RLS on the base tables** decides which rows exist. The filter is not in the query, so the model cannot remove it.

### Six layers
<div class="mini-layers"><span class="l-raw">raw</span><span class="l-stg">stg</span><span class="l-dq">dq</span><span class="l-core">core</span><span class="l-ai">ai</span><span class="l-sec">sec</span></div>

raw verbatim + SHA-256 · stg typed, decoded, **nothing filtered** · dq 124 rules, quarantine, flags · core star = stg − quarantine · ai 11 security-invoker views · sec grants, TOTP, 7 policies

### Numbers
| | |
|---|---|
| Source | 8 files · **1,079,680** rows (trans 1,056,320 · client 5,369 · disp 5,369 · account 4,500 · card 892 · loan 682 · order 6,471 · district 77) |
| Rules | **124** (89 hand + 35 sweep) · 19 fire (1 block, 6 warn, 12 info) · **14** defect types |
| Outcome | **1** row quarantined (0.00 CZK duplicate) · **440** warn flags on 352 rows · 20 seeded defects all caught |
| Recon | raw = stg 11 checks · core = stg − quarantine 9 checks (trans 6,257,793,560.30; loans 103,261,740.00) |
| Model | 4 source dims + calendar · 1 bridge · 2 facts · month-end fact 185,615 rows (558 carried) · 3 curated views |
| Semantic | 11 entities · 105 columns · 19 joins · 12 metrics · 7 caveats · 12 query rules · pack 33,662 chars |
| Access | cro_global 5,369 · rm_north 1,481 · rm_south 1,387 (1,386 + 1 delegated) · rm_unassigned **0** · client_3764 1 |
| LLM | Claude Sonnet 5.5 **10/10** first attempt (2026-10-25, old 29,500-char pack) · Ollama qwen2.5-coder:3b 6 / 2 / 2 |
| Tests | **327 passed, 1 skipped**; auth 40 + 1 strict xfail; 330 collected · DDR 2 pages · workbook 11 tabs · ZIP 183 |

### Task 3 in three sentences
**Where:** 7 RLS policies on the 7 client-bearing core tables; every view in between is `security_invoker`. **Why no bypass:** the predicate is not in the model's text, and identity is `session_user` (needs a password the model never sees); no consumer has BYPASSRLS. **Onboarding:** insert principal + portfolio, create role, enrol TOTP — grants derive live; offboarding is one UPDATE.

### The LLM defence
Isolation (no tools, no DB, one turn) · semantic layer (meaning) · **guard = shape only** (1 read-only SELECT on ai, no out-of-schema functions, LIMIT ≤ 10,000) · envelope (read-only txn, 60 s timeout, cap+1 rows) · **RLS = rows** · DB rejects unknown names · evaluation (value-based, abs tol 0.011) after the fact.

</div>
<div markdown="1">

### The ten answers
| Q | Delivered answer |
|---|---|
| 1 | south Moravia 937, north Moravia 920 … (client's own district, all 5,369) |
| 2 | 1993 2.62 m (half year) … 1997 30.73 m peak … total 103,261,740 |
| 3 | 76 / 682 = **11.14%** (B 31, D 45); 15.09% by value |
| 4 | junior 221,970 (n = 21, owners ~17 yrs) · gold 161,881 · no card 148,865 · classic 148,809 |
| 5 | Praha 115.13 m · Karvina 28.51 m · Ostrava 27.69 m … (credits, account district) |
| 6 | Jan 106 … Jul 137 … Dec 125; total 1,363 (calendar-driven) |
| 7 | A 37.07 · B 39.60 · C 38.70 · D 37.00 (exact age; Claude B 39.61 — rounding) |
| 8 | male 53 (60.23%) · female 35 (39.77%) |
| 9 | **43,808.94** over 4,500 (76 carried forward) — not 43,810.47 |
| 10 | after transaction 18.75% (6/32, not significant) · weekly 12.09% · monthly 10.55% |

### Decisions in one line
D002 PostgreSQL: RLS makes Task 3 real · D004 seed defects in a separate schema · D009 filter in the engine, identity = session_user · D010 every view security_invoker · D011 sandboxed LLM, value-based evaluation · D013 never repair in place · D017 one code map, code kept beside label · D018 sign resolved once (VYBER is a debit) · D019 month-end decided once (tie-break = weak spot) · D020 graded, not gated · D024 a disposition grants the account, never the person · D026 2FA enforced by the database · D027 derive grants, store only human decisions

### Raise these yourself
1. **Tie-break** (L-01, L-02): highest id right 0.4%; the "1,200 CZK missing posting" was its artefact; Q9 +1.53 after fix
2. **Guard ≠ meaning** (L-07): the `T2.gender` query passed the guard, failed in the DB; intent check added after
3. **10/10 is narrow** (L-08): old pack, Q-labels in the pack, no hold-out, one sample
4. **Disponent** (L-05, L-06): sees owner's card; hidden → "no card"
5. **Scope** (L-19): tasks first; cut deployment guide → agents → web page

### Awaiting business confirmation
A4 problematic = B or D · A7 interest is incoming · A19 CZK only · calendar (not fiscal) quarters · the 1,081 repeated interest groups

### Never say
"Passing the guard means it's correct" · "a person hand-wrote the references" · "the disponent sees nothing of the owner" · "no derived table can resolve intra-day order" · "241 tests"

### Before you walk in
PostgreSQL service up · `scripts\windows.ps1 test` green · delegation valid (`SELECT valid_to FROM sec.access_delegation`; re-run `entitlements` if near 10–11 Nov) · Ollama warmed up · `docs/DELIVERY_AUDIT.md` open

</div>
</div>
</div>
