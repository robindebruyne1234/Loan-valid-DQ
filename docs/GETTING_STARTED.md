# Getting started: running this yourself, from nothing

Written for someone on **Windows with WSL, Docker Desktop and VS Code**, who
has not seen this project before. No step is assumed. If a command needs
explaining, it is explained *before* you run it.

By the end you will have a bank's data cleaned on your own machine, a
database that refuses to show one customer another's finances, and a way to
poke at both yourself.

**Time:** about 20 minutes, most of it waiting.

---

## 0. The one-paragraph version of what this is

Eight text files from a real Czech bank (1999, public research data) go in.
They come out as a **cleaned, documented database** that an AI can be asked
questions about in English — where every person who connects sees only the
data they are entitled to, and has to pass two authentication steps to see
even that.

Three layers, and you will watch each one get built:

| Layer | Schema | What it holds |
|---|---|---|
| **Bronze** | `raw` | The files, landed as text, unchanged. Nothing cleaned. |
| **Silver** | `stg`, `dq` | Typed, decoded, derived — and every defect graded. |
| **Gold** | `core`, `ai`, `sec` | The business model, the AI-facing views, and who may see what. |

**Gold is what you will query.** The `ai.*` views are the clean, published
surface — that is "the gold data".

---

## 1. Install the four things you need

Open **Ubuntu (WSL)** from the Start menu. Everything below happens in that
terminal, not in Windows PowerShell.

### 1a. Check Docker reaches WSL

```bash
docker info
```

**Expected:** a wall of text about your Docker installation.

**If you get `command not found` or `Cannot connect to the Docker daemon`:**
open Docker Desktop on Windows → *Settings* → *Resources* → *WSL Integration*
→ turn it on for your Ubuntu distribution → *Apply & Restart*. Then close and
reopen the Ubuntu terminal and try again.

### 1b. Check your Python

```bash
python3 --version
```

**You need 3.11 or newer.** Ubuntu 24.04 ships 3.12 — fine. Ubuntu 22.04
ships 3.10, which is **too old**; install a newer one with:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update && sudo apt install -y python3.12 python3.12-venv
```

…and use `python3.12` wherever this guide says `python3`.

### 1c. Install the handful of system packages

```bash
sudo apt update
sudo apt install -y make git python3-venv python3-pip
```

- **make** — runs the project's commands. Not installed by default in WSL.
- **git** — to clone the repository.
- **python3-venv** — to make an isolated Python environment (see 2b).
- **python3-pip** — installs the Python libraries.

You do **not** need to install PostgreSQL. Docker provides it.

---

## 2. Get the code and set up Python

### 2a. Clone, in your Linux home directory

```bash
cd ~
git clone https://github.com/robindebruyne1234/Loan-valid-DQ.git
cd Loan-valid-DQ
git checkout ccr-46f6f45a-t9wtd4
```

> **Why `cd ~` and not a Windows folder?** WSL can reach your Windows drive at
> `/mnt/c/...`, but file access across that boundary is slow — enough to turn
> a four-minute build into fifteen. Keep the repository on the Linux side.

**Open it in VS Code** from that same terminal:

```bash
code .
```

The first time, VS Code installs a small server into WSL and reopens showing
**`WSL: Ubuntu`** in the bottom-left corner. If it does not say that, you are
editing Windows files through a slow bridge — close it and run `code .` from
the Ubuntu terminal again.

Useful VS Code extensions (optional): **Python**, **Even Better TOML**, and
**PostgreSQL** by Chris Kolkman if you want to browse the database by
clicking rather than typing.

### 2b. Make a virtual environment

A *virtual environment* is a private folder of Python libraries for this
project, so installing them cannot disturb anything else on your machine.
Recent Ubuntu **refuses** a system-wide install without one.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`. **You must run that `source` line again
in every new terminal** — it is the single most common thing to forget. If a
command later fails with `ModuleNotFoundError`, this is why.

### 2c. Install the Python libraries

```bash
make deps
```

**Expected last line:** `deps | installed into /home/you/Loan-valid-DQ/.venv`

Five libraries, and what each is for:

| Library | Why it is here |
|---|---|
| `psycopg` | talks to PostgreSQL |
| `PyYAML` | reads the quality rules and the semantic layer, both YAML |
| `sqlglot` | parses the SQL an AI writes, to check it before it runs |
| `openpyxl` | writes the Excel deliverable |
| `python-docx` | writes the Word deliverable |
| `pytest` (dev) | runs the 202 tests |

