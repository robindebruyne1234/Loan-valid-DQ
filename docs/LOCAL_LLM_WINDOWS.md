# Step 7 on a local model, on Windows

Step 7 of the walkthrough ("Ask") puts a question to a language model and runs
the SQL it writes as the persona you logged in as. On Windows this now runs on
a **local model through Ollama**: no API key, no paid inference, nothing leaves
the machine. The Claude providers are still there; set `LLM_PROVIDER` to use
them.

What did not change: the pipeline, the semantic layer, the reference answers,
authentication and row level security. The model still sees only the semantic
layer and the question, never the database, and never who is asking.

## From a clean machine

You need Python 3.11+, PostgreSQL running as a Windows service, and this
repository. From the repository root, in PowerShell:

```powershell
# 1. Python environment and dependencies
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 setup

# 2. Database role and database (asks for the postgres superuser password once)
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 init-db

# 3. Load, clean, grade, model and secure the data; runs the test suite (~7 min)
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 build

# 4. The local runtime (per-user install, no administrator rights needed)
winget install --id Ollama.Ollama -e --source winget

# 5. The model, about 1.9 GB
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 llm-pull

# 6. Is it ready? Then load it and its semantic layer before anyone asks
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 llm-check
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 llm-warm

# 7. The walkthrough: log in on step 6, ask on step 7
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 web-open
```

Ollama starts with Windows after installation and serves on
`http://127.0.0.1:11434`. If `llm-check` says it is not reachable, start the
Ollama app from the Start menu.

