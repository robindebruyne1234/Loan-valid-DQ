#!/usr/bin/env bash
# Explain, and stop, when `make deps` is run outside a virtual environment.
#
# Recent Debian and Ubuntu mark the system Python as externally managed
# (PEP 668), so a system-wide `pip install` fails with a wall of text that
# does not say what to do. This says what to do.
cat <<'MSG'

deps | You are not in a Python virtual environment.
deps |
deps | Recent Ubuntu and Debian refuse a system-wide pip install (PEP 668).
deps | Create an environment for this project first:
deps |
deps |     python3 -m venv .venv
deps |     source .venv/bin/activate
deps |     make deps
deps |
deps | You will need to run the `source` line again in every new terminal.
deps | Your prompt shows (.venv) when it is active.
deps |
deps | In a disposable container where a system install is fine:
deps |
deps |     ALLOW_SYSTEM_PIP=1 make deps

MSG
exit 1
