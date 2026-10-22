"""Package the semantic solution and the code into a single ZIP.

The brief asks for "Semantic solution and any code/agents: ZIP file". This
builds it from the repository, with a manifest so a reviewer who opens the ZIP
without the repository can still tell what each file is and in what order to
read it.

Deliberately included: the semantic layer and the rendered context pack, all
the SQL, all the Python, the rule set, the prompt template, the LLM call logs
(the evidence behind the Questions tab), the results and the documentation.

Deliberately excluded: the 17 MB of raw data (it is public and the README says
where to get it), the virtual environment, caches and the workbook itself,
which is a separate deliverable.

Run with ``make zip``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from src import config, db

LOGGER = db.setup_logging("zip")

#: Directories copied whole, with the glob applied inside them.
INCLUDE_TREES: tuple[tuple[str, str], ...] = (
    ("semantic", "*"),
    ("sql", "*.sql"),
    ("src", "*.py"),
    ("tests", "*.py"),
    ("dq", "dq_rules.yaml"),
    ("dq/results", "*"),
    ("llm_logs", "*.json"),
    ("scripts", "*"),
)

#: Individual files at the repository root.
INCLUDE_FILES: tuple[str, ...] = (
    "README.md",
    "PLAN.md",
    "DECISIONS.md",
    "ASSUMPTIONS.md",
    "AI_DISCLOSURE.md",
    "WALKTHROUGH_NOTES.md",
    "STATUS_REPORT.md",
    "Makefile",
    "docker-compose.yml",
    "pyproject.toml",
    "data/questions.csv",
    "deliverables/defects.csv",
    "deliverables/model_explanation.md",
)

MANIFEST = """\
# semantic_solution.zip -- what is in here and where to start

This archive is the "semantic solution and any code/agents" deliverable for the
Berka take-home. It is a snapshot of the repository minus the raw data files
(17 MB of public PKDD'99 data; README.md says where to get them) and minus the
Excel workbook, which is a separate deliverable.

## Read in this order

1. `README.md` -- what was built, how to run it, and what the results were.
2. `semantic/semantic_layer.yaml` -- **the semantic solution**: the single
   source of business meaning. Entities with their grain, certified metric
   definitions, a glossary that says what each word is NOT, the data quality
   caveats with row counts, and the traps each question contains.
3. `semantic/context_pack.md` -- that file rendered into the exact text the LLM
   received. Nothing else was in its context.
4. `semantic/prompt_template.md` -- the prompt around it.
5. `src/sql_guard.py` -- what happens to the SQL the model produces before it
   is allowed to run.
6. `sql/50_sec_rls.sql` -- the entitlement model and the row level security
   policies (Task 3).
7. `dq/dq_rules.yaml` -- the 88 hand-written data quality rules, each with its
   severity and the reason for that severity (Task 1).
8. `llm_logs/` -- one JSON file per model call: prompt, model, parameters, raw
   response, timing and cost. This is the evidence behind the Questions tab.
9. `dq/results/` -- the profile, the candidate defects, the data quality report,
   the reference answers, the LLM answers and the evaluation.

## Layout

```
semantic/     the semantic layer, the rendered context pack, the prompt
sql/          numbered SQL, in execution order (00 schemas .. 70 defect injector)
src/          Python orchestration; src/config.py holds every shared constant
tests/        the test suite, including the row level security bypass attempts
dq/           the rule set and every result it produced
llm_logs/     one audited record per LLM call
deliverables/ defects.csv and the model explanation
```

## To run it

```
make up     # PostgreSQL 16 (docker compose, or a native cluster)
make all    # the whole pipeline, about 6 minutes
make test   # the test suite
```
"""


def collect() -> list[tuple[Path, str]]:
    """Collect the files to archive.

    :returns: List of (absolute path, name inside the archive) pairs.
    """
    entries: list[tuple[Path, str]] = []
    for directory, pattern in INCLUDE_TREES:
        base = config.PROJECT_ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.glob(pattern)):
            if path.is_file() and "__pycache__" not in path.parts:
                entries.append((path, str(path.relative_to(config.PROJECT_ROOT))))
    for name in INCLUDE_FILES:
        path = config.PROJECT_ROOT / name
        if path.is_file():
            entries.append((path, name))
    return entries


def main() -> int:
    """Build ``deliverables/semantic_solution.zip``.

    :returns: Process exit code, ``0`` on success.
    """
    entries = collect()
    config.DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(config.SEMANTIC_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("MANIFEST.md", MANIFEST)
        for path, name in entries:
            archive.write(path, name)

    size_kb = config.SEMANTIC_ZIP.stat().st_size / 1024
    LOGGER.info(
        "wrote %s -> %d files, %.0f KB",
        config.SEMANTIC_ZIP.relative_to(config.PROJECT_ROOT),
        len(entries) + 1,
        size_kb,
    )
    db.record_run("zip", "make zip", {"files": len(entries) + 1, "size_kb": round(size_kb, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
