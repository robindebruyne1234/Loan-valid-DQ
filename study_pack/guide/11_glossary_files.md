# <span class="num">20</span>Glossary and where to find things {#glossary}

## Terms {#terms}

| Term | Meaning in this project |
|---|---|
| **Medallion (bronze / silver / gold)** | Layering by trust: verbatim (raw), typed and graded (stg + dq), modelled and published (core + ai) |
| **Grain** | What one row means ("one row per loan"). A false grain silently inflates every count |
| **Fan-out** | Joining to the "many" side of a relationship, which repeats rows and inflates sums and counts |
| **Disposition / owner / disponent** | The link between a client and an account. `OWNER` holds the account (exactly one per account); a `DISPONENT` may operate it but does not own it |
| **Quarantine** | Where a `block` row goes: excluded from core and the ai views, with a reason, reversible |
| **Flag** | A `warn` marker on a kept row (`dq.flags`, `_dq_flags`) that travels to the answer as a caveat |
| **Reconciliation** | Proof that a layer lost or invented nothing: counts and money sums compared between layers |
| **Semantic layer** | The YAML file of entities, grains, metrics, joins, glossary and caveats; validated against the database and rendered into the **context pack** the model reads |
| **Certified metric** | A metric defined once in the semantic layer (e.g. `problematic_loan_share`) that the model must use verbatim |
| **Row level security (RLS)** | A PostgreSQL policy that filters the rows a role may see, inside every statement's plan |
| **`security_invoker`** | A view option that evaluates the underlying policies as the *caller*, not as the view's owner |
| **`session_user`** | The role that authenticated the connection; cannot be changed by SQL without a password |
| **TOTP** | Time-based one-time password (RFC 6238), the second factor, verified inside the database |
| **Guard** | `src/sql_guard.py`: parses model SQL and enforces its *shape* (one read-only SELECT on `ai`, bounded) |
| **IR / intent verification** | (After delivery) the model states metric, periods, grouping and filters; the SQL is checked against that statement before and after execution |
| **Tie-break** | The rule that picks the closing posting when several share a date; delivered: highest `trans_id` |
| **Balance chain** | Each posting's opening balance is `balance_after − signed_amount`; postings of a day link into a chain whose end is the closing posting |
| **Value-based evaluation** | Comparing the numbers an answer contains, not its SQL text or column names |

## Codes worth knowing {#codes}

| Source code | Meaning |
|---|---|
| `PRIJEM` | Credit (incoming) |
| `VYDAJ`, `VYBER` | Debit (withdrawal); `VYBER` is not in the data description but is a debit |
| `UROK` | Interest credited (bank-generated; operation NULL) |
| `SANKC. UROK` | Sanction interest if negative balance |
| `SLUZBY` | Payment for statement (the fee) |
| `POPLATEK MESICNE` / `TYDNE` / `PO OBRATU` | Statement issued monthly / weekly / after each transaction |
| Loan status A / B / C / D | Finished paid / finished unpaid / running OK / running in debt — B and D are "problematic" |
| Birth number `YYMMDD` | Women carry month + 50 |

## Where to find things in the repository {#files}

| You need | Look in |
|---|---|
| Every claim and its evidence | `docs/DELIVERY_AUDIT.md` |
| The rules, severities and reasons | `dq/dq_rules.yaml`; last run: `dq/results/dq_report.md` |
| What the cleaning did, measured | `docs/CLEANING_LEDGER.md` |
| The model narrative and row counts | `deliverables/model_explanation.md` |
| The semantic layer / the text the model reads | `semantic/semantic_layer.yaml` / `semantic/context_pack.md` |
| The guard | `src/sql_guard.py` |
| The policies / authentication | `sql/50_sec_rls.sql` / `sql/51_sec_auth.sql` |
| Reference SQL and results | `sql/60_reference_queries.sql` / `dq/results/reference_results.json` |
| Claude's answers and the evaluation | `dq/results/llm_results.json`, `evaluation.json`, `llm_logs/` |
| The local model's run | `dq/results/local/`, `llm_logs/local/` |
| Decisions / assumptions | `DECISIONS.md` / `ASSUMPTIONS.md` |
| The AI disclosure | `AI_DISCLOSURE.md` |
| Security design | `docs/ACCESS_AND_AUTH.md`; one client end to end: `docs/WORKED_EXAMPLE.md` |
| Running it on Windows with Ollama | `docs/LOCAL_LLM_WINDOWS.md` |

:::key This study pack supersedes the older walkthrough prep
`docs/INTERVIEW_PREPARATION.md` was written before the delivery freeze and still quotes some
older figures (PostgreSQL 16 only, 241 tests). Where it and this pack differ, this pack has been
checked against the delivered commit.
:::
