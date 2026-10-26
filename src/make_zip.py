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
    ("docs", "*.md"),
    ("web", "*"),
    ("docs/diagrams", "*"),
    # Next-step material: the three layer agents and the simulation that
    # exercises their boundary. Clearly labelled as such in the manifest --
    # none of it is part of the assessed pipeline.
    (".claude/agents", "*.md"),
    ("tests/agentsim", "*.py"),
    ("packages/berka_control/src/berka_control", "*"),
    ("packages/berka_bronze/src/berka_bronze", "*.py"),
    ("packages/berka_silver/src/berka_silver", "*.py"),
    ("packages/berka_gold/src/berka_gold", "*.py"),
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
    # scripts/simulate_agents.py is already covered by the ("scripts", "*")
    # tree above; listing it here as well wrote it into the archive twice.
    "packages/berka_control/pyproject.toml",
    "packages/berka_bronze/pyproject.toml",
    "packages/berka_silver/pyproject.toml",
    "packages/berka_gold/pyproject.toml",
)

MANIFEST_TEMPLATE = """\
# semantic_solution.zip -- what is in here and where to start

This archive is the "semantic solution and any code/agents" deliverable for the
Berka take-home. It is a snapshot of the repository minus the raw data files
(17 MB of public PKDD'99 data; README.md says where to get them) and minus the
Excel workbook, which is a separate deliverable.

## Read in this order

1. `README.md` -- what was built, how to run it, and what the results were.
   `docs/GETTING_STARTED.md` if you want to run it yourself from nothing.
2. `docs/DEMO_SCRIPT.md` -- how to show the privacy model to stakeholders in
   fifteen minutes: what to run, what to point at, and the questions to
   expect. Driven by `make demo-login`; `make web` is the same story as a
   page you click through, and `docs/DEPLOYMENT.md` puts that page on a
   free-tier host behind TLS.
3. `docs/ACCESS_AND_AUTH.md` -- the design behind it: three kinds of
   identifier, four sources of access (ownership, disposition, portfolio,
   delegation) and two factors enforced by the database rather than by an
   application. Figures 11 and 12.
4. `docs/WORKED_EXAMPLE.md` -- one client followed from the line of text she
   arrives as, through the cleaning, into the product, and then through the
   entitlement model. Written by `make demo`, so the output is executed.
5. `docs/CLEANING_LEDGER.md` -- **what the cleaning actually did**: every
   transformation between the source file and the product, with its effect
   measured by a probe run against the database at build time, where the
   original value survives, and which rule watches it. `DECISIONS.md`
   D013-D020 is the reasoning behind each choice.
6. `docs/GOLD_LAYER.md` -- what is modelled today, what is cleaned and
   consumed by nothing, and the eight tables the cleaned data will carry with
   no new source file.
7. `docs/VISUAL_GUIDE.md` -- the figures: the pipeline, the query path, what
   each severity does, the star schema, two decision comparisons, the defect
   lifecycle and catalogue, the system map, the build sequence, the access
   model and the two-step login.
8. `semantic/semantic_layer.yaml` -- **the semantic solution**: the single
   source of business meaning. Entities with their grain, certified metric
   definitions, a glossary that says what each word is NOT, the data quality
   caveats with row counts, and the traps each question contains.
9. `semantic/context_pack.md` -- that file rendered into the exact text the LLM
   received. Nothing else was in its context.
10. `semantic/prompt_template.md` -- the prompt around it.
11. `src/sql_guard.py` -- what happens to the SQL the model produces before it
   is allowed to run.
12. `sql/50_sec_rls.sql` and `sql/51_sec_auth.sql` -- the entitlement model,
   the row level security policies, the access grant set and the two-factor
   machinery (Task 3).
13. `dq/dq_rules.yaml` -- the {rule_count} hand-written data quality rules, each
   with its severity and the reason for that severity (Task 1).
14. `llm_logs/` -- one JSON file per model call: prompt, model, parameters, raw
   response, timing and cost. This is the evidence behind the Questions tab.
15. `dq/results/` -- the profile, the candidate defects, the data quality report,
   the reference answers, the LLM answers and the evaluation.

## Not part of the assessed pipeline

`packages/`, `.claude/agents/`, `tests/agentsim/`, `scripts/simulate_agents.py`
and `docs/MEDALLION_REFACTOR.md` are **next-step material**, included because
they show where this would go rather than what was built for the assessment.
They are a simulation of three layer-owning agents (bronze, silver, gold) over
an isolated-package split, run against a small control dataset. No production
code was refactored for them and no agent was triggered; `make all` does not
touch them. Run them with `make simulate`.

## Layout

```
docs/         the cleaning ledger, the gold layer analysis, the visual
              guide and the diagram sources and renders
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
make up        # PostgreSQL 16 (docker compose, or a native cluster)
make all       # the whole pipeline, about 4.5 minutes
make test      # the test suite
make simulate  # the next-step agent simulation (no database needed)
```
"""


def render_manifest() -> str:
    """Render the manifest, reading the rule count rather than stating it.

    :returns: The manifest text.
    """
    import yaml

    rules = yaml.safe_load(config.DQ_RULES_YAML.read_text(encoding="utf-8"))["rules"]
    return MANIFEST_TEMPLATE.format(rule_count=len(rules))


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
        archive.writestr("MANIFEST.md", render_manifest())
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