There is no lock file. The project pins minimum versions only, and has no
transitive pins to conflict — `make deps` on a fresh machine resolves cleanly.

---

## 3. Start the database

```bash
make up
```

**What it does:** starts a PostgreSQL 16 container called `berka_pg`, listening
on `localhost:5432`, with database `berka` owned by `berka_owner`
(password `berka_owner_pw` — a local demo credential, not a secret).

**Expected:**

```
db_up | docker daemon available -> using docker compose
[+] Running 2/2  ✔ Network ... ✔ Container berka_pg  Started
db_up | database ready -> localhost:5432/berka as berka_owner
db_up | berka_owner is a superuser, pg_read_all_stats not needed
```

Check it yourself any time with `docker ps` — you should see `berka_pg`.

> The data lives in a Docker volume, so it survives `make down` and restarts.
> To throw it away completely: `docker compose down -v`.

---

## 4. Build everything (except the AI step)

```bash
make build
```

**This takes about 4–6 minutes.** It is the one command that matters. Leave it
running and read the next section while it works.

**Expected final lines:**

```
202 passed in ...
build | done. The data product is built and the privacy model is live.
build | try:  make demo-login
```

### What just happened, step by step

Each of these is also a command you can run on its own:

| Step | Command | What it does | Watch for |
|---|---|---|---|
| 1 | `make ingest` | **Bronze.** Loads the 8 `.asc` files into schema `raw` as text, unchanged, recording a SHA-256 of each | `1,079,680 rows landed` |
| 2 | `make profile` | **Silver.** Builds `stg`: types every column, decodes Czech codes, derives birth date, gender and transaction sign | `tables=8` |
| 3 | `make dq` | **Silver.** Runs 124 quality rules, quarantines blockers, flags warnings | `rules fired : 19`, `rows quarantined : 1` |
| 4 | `make model` | **Gold.** Builds the star schema in `core`, then the `ai` views and the security on top | `code catalogue agrees with staging` |
| 5 | `make ledger` | Measures all 21 cleaning steps and writes `docs/CLEANING_LEDGER.md` | `0 probes failed` |
| 6 | `make reference` | Computes the 10 answers by hand-written SQL — the ground truth the AI is graded against | `all 10 reference answers computed` |
| 7 | `make semantic` | Renders the semantic layer into the text the AI will be given | `11 entities, 106 columns` |
| 8 | `make entitlements` | Creates the 8 logins, their second factors, the access grants and the 7 security policies | the `visible to ...` table |
| 9 | `make demo` | The worked example on one client → `docs/WORKED_EXAMPLE.md` | `attempts=13 blocked=13 leaked=0` |
| 10 | `make test` | 202 tests | `202 passed` |

If a step fails, run just that step again to see its output on its own.

---

## 5. See the privacy model (the point of all this)

```bash
make demo-login
```

Forty seconds, seven acts. `docs/DEMO_SCRIPT.md` is the full narration. The
three moments to actually look at:

1. **Act 1 vs Act 2** — two customers. Both show the *same* account
   (`CZ84 8888 0000 0000 0000 3112`), because one is authorised to operate the
   other's account. But their client lists differ: she sees herself, he sees
   himself. **He can use her account and cannot see her.**

2. **Act 3** — one customer asking for another's data by name. Look at the two
   different refusals. `refused (privilege)` means the statement was blocked.
   `0 rows (policy)` means the statement **ran** and the database had already
   narrowed the answer. The second is why an AI can be allowed to write
   queries.

3. **Act 5** — the administrator, who can see all 5,369 clients, with the
   correct password and no second factor: **0 clients, 0 accounts, 0 rows.**
   Then with the code: 5,369. That is the two-factor control doing its job.

### Drive it yourself

```bash
make demo-interactive
```

Pick a persona by number, type the code it shows you, then type SQL as that
person. Try these:

```sql
SELECT count(*) FROM ai.client;                     -- how much can I see?
SELECT * FROM ai.my_entitlement;                    -- who am I, and why?
SELECT * FROM ai.client WHERE client_id = 3763;     -- ask for someone else
SELECT count(*) FROM core.fact_transaction;         -- go around the views
SELECT count(*) FROM stg.trans;                     -- try the uncleaned copy
```

