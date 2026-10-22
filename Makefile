# Berka governed data product -- one command to stand it up, one to run it.
#
#   make up    : start PostgreSQL 16 (docker compose, or a native cluster)
#   make all   : run the whole pipeline end to end and rebuild every deliverable
#
# Every target is idempotent: re-running it rebuilds from the raw files.

PY ?= python3
PYTHONPATH := $(CURDIR)
export PYTHONPATH

.DEFAULT_GOAL := help
.PHONY: help up down deps ingest profile dq model reference semantic questions \
        entitlements evaluate workbook ddr zip deliverables test all clean status

help:  ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

deps:  ## Install the Python dependencies
	$(PY) -m pip install --quiet -e ".[dev]"

up:  ## Start PostgreSQL 16 (docker compose if available, else a native cluster)
	@bash scripts/db_up.sh

down:  ## Stop the database (docker compose only; a native cluster is left running)
	@docker compose down 2>/dev/null || echo "down | no docker compose stack to stop"

ingest:  ## Load the raw .asc files verbatim into schema raw, with a load audit
	$(PY) -m src.ingest

profile:  ## Build schema stg and profile every column
	$(PY) -m src.profile_data

dq:  ## Run every data quality rule, quarantine blockers, write the defect report
	$(PY) -m src.dq_runner

model:  ## Build the core star schema, then restore the ai views that depend on it
	$(PY) -m src.build_model
	@# Rebuilding core drops its dependent views (CASCADE), so the ai surface
	@# and its row level security policies are re-applied here. Without this,
	@# `make model` on its own leaves the consumer surface missing.
	$(PY) -m src.build_security

reference:  ## Run the hand-written reference queries and store the ground truth
	$(PY) -m src.run_reference

semantic:  ## Render the semantic layer into the LLM context pack
	$(PY) -m src.semantic_context --write

entitlements:  ## Apply row level security, roles and the entitlement tables
	$(PY) -m src.build_security

questions:  ## Ask the LLM the 10 questions through the semantic layer
	$(PY) -m src.run_questions

evaluate:  ## Compare LLM answers against the reference answers
	$(PY) -m src.evaluate

workbook:  ## Build the Excel submission workbook
	$(PY) -m src.make_workbook

ddr:  ## Build the Design Decision Record (docx + pdf) and check the page count
	$(PY) -m src.make_ddr

zip:  ## Package the semantic solution and code as a ZIP
	$(PY) -m src.make_zip

deliverables: workbook ddr zip  ## Build every deliverable

status:  ## Write STATUS_REPORT.md from the run log
	$(PY) -m src.make_status

test:  ## Run the test suite
	$(PY) -m pytest

all: up ingest profile dq model reference semantic entitlements questions evaluate test deliverables status  ## Full pipeline
	@echo "all | pipeline complete -> see deliverables/ and STATUS_REPORT.md"

clean:  ## Drop every project schema (raw stays on disk, nothing is lost)
	$(PY) -m src.ingest --drop-all
