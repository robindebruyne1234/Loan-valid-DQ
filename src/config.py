"""Central configuration for the Berka governed data product.

Every shared constant used anywhere in this project is defined here and
imported from here: filesystem paths, database connection defaults, schema
names, date bounds, severity labels, reference row counts, the raw file
layout and the code-to-business-label decode maps.

Nothing in this module reads the database or the filesystem at import time,
so it is safe to import from tests, from the pipeline and from the
documentation generators alike.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------

#: Repository root, derived from the location of this file (``src/config.py``).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

BRIEF_DIR: Path = PROJECT_ROOT / "brief"
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
PROVIDED_DIR: Path = DATA_DIR / "raw" / "provided"
SQL_DIR: Path = PROJECT_ROOT / "sql"
SRC_DIR: Path = PROJECT_ROOT / "src"
SEMANTIC_DIR: Path = PROJECT_ROOT / "semantic"
DQ_DIR: Path = PROJECT_ROOT / "dq"
DQ_RESULTS_DIR: Path = DQ_DIR / "results"
TESTS_DIR: Path = PROJECT_ROOT / "tests"
DELIVERABLES_DIR: Path = PROJECT_ROOT / "deliverables"
LLM_LOG_DIR: Path = PROJECT_ROOT / "llm_logs"

QUESTIONS_CSV: Path = DATA_DIR / "questions.csv"
DQ_RULES_YAML: Path = DQ_DIR / "dq_rules.yaml"
SEMANTIC_LAYER_YAML: Path = SEMANTIC_DIR / "semantic_layer.yaml"
PROMPT_TEMPLATE_MD: Path = SEMANTIC_DIR / "prompt_template.md"

PROFILE_MD: Path = DQ_RESULTS_DIR / "profile.md"
PROFILE_JSON: Path = DQ_RESULTS_DIR / "profile.json"
CANDIDATES_MD: Path = DQ_RESULTS_DIR / "candidates.md"
DQ_REPORT_MD: Path = DQ_RESULTS_DIR / "dq_report.md"
REFERENCE_RESULTS_JSON: Path = DQ_RESULTS_DIR / "reference_results.json"
LLM_RESULTS_JSON: Path = DQ_RESULTS_DIR / "llm_results.json"
EVALUATION_JSON: Path = DQ_RESULTS_DIR / "evaluation.json"
RUN_LOG_JSONL: Path = DQ_RESULTS_DIR / "run_log.jsonl"

DEFECTS_CSV: Path = DELIVERABLES_DIR / "defects.csv"
MODEL_EXPLANATION_MD: Path = DELIVERABLES_DIR / "model_explanation.md"
WORKBOOK_XLSX: Path = DELIVERABLES_DIR / "Berka_TakeHome_Submission.xlsx"
DDR_DOCX: Path = DELIVERABLES_DIR / "DDR.docx"
DDR_PDF: Path = DELIVERABLES_DIR / "DDR.pdf"
SEMANTIC_ZIP: Path = DELIVERABLES_DIR / "semantic_solution.zip"
STATUS_REPORT_MD: Path = PROJECT_ROOT / "STATUS_REPORT.md"

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

#: PostgreSQL host. Overridable with ``PGHOST`` for a containerised database.
PGHOST: str = os.environ.get("PGHOST", "localhost")
PGPORT: int = int(os.environ.get("PGPORT", "5432"))
PGDATABASE: str = os.environ.get("PGDATABASE", "berka")

#: Owner / ETL role. Owns every object and runs the pipeline.
PGUSER: str = os.environ.get("PGUSER", "berka_owner")
PGPASSWORD: str = os.environ.get("PGPASSWORD", "berka_owner_pw")

#: Role the AI consumer uses. Holds SELECT on the ``ai`` schema only and is
#: subject to row level security, so it can never read unentitled rows.
AI_CONSUMER_ROLE: str = os.environ.get("AI_CONSUMER_ROLE", "ai_consumer")

#: Demo end-user login roles, created by ``sql/50_sec_rls.sql``. Each one
#: inherits ``ai_consumer`` and is mapped to a portfolio in ``sec.app_user``.
DEMO_USER_PASSWORD: str = os.environ.get("DEMO_USER_PASSWORD", "demo_pw")
DEMO_USERS: tuple[str, ...] = (
    "rm_north",
    "rm_south",
    "cro_global",
    "rm_unassigned",
    "client_11409",
    "client_3763",
    "client_3764",
    "admin_demo",
)

# ---------------------------------------------------------------------------
# External identifiers and authentication
# ---------------------------------------------------------------------------

#: Secret salt for the opaque external references (``client_ref``). Derived
#: references are deterministic under a given salt and unguessable without it,
#: so changing the salt reissues every reference -- which is the intended
#: behaviour if one is ever believed to have leaked. The default is a
#: development value and is NOT a secret; a deployment sets BERKA_REF_SALT.
REF_SALT: str = os.environ.get("BERKA_REF_SALT", "berka-dev-salt-not-a-secret")

#: Four-digit bank code used in the IBAN-shaped ``account_ref``. Deliberately
#: fictional: this is public research data and must not carry a real bank's
#: routing code. The check digits around it are genuine ISO 13616.
BANK_CODE: str = os.environ.get("BERKA_BANK_CODE", "8888")

#: Time-based one-time password settings (RFC 6238). Thirty seconds is the
#: universal default and is what an authenticator app assumes; the window of
#: 1 accepts the adjacent steps, which covers ordinary clock drift.
TOTP_DIGITS: int = 6
TOTP_PERIOD_SECONDS: int = 30
TOTP_WINDOW_STEPS: int = 1

#: How long a fully authenticated session stays valid before the second factor
#: must be presented again. Short on purpose: the session is a bearer secret.
SESSION_TTL_MINUTES: int = int(os.environ.get("BERKA_SESSION_TTL_MINUTES", "30"))

#: Self-service customer logins: ``(db_role, client_id)``. These are the second
#: grain of principal -- a principal that IS one client rather than one that
#: HOLDS a book of clients. Both are chosen deliberately from north Bohemia, so
#: both sit inside ``rm_north``'s portfolio: the sharpest test of the model is
#: that two customers of the SAME relationship manager still cannot see each
#: other. See :mod:`src.worked_example` and DECISIONS.md D021.
DEMO_CLIENT_USERS: tuple[tuple[str, int], ...] = (
    ("client_11409", 11409),
    ("client_3763", 3763),
    # Client 3764 owns nothing. They are a DISPONENT on account 3112, which
    # client 3763 owns -- a real relationship in the source data, and the
    # reason the demo can show "may operate an account they do not own"
    # without inventing anything.
    ("client_3764", 3764),
)

#: The disponent persona and the account they may operate but do not own.
EXAMPLE_DISPONENT_CLIENT_ID: int = 3764
EXAMPLE_SHARED_ACCOUNT_ID: int = 3112

#: The client the end-to-end worked example follows, chosen because it carries
#: a data quality flag of its own and its account carries a different one, so
#: the caveats are visible all the way through to the answer.
EXAMPLE_CLIENT_ID: int = 11409

#: A second client, in the same relationship manager's book, used as the
#: negative control: everything the example client can see, this one must not.
EXAMPLE_OTHER_CLIENT_ID: int = 3763

SCHEMA_RAW: str = "raw"
SCHEMA_STG: str = "stg"
SCHEMA_DQ: str = "dq"
SCHEMA_CORE: str = "core"
SCHEMA_AI: str = "ai"
SCHEMA_SEC: str = "sec"

#: Schema holding the deliberately corrupted copy used to prove that every
#: data quality rule family actually fires. Never feeds ``core``.
SCHEMA_INJECT: str = "inject"

ALL_SCHEMAS: tuple[str, ...] = (
    SCHEMA_RAW,
    SCHEMA_STG,
    SCHEMA_DQ,
    SCHEMA_CORE,
    SCHEMA_AI,
    SCHEMA_SEC,
)


def dsn(user: str | None = None, password: str | None = None, database: str | None = None) -> str:
    """Build a libpq connection string.

    :param user: Login role. Defaults to the owner role :data:`PGUSER`.
    :param password: Password for ``user``. Defaults to :data:`PGPASSWORD`
        when ``user`` is omitted, otherwise :data:`DEMO_USER_PASSWORD`.
    :param database: Database name. Defaults to :data:`PGDATABASE`.
    :returns: A keyword/value libpq connection string.
    """
    if user is None:
        user = PGUSER
        password = PGPASSWORD if password is None else password
    elif password is None:
        password = DEMO_USER_PASSWORD
    database = database or PGDATABASE
    return (
        f"host={PGHOST} port={PGPORT} dbname={database} "
        f"user={user} password={password} application_name=berka_dp"
    )


# ---------------------------------------------------------------------------
# Date handling and validity bounds
# ---------------------------------------------------------------------------

#: All source dates are ``YYMMDD`` strings from the 1990s; the loader prefixes
#: this century. The dataset ends in 1998, so no 20xx interpretation applies.
CENTURY_PREFIX: int = 1900

#: Inclusive plausibility window for every business date in the dataset.
#: Used by the validity rules and by ``core.dim_date``.
DATA_MIN_DATE: date = date(1993, 1, 1)
DATA_MAX_DATE: date = date(1998, 12, 31)

#: Earliest plausible client birth date. Anything older is implausible for a
#: living bank client in 1999 and is reported by the validity rules.
MIN_BIRTH_DATE: date = date(1900, 1, 1)

#: Plausible age window, in years, for an account owner at account opening
#: and at loan start.
MIN_AGE_AT_EVENT: int = 15
MAX_AGE_AT_EVENT: int = 100

#: Reporting reference date for Q9 (average closing balance at month end).
Q9_AS_OF_DATE: date = date(1998, 12, 31)
Q5_YEAR: int = 1997
Q6_YEAR: int = 1996

#: Tolerance for the ``payments * duration ~= amount`` cross-table check,
#: expressed as a relative difference.
PAYMENT_SCHEDULE_TOLERANCE: float = 0.01

#: Absolute tolerance, in CZK, for the running balance continuity check.
BALANCE_CONTINUITY_TOLERANCE: float = 0.01

# ---------------------------------------------------------------------------
# Severity framework
# ---------------------------------------------------------------------------

#: The defect breaks a key, a join path or a certified metric. Offending rows
#: are quarantined and never reach the ``ai`` schema.
SEVERITY_BLOCK: str = "block"

#: The row stays usable but carries a flag, and the semantic layer attaches a
#: caveat to every metric that touches it.
SEVERITY_WARN: str = "warn"

#: Cosmetic, or irrelevant to the certified metrics. Standardise and log.
SEVERITY_INFO: str = "info"

SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_BLOCK: 0,
    SEVERITY_WARN: 1,
    SEVERITY_INFO: 2,
}

VALID_SEVERITIES: tuple[str, ...] = (SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO)

#: Data quality dimensions every rule must declare.
VALID_DIMENSIONS: tuple[str, ...] = (
    "completeness",
    "uniqueness",
    "referential_integrity",
    "validity",
    "consistency",
    "reconciliation",
)

#: Placeholder strings that mean "missing" in the source files.
NULL_PLACEHOLDERS: tuple[str, ...] = ("", "?", "NA", "N/A", "NULL", "-", "unknown")

# ---------------------------------------------------------------------------
# Raw file layout
# ---------------------------------------------------------------------------

#: Field separator of the PKDD'99 ``.asc`` files.
RAW_DELIMITER: str = ";"

#: Source table name -> (file name, ordered column list). Column names are the
#: original PKDD'99 names. ``district`` keeps its ``A1..A16`` codes in ``raw``
#: and is renamed in ``stg``.
RAW_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "account": ("account.asc", ("account_id", "district_id", "frequency", "date")),
    "client": ("client.asc", ("client_id", "birth_number", "district_id")),
    "disp": ("disp.asc", ("disp_id", "client_id", "account_id", "type")),
    "card": ("card.asc", ("card_id", "disp_id", "type", "issued")),
    "loan": (
        "loan.asc",
        ("loan_id", "account_id", "date", "amount", "duration", "payments", "status"),
    ),
    "order": (
        "order.asc",
        ("order_id", "account_id", "bank_to", "account_to", "amount", "k_symbol"),
    ),
    "trans": (
        "trans.asc",
        (
            "trans_id",
            "account_id",
            "date",
            "type",
            "operation",
            "amount",
            "balance",
            "k_symbol",
            "bank",
            "account",
        ),
    ),
    "district": (
        "district.asc",
        (
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "A9",
            "A10",
            "A11",
            "A12",
            "A13",
            "A14",
            "A15",
            "A16",
        ),
    ),
}

#: Business column names for the ``district`` table, positionally aligned with
#: the ``A1..A16`` codes above.
DISTRICT_COLUMN_MAP: dict[str, str] = {
    "A1": "district_id",
    "A2": "district_name",
    "A3": "region",
    "A4": "inhabitants",
    "A5": "municipalities_lt_499",
    "A6": "municipalities_500_1999",
    "A7": "municipalities_2000_9999",
    "A8": "municipalities_gt_10000",
    "A9": "cities",
    "A10": "urban_ratio_pct",
    "A11": "average_salary",
    "A12": "unemployment_rate_1995",
    "A13": "unemployment_rate_1996",
    "A14": "entrepreneurs_per_1000",
    "A15": "crimes_1995",
    "A16": "crimes_1996",
}

#: Row counts of the authentic public PKDD'99 copy, used as an ingest gate.
REFERENCE_ROW_COUNTS: dict[str, int] = {
    "account": 4500,
    "client": 5369,
    "disp": 5369,
    "card": 892,
    "loan": 682,
    "order": 6471,
    "trans": 1056320,
    "district": 77,
}

#: Published cross-check figures for the public copy.
REFERENCE_PROBLEMATIC_LOANS: int = 76
REFERENCE_PROBLEMATIC_LOAN_PCT: float = 11.14

# ---------------------------------------------------------------------------
# Code decode maps (single source of truth, mirrored into core.ref_codes
# and into semantic/semantic_layer.yaml by the build)
# ---------------------------------------------------------------------------

FREQUENCY_CODES: dict[str, str] = {
    "POPLATEK MESICNE": "monthly",
    "POPLATEK TYDNE": "weekly",
    "POPLATEK PO OBRATU": "after transaction",
}

LOAN_STATUS_CODES: dict[str, str] = {
    "A": "finished, paid in full",
    "B": "finished, unpaid (default)",
    "C": "running, no problem",
    "D": "running, client in debt",
}

#: Loan statuses treated as problematic for Q3 and Q10.
PROBLEMATIC_LOAN_STATUSES: tuple[str, ...] = ("B", "D")

CARD_TYPE_CODES: dict[str, str] = {
    "junior": "junior",
    "classic": "classic",
    "gold": "gold",
}

#: Label used in Q4 for loans whose account owner holds no card at all.
NO_CARD_LABEL: str = "no card"

DISP_TYPE_CODES: dict[str, str] = {
    "OWNER": "owner",
    "DISPONENT": "disponent",
}

TRANS_TYPE_CODES: dict[str, str] = {
    "PRIJEM": "credit",
    "VYDAJ": "debit",
    "VYBER": "withdrawal (legacy debit)",
}

#: Transaction types that increase the balance. Everything else decreases it.
CREDIT_TRANS_TYPES: tuple[str, ...] = ("PRIJEM",)
DEBIT_TRANS_TYPES: tuple[str, ...] = ("VYDAJ", "VYBER")

TRANS_OPERATION_CODES: dict[str, str] = {
    "VKLAD": "cash deposit",
    "VYBER": "cash withdrawal",
    "VYBER KARTOU": "credit card withdrawal",
    "PREVOD Z UCTU": "collection from another bank",
    "PREVOD NA UCET": "remittance to another bank",
}

#: The k_symbol code set, as the SOURCE uses it. The column appears on both
#: ``trans`` and ``order``, and the union of the two is what belongs here --
#: LEASING occurs only on standing orders, never on a posting. What each
#: published entity may actually contain is narrower, and is stated per entity
#: in semantic/semantic_layer.yaml. See DECISIONS.md D017.
K_SYMBOL_CODES: dict[str, str] = {
    "POJISTNE": "insurance payment",
    "SLUZBY": "payment for statement",
    "UROK": "interest credited",
    "SANKC. UROK": "sanction interest for negative balance",
    "SIPO": "household payment",
    "DUCHOD": "old age pension",
    "UVER": "loan payment",
    "LEASING": "leasing payment",
}

#: Gender derived from ``birth_number``: women carry month + 50.
GENDER_MALE: str = "male"
GENDER_FEMALE: str = "female"

#: Allowed loan durations, in months, as published with the dataset.
VALID_LOAN_DURATIONS: tuple[int, ...] = (12, 24, 36, 48, 60)

# ---------------------------------------------------------------------------
# Questions and LLM access
# ---------------------------------------------------------------------------

QUESTION_IDS: tuple[str, ...] = tuple(f"Q{i}" for i in range(1, 11))

#: LLM provider: ``claude_cli`` (default, uses the local authenticated Claude
#: Code CLI as a plain text completion endpoint), ``anthropic_api``,
#: ``ollama`` or ``none`` (export the prompt pack without executing).
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "claude_cli")

#: Model used for each provider when ``LLM_MODEL`` is not set, so choosing
#: ``LLM_PROVIDER=ollama`` alone never sends a Claude model name to Ollama.
LLM_DEFAULT_MODELS: dict[str, str] = {
    "claude_cli": "claude-sonnet-5-5",
    "anthropic_api": "claude-sonnet-5-5",
    "ollama": "qwen2.5-coder:3b",
}
LLM_MODEL: str = os.environ.get("LLM_MODEL") or LLM_DEFAULT_MODELS.get(
    LLM_PROVIDER, LLM_DEFAULT_MODELS["claude_cli"])
LLM_API_KEY_ENV: str = "LLM_API_KEY"
LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", "0.0"))
LLM_TIMEOUT_SECONDS: int = int(os.environ.get("LLM_TIMEOUT_SECONDS", "300"))


def _http_url(value: str) -> str:
    """Turn an Ollama address into a URL a client can call.

    Ollama's own server reads ``OLLAMA_HOST`` as a bind address, usually
    without a scheme (``0.0.0.0:11434``). The same variable therefore arrives
    here in either form, and a bind-all address is not something to connect to.

    :param value: ``host:port`` or a full URL.
    :returns: An ``http(s)://host:port`` URL without a trailing slash.
    """
    url = value.strip().rstrip("/")
    if "://" not in url:
        url = f"http://{url}"
    return url.replace("://0.0.0.0", "://127.0.0.1")


#: Ollama endpoint. 127.0.0.1 rather than localhost: on Windows ``localhost``
#: tries ::1 first, and a refused IPv6 connection costs about two seconds
#: before the IPv4 attempt that Ollama actually listens on.
OLLAMA_HOST: str = _http_url(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))

#: Context window requested from Ollama, in tokens. Set explicitly because
#: Ollama's default is a few thousand tokens and the semantic layer alone is
#: larger: an unset window silently drops the start of the prompt.
OLLAMA_NUM_CTX: int = int(os.environ.get("OLLAMA_NUM_CTX", "12288"))

#: Maximum tokens the model may generate for one answer.
OLLAMA_NUM_PREDICT: int = int(os.environ.get("OLLAMA_NUM_PREDICT", "1024"))

#: How long Ollama keeps the model, and the evaluated semantic layer, in
#: memory after a call. Long enough that a walkthrough does not pay the load
#: and the prompt evaluation again for every question.
OLLAMA_KEEP_ALIVE: str = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

#: Model layers Ollama may place on a GPU. Unset lets Ollama decide; ``0``
#: keeps the model on the CPU. Measured on a laptop with a 2 GB GeForce MX150:
#: Ollama's Vulkan backend loaded the model once, then misreported the card
#: as having 6.9 GiB free and crashed on every later load. CPU-only was stable.
OLLAMA_NUM_GPU: int | None = (int(os.environ["OLLAMA_NUM_GPU"])
                              if os.environ.get("OLLAMA_NUM_GPU", "").strip() else None)

#: Marker written into deliverables when a step could not be executed.
NOT_EXECUTED: str = "NOT EXECUTED"

# ---------------------------------------------------------------------------
# SQL guard
# ---------------------------------------------------------------------------

#: Schema an LLM-generated query may reference. Anything else is rejected
#: before execution.
GUARD_ALLOWED_SCHEMAS: tuple[str, ...] = (SCHEMA_AI,)

#: Statement types the guard accepts. One statement, read only.
GUARD_ALLOWED_STATEMENTS: tuple[str, ...] = ("SELECT",)

#: Hard row cap applied to every guarded query.
GUARD_MAX_ROWS: int = 10000

#: Statement timeout, in milliseconds, applied to every guarded query.
GUARD_STATEMENT_TIMEOUT_MS: int = 60000

LOG_FORMAT: str = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