Log in as `client_11409` and run the third one: you get nothing. Log in as
`rm_north` and run it: you get a row. Same query, same database.

Type `back` to pick another persona, `q` to quit.

---

## 6. Looking at the clean gold data directly

This is the part that makes it stop being a black box.

### What "gold" actually is

Eleven views in the `ai` schema. These are the cleaned, business-named,
entitlement-filtered surface — the only thing the AI is ever shown:

| View | Rows | What it is |
|---|---|---|
| `ai.client` | 5,369 | one per customer: birth date, gender, district, their reference |
| `ai.account` | 4,500 | one per account, with its IBAN-style number |
| `ai.account_owner` | 4,500 | account joined to its owner — the join you'd otherwise get wrong |
| `ai.loan` | 682 | one per loan, with `is_problematic` already decided |
| `ai.transaction` | 1,056,319 | one per posting, with `signed_amount` already signed |
| `ai.account_month_end_balance` | 185,615 | balance per account per month end |
| `ai.card` | 892 | issued cards |
| `ai.district` | 77 | reference data, not filtered |
| `ai.calendar` | 2,191 | every day 1993–1998 |
| `ai.code_reference` | 28 | what each Czech code means |
| `ai.my_entitlement` | 1 | who you are and what you may see |

### Connect and look

The simplest way, with no extra software — from the repo folder, with `.venv`
active:

```bash
python3 -c "
from src import db
with db.connect() as c:
    for r in db.fetch_all(c, '''
        SELECT client_id, client_ref, gender, birth_date, region
        FROM ai.client ORDER BY client_id LIMIT 5'''):
        print(r)
"
```

> Connecting this way uses the **owner** identity, which is exempt from the
> security policies — that is how the nightly build is able to write the
> tables. It is the right way to *inspect* the data and the wrong way to
> demonstrate privacy. For that, use `make demo-interactive`, which logs in as
> a real restricted user.

### Prefer a GUI?

In VS Code install the **PostgreSQL** extension and add a connection:

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `berka` |
| User | `berka_owner` |
| Password | `berka_owner_pw` |

Browse to `berka → Schemas → ai` and you will see the eleven views.

Or use `psql` inside the container, no install needed:

```bash
docker exec -it berka_pg psql -U berka_owner -d berka
```

Then `\dn` lists schemas, `\dv ai.*` lists the gold views, `\d ai.client`
describes one, and `\q` quits.

### See the cleaning for yourself

The single most convincing query — the same row, before and after:

```bash
docker exec -it berka_pg psql -U berka_owner -d berka -c "
SELECT 'RAW  ' AS layer, birth_number AS value, NULL AS derived_1, NULL AS derived_2
FROM raw.client WHERE client_id = '11409'
UNION ALL
SELECT 'CLEAN', birth_number, birth_date::text, gender
FROM stg.client WHERE client_id = 11409;"
```

`805502` becomes `1980-05-02` and `female` — one field that held two facts,
because in the Czech birth number the month carries +50 for women. The
original digits stay in the row, so the derivation can be checked rather than
trusted.

Every one of the 21 cleaning steps is listed, with its measured effect, in
`docs/CLEANING_LEDGER.md`.

---

## 7. The AI step

Everything so far needed no AI. This part does, and you have three options.

### What actually happens

1. `make semantic` already rendered `semantic/context_pack.md` — the entity
   list, grains, metric definitions and data-quality caveats. **This is the
   only thing the model is given.** It never sees the database.
2. The model is asked a question in English and replies with SQL.
3. `src/sql_guard.py` parses that SQL and rejects anything that is not a
   single read-only `SELECT` against the `ai` schema.
4. The SQL runs on a connection authenticated as a real consumer — two
   factors — so the policies apply to whatever it wrote.
5. `make evaluate` compares the answer to the hand-written one from step 6.

### Option A — an Anthropic API key (easiest)

```bash
export LLM_PROVIDER=anthropic_api
export LLM_API_KEY=sk-ant-...        # from console.anthropic.com
make questions
make evaluate
```

Ten questions, ten calls. Costs a few cents.