To measure the model against the reference answers:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 questions-local
powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 evaluate-local
```

These write to `dq\results\local\` and `llm_logs\local\`. They never touch
`dq\results\llm_results.json`, `evaluation.json` or `llm_logs\Q*.json`: those
are the recorded Claude run that the workbook, the DDR and the submission ZIP
are built from. In local mode, plain `questions` refuses to run for that
reason.

## Configuration

All settings are environment variables, read by `src/config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` on Windows (`claude_cli` elsewhere) | `ollama`, `claude_cli`, `anthropic_api` or `none` |
| `LLM_MODEL` | the provider's own: `qwen2.5-coder:3b` for Ollama | model tag |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | also accepts Ollama's own `host:port` form |
| `OLLAMA_NUM_CTX` | `16384` | context window in tokens; the prompt is ~9,400 (about 36,000 characters) |
| `OLLAMA_NUM_PREDICT` | `1024` | longest answer, in tokens |
| `OLLAMA_KEEP_ALIVE` | `30m` | how long the model and its cached semantic layer stay loaded |
| `OLLAMA_NUM_GPU` | `0` on Windows (unset elsewhere) | model layers on the GPU: `0` is CPU only, `-1` lets Ollama decide |
| `LLM_TIMEOUT_SECONDS` | `900` on Windows with Ollama (`300` elsewhere) | per call |

`scripts\windows.ps1` sets `LLM_PROVIDER`, `LLM_TIMEOUT_SECONDS` and
`OLLAMA_NUM_GPU` only when you have not.

## When it fails

Every failure is reported on the page, in the call log and in the question
run as a typed `error_kind`. Nothing is invented in its place.

| `error_kind` | What happened | What to do |
|---|---|---|
| `runtime_unavailable` | nothing answers at `OLLAMA_HOST` | start the Ollama app, or `ollama serve` |
| `model_missing` | Ollama has no such model | `scripts\windows.ps1 llm-pull` |
| `timeout` | no answer within `LLM_TIMEOUT_SECONDS` | warm up first (`llm-warm`), or raise the timeout |
| `context_overflow` | the prompt does not fit, or Ollama dropped part of it | raise `OLLAMA_NUM_CTX` |
| `output_truncated` | the answer hit `OLLAMA_NUM_PREDICT` | raise `OLLAMA_NUM_PREDICT` |
| `empty_response` | the model returned nothing | retry; try another model |
| `malformed_output` | not the JSON object asked for (page stage `parse`) | a model limitation; the question runner retries once |
| `http_error`, `malformed_response` | Ollama itself failed | the message carries Ollama's own error |

`context_overflow` deserves its reason. Measured on Ollama 0.40.11: given a
window smaller than the prompt, Ollama returns HTTP 200, evaluates only part
of the prompt (1,026 of 7,979 tokens), and the model still answers with
fluent, plausible SQL — written without most of the semantic layer. So the
prompt is sized before it is sent, and an answer whose evaluated token count
is implausibly low for its prompt is refused.

## What the model can and cannot do

The model writes one SQL string. It does not choose who runs it, and it cannot
run anything itself.

* **Identity.** `/api/ask` requires a session from the two-step login on step
  6. A request naming a persona instead of carrying a session is refused (it
  used to be accepted). The SQL runs on that persona's own two-factor login;
  the model is never told who is asking.
* **The guard** (`src/sql_guard.py`) allows one read-only `SELECT` on the `ai`
  schema, bounded to 10,000 rows and 60 seconds. Three gaps were found and
  closed while adding this provider, each now with tests:
  * a CTE named like a real table (`WITH dim_client AS (...) SELECT * FROM
    core.dim_client`) skipped the schema check;
  * a function called through a schema (`sec.end_session()`,
    `FROM sec.verify_second_factor(...)`) was not checked at all;
  * a limit the model wrote (`LIMIT 100000000`, `LIMIT ALL`, `FETCH FIRST`)
    was kept, so the row cap held only for models that forgot to write one.
* **Under the guard**, nothing changed and nothing needed to: the statement
  runs in a read-only transaction, as a role with no write privileges, through
  row level security. Before the fixes, every bypass above was still stopped
  or filtered by the database — the guard gaps were defence-in-depth failures,
  not data leaks.

## Measured on this machine

Intel i7-8550U (4 cores, 15 W), 16 GB RAM, NVIDIA MX150 (2 GB), Ollama
0.40.11, `qwen2.5-coder:3b` (Q4_K_M, 1.9 GB on disk).

**Why CPU only.** Left to decide, Ollama first split the model 43% CPU / 57%
GPU through its Vulkan backend and ran it. After the model was unloaded,
every reload saw the 2 GB card reporting 6.9 GiB free and the model runner
crashed (`llama-server ... exit status 0xe06d7363`). The page reported each
crash as `http_error` with Ollama's message, as it should. With
`num_gpu = 0` the model loaded and answered every time, so that is the
default on Windows. Set `OLLAMA_NUM_GPU=-1` to try the GPU on a machine
where it works.

| | GPU split, cold | GPU split, warm | **CPU only, cold** | **CPU only, warm** |
|---|---|---|---|---|
| Model load | 15.2 s | 0.0 s | | |
| Prompt evaluation (7,979 tokens) | 224.9 s | 4.8 s | | |
| Generation | 33.3 s (125 tokens) | 59.7 s (218 tokens) | | |
| **Total model time** | 273.6 s | 64.7 s | **436.5 s** | **85.1 s** |

The CPU-only figures are the web page's own timings, from the live check
below. Warm, the semantic layer is reused from Ollama's cache and nearly all
the time is the model writing at a few tokens per second, mostly its
`reasoning` field. Run `llm-warm` before a demo so nobody waits seven
minutes for the first answer. The guard and the database add milliseconds;
the two-factor login can add up to 30 seconds when the persona's one-time
code for the current window was just spent on the login step.

**Live, through the page's API** (real server, real model, real logins,
CPU only), the same question asked by two personas:

| Persona | Model's SQL | Guard | Rows returned |
|---|---|---|---|
| `client_3763` (a customer) | `SELECT region, COUNT(*) AS client_count FROM ai.client GROUP BY region` | allowed, limit 10,000 added | 1: north Bohemia, 1 (herself) |
| `rm_north` (her relationship manager) | the same | allowed, limit 10,000 added | 2: north Bohemia 561, north Moravia 920 |

The model wrote the same SQL for both; row level security decided what each
of them saw.

### The ten questions, measured

`questions-local` then `evaluate-local`, 2026-10-27, with the GPU split
(before the reload crashes), executed as `cro_global`
(entitled to every client, so totals are comparable with the reference). The
verdict is the existing value-based evaluator against the hand-written
reference answers, which were not changed. Model time is per question,
including a retry where there was one; the database time is the final
attempt's guarded query.

| | Verdict | Attempts | Model time | Guard | Database | What went wrong |
|---|---|---|---|---|---|---|
| Q1 | match 8/8 | 1 | 35.0 s | allowed | 0.05 s | |
| Q2 | match 6/6 | 1 | 51.9 s | allowed | 0.23 s | |
| Q3 | partial 1/3 | 1 | 62.3 s | allowed | 0.26 s | right share (11.14%), but omits the 76 problematic of 682 loans the reference also reports |
| Q4 | match 4/4 | 1 | 78.6 s | allowed | 0.63 s | |
| Q5 | match 10/10, order ok | 2 | 322.1 s | allowed | 1.00 s | first attempt referenced an alias it never defined; the database refused it, the retry was right |
| Q6 | mismatch 0/12 | 1 | 49.2 s | allowed | 0.16 s | joined `open_date = month_start`, so it counted only accounts opened on a 1st, across every year |
| Q7 | partial 1/4 | 1 | 100.4 s | allowed | 0.25 s | grouped by age instead of averaging it: 650 rows instead of 4 |
| Q8 | match 2/2 | 1 | 78.7 s | allowed | 0.20 s | |
| Q9 | match 1/1 | 1 | 101.8 s | allowed | 0.21 s | |
| Q10 | mismatch 0/3 | 2 | 176.7 s | allowed | 0.42 s | ranked by problematic COUNT, not share, so it named `monthly` (the largest group) instead of `after transaction` |

**6 match, 2 partial, 2 mismatch.** All ten produced SQL in the agreed shape,
passed the guard and ran; two needed the retry after a database error. The
recorded Claude Sonnet run on the same prompt matches 10 of 10. Every miss
above is a reasoning error about the business question, not a formatting
or safety failure. Q6 and Q10 are the dangerous kind: plausible-looking
numbers that are wrong. That is what the evaluation exists to catch, and
why a small local model's answers are a demonstration of the access
controls, not a source of figures.

Total for the ten: 17 minutes 46 seconds, almost all of it generation.

This run used the semantic pack of commit `5b13f2b` (29,500 characters). The
semantic audit has since grown the pack to about 33,700 characters, and the
default `OLLAMA_NUM_CTX` was raised from 12,288 to 16,384 so it fits: at the old
value every question was refused as `context_overflow`. On the grown pack the
opt-in live test (`BERKA_LIVE_LLM=1`, one question) passed on 2026-10-28 in
9.5 minutes on the CPU: the model answered in contract and its SQL ran as the
persona. The ten were not re-run on the grown pack, so the table above is the
older pack's result.

## Limitations

* **Quality.** A 3-billion-parameter model reading an 8,400-token semantic
  layer is the weakest part of this pipeline. Its answers are measured against
  the hand-written reference answers, not trusted.
* **Speed.** About a minute and a half per warm answer on this laptop's CPU,
  seven minutes cold. One question is answered at a time; a second visitor
  waits. A CPU-only rerun of the ten questions would take roughly 25 minutes;
  answers at temperature 0 should not depend on CPU versus GPU, but that
  rerun was not done.
* **Licence.** `qwen2.5-coder:3b` is published under the Qwen Research
  License, which does not permit commercial use. The 1.5B and 7B variants are
  Apache 2.0; the 7B needs about 5.5 GB of free memory.
* **The size check is an estimate.** A prompt is refused if it could exceed
  the window at 3 characters per token (this prompt measures 3.85). Text with
  far fewer characters per token could still slip past the check before the
  call; the check after the call then catches a large truncation, not a
  small one.
* **The Claude CLI on Windows** was not tested here (it is not installed). It
  passes the whole prompt on the command line, which may exceed Windows'
  command-line limit; that is a hypothesis, not a finding.