### Option B — a local model with Ollama (free, no key)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen2.5-coder:7b
make questions
```

Needs ~8 GB of RAM. A smaller model will get fewer of the ten right — which
is itself informative, and the evaluation will tell you exactly which.

### Option C — skip it

You do not need the AI to see anything else. `make build` deliberately stops
before this step. The questions, the generated SQL and the results from the
run on my machine are already in
`deliverables/Berka_TakeHome_Submission.xlsx` (tabs **Questions** and
**Q detail**) and in `llm_logs/` as one JSON file per call, with the prompt,
the model, the parameters and the raw response.

> **If you set no provider**, `make questions` writes `NOT EXECUTED` into every
> cell rather than inventing an answer, and exits non-zero. That is deliberate:
> a fabricated AI result would be worse than no result.

### Then the deliverables

```bash
make deliverables     # Excel, Word/PDF decision record, and the ZIP
```

The PDF conversion needs LibreOffice (`sudo apt install -y libreoffice`). The
Excel and ZIP work without it.

---

## 8. Where everything lives

```
Loan-valid-DQ/
├── data/raw/            the 8 source files, committed (18 MB) — nothing to download
├── sql/                 numbered SQL, in execution order
│   ├── 00_schemas.sql       the seven schemas
│   ├── 10_stg.sql           SILVER: typing, decoding, deriving
│   ├── 30_core.sql          GOLD: the star schema
│   ├── 40_ai_views.sql      GOLD: the AI-facing views
│   ├── 50_sec_rls.sql       who may see what: the policies
│   └── 51_sec_auth.sql      two-factor login and the access grants
├── src/                 Python that orchestrates the SQL
│   ├── config.py            every shared constant. Start here.
│   ├── auth.py              the two-step login
│   ├── demo_console.py      make demo-login
│   └── worked_example.py    make demo
├── dq/dq_rules.yaml     the 89 hand-written quality rules
├── semantic/            what the AI is told about the data
├── tests/               202 tests
├── docs/                all the explanation, including this file
└── deliverables/        the Excel, the decision record, the deck, the ZIP
```

**If you read three files:** `src/config.py` (every setting in one place),
`sql/10_stg.sql` (the cleaning, with the reasoning in comments), and
`sql/51_sec_auth.sql` (the privacy model).

**If you read three documents:** `docs/CLEANING_LEDGER.md` (what was cleaned,
measured), `docs/WORKED_EXAMPLE.md` (one client all the way through), and
`docs/ACCESS_AND_AUTH.md` (the privacy design).

---

## 9. When something goes wrong

| What you see | What it means | Fix |
|---|---|---|
| `make: command not found` | make is not installed | `sudo apt install -y make` |
| `ModuleNotFoundError: No module named 'psycopg'` | the virtual environment is not active | `source .venv/bin/activate` |
| `deps \| You are not in a Python virtual environment` | same | as above, then `make deps` |
| `Cannot connect to the Docker daemon` | Docker Desktop is off, or WSL integration is off | start Docker Desktop → Settings → Resources → WSL Integration |
| `connection refused` on port 5432 | the database container is not running | `make up`, then `docker ps` |
| `database did not become ready in time` | the container is starting, or failed | `docker compose logs db` |
| `no second factor enrolled` | a login exists but has no authenticator | `make entitlements` |
| `code already used` | two logins as the same person within 30 seconds | wait 30 seconds — this is the replay protection working |
| `locked until HH:MM` | five wrong codes in a row | `make entitlements` resets the counters |
| A persona sees 0 rows when it should see some | security was rebuilt without the model | `make model` then `make entitlements` |
| `NOT EXECUTED` in the Questions tab | no LLM provider configured | section 7, or ignore it |
| Everything is empty | the pipeline has not run here | `make build` |
| You want to start completely over | | `docker compose down -v && make up && make build` |

**Nothing you can do here is destructive.** The source files are read-only
inputs; every schema is rebuilt from them by `make build`. If the database
gets into a state you do not understand, throw it away and rebuild — it takes
five minutes.

---

## 10. A sensible first hour

1. `make up && make build` — watch it go past.
2. `make demo-login` — read Act 5 twice.
3. `make demo-interactive` — log in as `client_11409`, try to read client
   3763, watch it come back empty. Then log in as `rm_north` and read the same
   row successfully.
4. Open `docs/WORKED_EXAMPLE.md` — one client from a line of text to a
   published row, with the output of a real run.
5. Open `docs/CLEANING_LEDGER.md` — the 21 cleaning steps, each with a number
   measured at build time.
6. Break something on purpose: in `src/config.py` change
   `EXAMPLE_CLIENT_ID` to another client id, re-run `make demo`, and see the
   whole worked example follow a different person.
