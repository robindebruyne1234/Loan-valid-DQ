"""Build deliverables/Setup_Workbook.xlsx: the steps to run the app locally.

A checklist you work down, not a document you read. One command per cell, so
each can be copied without dragging a selection across prose; and for every
step the output you should see, because "it ran" and "it worked" are not the
same thing and a newcomer cannot tell them apart without being shown.

Generated rather than typed so it cannot drift from the repo: the port, the
make targets and the test count are read from the project, not remembered.

Usage: python scripts/make_setup_workbook.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TARGET = ROOT / "deliverables" / "Setup_Workbook.xlsx"

NAVY, GREY, PALE = "1F3864", "5B6472", "F7F9FC"
HEAD = PatternFill("solid", fgColor=NAVY)
BAND = PatternFill("solid", fgColor=PALE)
CODE = PatternFill("solid", fgColor="EEF2F8")
WARN = PatternFill("solid", fgColor="FFF4E0")
OK = PatternFill("solid", fgColor="E8F5EC")
THIN = Side(style="thin", color="DDE3ED")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
MONO = Font(name="Consolas", size=10.5)


def makefile_targets() -> set[str]:
    """Read the make targets that actually exist.

    :returns: Target names declared with a ``##`` description.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-zA-Z_-]+):.*?## ", text, flags=re.M))


def test_count() -> int:
    """Count the tests by asking pytest, not by remembering.

    :returns: Number of collected tests.
    """
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return sum(int(n) for n in re.findall(r":\s(\d+)$", out, flags=re.M))


def title(ws, text: str, sub: str, width: int) -> int:
    """Write a sheet title and a one-line purpose.

    :param ws: Worksheet.
    :param text: Title.
    :param sub: What this sheet is for.
    :param width: Number of columns to merge across.
    :returns: Next free row.
    """
    ws.cell(row=1, column=1, value=text).font = Font(bold=True, size=15, color=NAVY)
    ws.cell(row=2, column=1, value=sub).font = Font(italic=True, size=10.5, color=GREY)
    ws.cell(row=2, column=1).alignment = WRAP
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    ws.row_dimensions[2].height = 34
    return 4


def header(ws, row: int, labels: list[str]) -> None:
    """Write a header row.

    :param ws: Worksheet.
    :param row: Row number.
    :param labels: Column headings.
    :returns: ``None``.
    """
    for col, label in enumerate(labels, 1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill, cell.alignment, cell.border = HEAD, WRAP, BOX


def widths(ws, sizes: list[int]) -> None:
    """Set column widths.

    :param ws: Worksheet.
    :param sizes: Width per column.
    :returns: ``None``.
    """
    for col, size in enumerate(sizes, 1):
        ws.column_dimensions[chr(64 + col)].width = size


def steps_sheet(wb: Workbook, name: str, heading: str, purpose: str,
                rows: list[tuple[str, str, str, str]], start_no: int) -> int:
    """Write a checklist sheet.

    :param wb: Workbook.
    :param name: Sheet name.
    :param heading: Title.
    :param purpose: One-line purpose.
    :param rows: ``(what, command, expect, if_not)`` per step. An empty command
        marks a step done in a browser or by hand.
    :param start_no: Number of the first step, so numbering runs across sheets.
    :returns: The next step number.
    """
    ws = wb.create_sheet(name)
    widths(ws, [7, 8, 38, 58, 50, 46])
    row = title(ws, heading, purpose, 6)
    header(ws, row, ["Step", "Done", "What you are doing", "Command (copy this cell)",
                     "You should see", "If you do not"])
    dv = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(dv)
    n = start_no
    for what, command, expect, if_not in rows:
        row += 1
        values = [n, "", what, command, expect, if_not]
        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.alignment, cell.border = WRAP, BOX
            if (n - start_no) % 2:
                cell.fill = BAND
        ws.cell(row=row, column=1).font = Font(bold=True, color=NAVY)
        if command:
            ws.cell(row=row, column=4).font = MONO
            ws.cell(row=row, column=4).fill = CODE
        dv.add(ws.cell(row=row, column=2))
        ws.row_dimensions[row].height = max(34, 17 * max(
            len(command.splitlines()) or 1,
            -(-len(expect) // 48), -(-len(if_not) // 44), -(-len(what) // 34)))
        n += 1
    ws.freeze_panes = ws.cell(row=5, column=1)
    return n


def build() -> Workbook:
    """Assemble the workbook.

    :returns: The workbook.
    """
    targets = makefile_targets()
    for needed in ("deps", "up", "build", "web", "web-open", "demo-login", "test"):
        assert needed in targets, f"the workbook promises `make {needed}` but it does not exist"
    tests = test_count()

    wb = Workbook()
    ws = wb.active
    ws.title = "Start here"
    widths(ws, [30, 96])
    row = title(ws, "Run the governed data product on your own machine",
                "Work down the numbered tabs. Each step has the command, what you should see, "
                "and what to do if you do not. About 20 minutes, most of it waiting.", 2)

    facts = [
        ("What you end up with",
         "A web page at http://localhost:8080 that walks through seven steps: the raw text the "
         "bank sends, what cleaning does to it, how defects are graded, the published model, who "
         "may read it and why, a two-step login, and a real question answered under the "
         "entitlement filter."),
        ("Works on", "Windows with WSL2, macOS, or Linux (tabs 1-4). Native Windows without WSL "
                     "or Docker, using a locally installed PostgreSQL and PowerShell: see the "
                     "“Windows native” tab instead of tabs 1-4."),
        ("You need installed", "Docker Desktop (runs the database) · Python 3.11 or newer · "
                               "git · make. Tab 1 checks each and tells you how to fix a miss."),
        ("You do NOT need", "PostgreSQL installed (Docker provides it) · any data download (the "
                            "18 MB of source files are in the repository) · an API key (only "
                            "the last step, asking questions, uses a model; everything before "
                            "it runs without one)."),
        ("The command, once set up", "make up   then   make web-open"),
        ("Where to type commands",
         "WSL route: the Ubuntu app, not PowerShell. Every command in tabs 1-5 is for that "
         "terminal. Native route: PowerShell (or the VS Code terminal), commands in the "
         "“Windows native” tab only."),
        ("How long", "Install ~10 min · first build ~6 min · after that, starting it takes seconds."),
        ("Tests in the repo", f"{tests} (so `make build` ends with “{tests} passed”)"),
        ("Tabs", "1 Install  →  2 Get the code  →  3 Build  →  4 Open the site  →  "
                 "5 Use it  →  Windows native  →  Troubleshooting  →  Reset  →  Every command"),
    ]
    for label, text in facts:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, color=NAVY)
        cell = ws.cell(row=row, column=2, value=text)
        ws.cell(row=row, column=1).alignment = WRAP
        cell.alignment = WRAP
        for c in (1, 2):
            ws.cell(row=row, column=c).border = BOX
        ws.cell(row=row, column=1).fill = BAND
        ws.row_dimensions[row].height = max(20, 17 * -(-len(text) // 92))
        row += 1
    ws.cell(row=row + 1, column=1, value="Rule of thumb").font = Font(bold=True, color="B45309")
    ws.cell(row=row + 1, column=2,
            value="If a step does not show what the “You should see” column says, stop and use "
                  "that row's “If you do not” cell before going on. Later steps assume earlier "
                  "ones worked, and a failure three steps downstream is much harder to read.")
    ws.cell(row=row + 1, column=2).alignment = WRAP
    ws.cell(row=row + 1, column=2).fill = WARN
    ws.row_dimensions[row + 1].height = 50

    n = steps_sheet(wb, "1 Install", "1 · Install what you need",
                    "Do this once per machine. Windows users: do the WSL steps first.", [
        ("Windows only: install WSL and Ubuntu. Open PowerShell as administrator.",
         "wsl --install -d Ubuntu",
         "Windows installs Ubuntu and asks you to restart. After the restart an Ubuntu window "
         "asks you to choose a username and password.",
         "If `wsl` is not recognised, update Windows. If it says virtualisation is off, enable "
         "it in BIOS."),
        ("Windows only: install Docker Desktop from docker.com, then turn on WSL integration: "
         "Settings → Resources → WSL Integration → enable Ubuntu → Apply & Restart.",
         "",
         "A whale icon in the tray that says “Docker Desktop is running”.",
         "Docker needs the WSL integration switch even when it is installed. This is the most "
         "common reason step 5 fails."),
        ("From here on, work inside the Ubuntu terminal (not PowerShell). Update it.",
         "sudo apt update && sudo apt upgrade -y",
         "A long scroll ending without red errors.",
         "If it asks for a password, it is the Ubuntu one you chose in step 1."),
        ("Install make, git, and Python's venv and pip.",
         "sudo apt install -y make git python3-venv python3-pip",
         "Ends with no errors. Nothing prints on success beyond the install log.",
         "“Unable to locate package”: run the update line above again."),
        ("Check Docker can be reached from here.",
         "docker info",
         "A wall of text about your Docker install. The line “Server Version” is present.",
         "“Cannot connect to the Docker daemon”: Docker Desktop is not running, or WSL "
         "integration (step 2) is off."),
        ("Check your Python version.",
         "python3 --version",
         "Python 3.11.x, 3.12.x or newer.",
         "Ubuntu 22.04 ships 3.10, which is too old. Install 3.12: "
         "sudo add-apt-repository ppa:deadsnakes/ppa -y && sudo apt update && "
         "sudo apt install -y python3.12 python3.12-venv  — then use python3.12 wherever this "
         "workbook says python3."),
        ("Check make and git exist.",
         "make --version && git --version",
         "Two version lines, one for each.",
         "“command not found”: repeat step 4."),
    ], 1)

    n = steps_sheet(wb, "2 Get the code", "2 · Get the code and set up Python",
                    "Keep the project in your Linux home folder, not on the Windows drive.", [
        ("Go to your Linux home folder. Do NOT use /mnt/c/... — crossing into the Windows drive "
         "makes the build roughly three times slower.",
         "cd ~",
         "Your prompt shows ~ .",
         "If your prompt shows /mnt/c/..., you are on the Windows side. Run this step again."),
        ("Clone the repository.",
         "git clone https://github.com/robindebruyne1234/Loan-valid-DQ.git",
         "“Cloning into 'Loan-valid-DQ'…” and a progress bar reaching 100%.",
         "Private repo or auth prompt: sign in to GitHub, or use a personal access token as the "
         "password."),
        ("Enter the folder.",
         "cd Loan-valid-DQ",
         "Your prompt now ends with Loan-valid-DQ.",
         ""),
        ("Switch to the branch this was built on.",
         "git checkout ccr-46f6f45a-t9wtd4",
         "“Switched to branch 'ccr-46f6f45a-t9wtd4'”.",
         "If the branch is missing, run git fetch --all and try again."),
        ("Optional: open the folder in VS Code. Check the bottom-left corner says “WSL: Ubuntu”.",
         "code .",
         "VS Code opens. First time only, it installs a small server into WSL.",
         "If it does not say “WSL: Ubuntu”, close it and run  code .  from the Ubuntu terminal, "
         "not from Windows."),
        ("Make a private Python environment for this project. Recent Ubuntu refuses to install "
         "packages system-wide, so this step is not optional.",
         "python3 -m venv .venv",
         "Nothing prints. A .venv folder appears.",
         "“No module named venv”: sudo apt install -y python3-venv"),
        ("Switch it on. You must repeat this line in EVERY new terminal window.",
         "source .venv/bin/activate",
         "Your prompt now starts with (.venv).",
         "If a later command says ModuleNotFoundError, this is why. Run this line again."),
        ("Install the five libraries the project uses.",
         "make deps",
         "The last line reads: deps | installed into …/Loan-valid-DQ/.venv",
         "“You are not in a Python virtual environment”: step 7 was skipped. Run it, then retry."),
    ], 1)

    n = steps_sheet(wb, "3 Build", "3 · Start the database and build everything",
                    "The database runs in Docker. The build loads, cleans, models and secures "
                    "the data, then runs the tests.", [
        ("Start PostgreSQL in Docker.",
         "make up",
         "Ends with: db_up | database ready -> localhost:5432/berka as berka_owner",
         "“docker daemon not available”: Docker Desktop is off or WSL integration is off. "
         "Port 5432 already in use: stop any local PostgreSQL, or change the port in "
         "docker-compose.yml."),
        ("Confirm the container is running.",
         "docker ps",
         "A row with the name berka_pg and status “Up … (healthy)”.",
         "Empty list: run make up again and read its output."),
        ("Build everything except the AI step. Takes about 6 minutes. Leave it running.",
         "make build",
         f"Scrolling progress, then “{tests} passed” and: build | done. The data product is "
         "built and the privacy model is live.",
         "It stops at the first failure and prints which step. Fix that one, then re-run make "
         "build: it is safe to repeat and rebuilds from the source files each time."),
        ("Optional but useful: watch the privacy model work in the terminal, 40 seconds.",
         "make demo-login",
         "Seven acts ending in === END ===. In Act 5 the administrator with the wrong code "
         "can reach 0 clients; with the right one, 5,369.",
         "“connection refused”: the database stopped. Run make up."),
    ], 1)

    n = steps_sheet(wb, "4 Open the site", "4 · Start the website and open it",
                    "Two ways. The first opens your browser for you.", [
        ("Start the site and open it in your browser.",
         "make web-open",
         "The log says: serving the walkthrough on http://localhost:8080 — and a browser tab "
         "opens on “Bronze · land it”. Leave this terminal running.",
         "Browser did not open: that is fine. Open http://localhost:8080 yourself in any "
         "browser on Windows or Mac."),
        ("Alternative: start it without opening a browser.",
         "make web",
         "Same log line. Open http://localhost:8080 yourself.",
         "“Address already in use”: another program holds port 8080. Use  "
         "make web WEB_PORT=8081  and open http://localhost:8081"),
        ("Check the top-right of the page.",
         "",
         "A green pill reading “5,369 clients”. Click Next and the steps load.",
         "A red pill “pipeline not built”: step 3 of tab 3 did not finish. Run make build."),
        ("To stop the site: go to its terminal and press Ctrl + C.",
         "",
         "The log prints “stopping” and your prompt returns.",
         "To start it again later: open Ubuntu, then the three lines in the “Every command” tab."),
    ], 1)

    n = steps_sheet(wb, "5 Use it", "5 · What to click, in order",
                    "The page has seven steps. Previous/Next, the numbered boxes, or the arrow "
                    "keys all move between them.", [
        ("Step 1 Bronze. Read the three raw lines, then the blue “Design choice” and amber "
         "“What this assumes” boxes.",
         "", "Eight files, 1,079,680 rows, every row count matching its expected count.",
         "Empty page: the database is not built. Run make build."),
        ("Step 2 Silver · clean. Look at the red→green arrows.",
         "", "805502 becomes 1980-05-02 and “female”. Month 55 means May: women carry +50.",
         ""),
        ("Step 3 Silver · grade. See which rules fired and at what severity.",
         "", "19 rules fire: 1 block, 6 warn, 12 info. One row is removed from the product.",
         ""),
        ("Step 4 Gold. Check the reconciliation table at the bottom.",
         "", "Every row shows balanced = yes: core equals staging minus quarantine, on rows "
         "and on money.", ""),
        ("Step 5 Access. Find the row for client_3764 and the row for rm_south.",
         "", "client_3764 may operate an account without owning it. rm_south has a time-boxed "
         "delegation with a stated reason.", ""),
        ("Step 6 Log in. Pick Petr, press “Show the code their phone would show”, then Log in.",
         "", "Before the code: 0 clients, 0 accounts. After it: 1 client, 1 account. Try a wrong "
         "code first and watch it refuse.",
         "“Code already used”: a code works once. The page counts down to the next one."),
        ("Step 7 Ask. Click Q1 as Eva (relationship manager). Then go back and do the same "
         "as Klara.",
         "", "The model writes the same SQL for both. Eva's answer covers her whole book; "
         "Klara's is one row: herself. That difference is the point of the whole project.",
         "“NOT EXECUTED”: no model is configured. See the “AI step” section of the "
         "Troubleshooting tab. Steps 1 to 6 do not need one."),
    ], 1)

    steps_sheet(wb, "Windows native", "Windows without WSL or Docker",
                "PowerShell in the repository folder (VS Code: Terminal → New Terminal). "
                "Uses your own PostgreSQL. Replaces tabs 1-4; tab 5 is the same.", [
        ("Check Python is 3.11 or newer.",
         "py -3 --version",
         "Python 3.11.x or newer.",
         "Not found or older: install Python 3.11+ from python.org (tick “Add to PATH”)."),
        ("Check PostgreSQL is installed and running (Services → postgresql-x64-16).",
         "Get-Service postgresql*",
         "Status Running.",
         "Not listed: install PostgreSQL 16 from postgresql.org (EDB installer). "
         "Stopped: Start-Service postgresql-x64-16 (as administrator)."),
        ("Allow this script to run in this window only.",
         "Set-ExecutionPolicy -Scope Process Bypass",
         "No output.",
         "Or prefix every command with: powershell -ExecutionPolicy Bypass -File"),
        ("Create .venv and install the Python packages.",
         "scripts\\windows.ps1 setup",
         "setup | dependencies installed into .venv",
         "“needs 3.11 or newer”: pass your interpreter, e.g.  "
         "scripts\\windows.ps1 setup -Python C:\\Python312\\python.exe"),
        ("Create the project role and database (once). psql asks for the password you "
         "chose for the postgres superuser when installing PostgreSQL.",
         "scripts\\windows.ps1 init-db",
         "CREATE ROLE, CREATE DATABASE, GRANT … then init-db | done",
         "“psql.exe not found”: add C:\\Program Files\\PostgreSQL\\16\\bin to PATH. "
         "“password authentication failed for user postgres”: wrong superuser password."),
        ("Build everything (same steps as make build, without the LLM).",
         "scripts\\windows.ps1 build",
         f"Ends with “{tests} passed” and build | done.",
         "“Cannot connect to PostgreSQL”: service stopped, or init-db not run. "
         "A PGUSER/PGPASSWORD set for another login overrides the project defaults: "
         "Remove-Item Env:PGUSER, Env:PGPASSWORD"),
        ("Open the walkthrough in your browser. Then follow tab 5.",
         "scripts\\windows.ps1 web-open",
         "serving the walkthrough on http://localhost:8080, and a browser tab opens.",
         "Port in use:  scripts\\windows.ps1 web-open -WebPort 8081"),
        ("Later: tests only, or the stakeholder console demo.",
         "scripts\\windows.ps1 test\nscripts\\windows.ps1 demo-login",
         f"“{tests} passed”; the console demo ends with === END ===.",
         "Run build first if the database was reset."),
    ], 1)

    ws = wb.create_sheet("Troubleshooting")
    widths(ws, [44, 54, 62])
    row = title(ws, "When something goes wrong", "Search this tab for the words you can see on "
                "your screen.", 3)
    header(ws, row, ["What you see", "What it means", "What to do"])
    trouble = [
        ("make: command not found", "make is not installed", "sudo apt install -y make"),
        ("ModuleNotFoundError: No module named 'psycopg'",
         "The virtual environment is not switched on in this terminal",
         "source .venv/bin/activate   (your prompt should then start with (.venv))"),
        ("You are not in a Python virtual environment",
         "make deps was run without the environment on",
         "python3 -m venv .venv && source .venv/bin/activate && make deps"),
        ("Cannot connect to the Docker daemon",
         "Docker Desktop is off, or WSL integration is off",
         "Start Docker Desktop. Settings → Resources → WSL Integration → enable Ubuntu → Apply."),
        ("connection refused  (port 5432)", "The database container is not running",
         "make up   then   docker ps"),
        ("database did not become ready in time", "The container is slow to start, or crashed",
         "docker compose logs db   — then  make up  again"),
        ("port is already allocated / address already in use (5432)",
         "A PostgreSQL is already running on your machine",
         "Stop it (Windows: Services → postgresql; Linux: sudo systemctl stop postgresql), "
         "then make up"),
        ("Address already in use  (8080)", "Something else holds the website's port",
         "make web WEB_PORT=8081   and open http://localhost:8081"),
        ("Page says “pipeline not built”, red pill",
         "The site is up but the database is empty", "make build   (then reload the page)"),
        ("code already used", "A one-time code works once, even inside its 30 seconds",
         "Wait for the next one. The page counts down. This is the replay protection working."),
        ("locked until HH:MM", "Five wrong codes in a row", "make entitlements  resets the counters"),
        ("A persona sees 0 rows when it should see some",
         "The security layer was rebuilt without its model", "make model   then   make entitlements"),
        ("Build is very slow (> 20 min)", "The project is on the Windows drive (/mnt/c)",
         "Clone into ~ instead (tab 2, step 1)"),
        ("Python 3.10 or older", "Too old for this project",
         "Install 3.12 — see tab 1, step 6 — and use python3.12 in place of python3"),
        ("AI step: NOT EXECUTED",
         "No language model is configured. By design this is shown rather than faked.",
         "Optional. Steps 1–6 of the site work without one. See the three options below."),
    ]
    for item in trouble:
        row += 1
        for col, value in enumerate(item, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.alignment, cell.border = WRAP, BOX
        ws.cell(row=row, column=1).font = Font(bold=True, color="991B1B")
        ws.cell(row=row, column=3).font = MONO
        ws.row_dimensions[row].height = max(32, 17 * max(-(-len(item[2]) // 56), -(-len(item[1]) // 50)))
    row += 2
    ws.cell(row=row, column=1, value="The AI step: three options").font = Font(bold=True, size=12, color=NAVY)
    ai = [
        ("A · Anthropic API key (simplest)",
         "export LLM_PROVIDER=anthropic_api && export LLM_API_KEY=sk-ant-…   then   make web-open",
         "Costs a few cents. Set both variables in the same terminal before starting the site."),
        ("B · Local model with Ollama (free)",
         "curl -fsSL https://ollama.com/install.sh | sh && ollama pull qwen2.5-coder:7b && "
         "export LLM_PROVIDER=ollama && export LLM_MODEL=qwen2.5-coder:7b   then   make web-open",
         "Needs about 8 GB RAM. A smaller model is faster and will get more answers wrong, "
         "which the page shows rather than hides."),
        ("C · Skip it",
         "(nothing to run)",
         "Steps 1–6 work fully. The previous run's prompts, SQL and results are in "
         "deliverables/Berka_TakeHome_Submission.xlsx, tabs Questions and Q detail."),
    ]
    for label, cmd, note in ai:
        row += 1
        for col, value in enumerate((label, cmd, note), 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.alignment, cell.border = WRAP, BOX
        ws.cell(row=row, column=1).font = Font(bold=True)
        ws.cell(row=row, column=2).font = MONO
        ws.cell(row=row, column=2).fill = CODE
        ws.row_dimensions[row].height = 64

    ws = wb.create_sheet("Reset")
    widths(ws, [46, 56, 54])
    row = title(ws, "Start over, safely", "Nothing here can damage anything outside this project. "
                "The source files are read-only inputs; everything else is rebuilt from them.", 3)
    header(ws, row, ["When", "Command", "What it does"])
    for item in [
        ("Rebuild the data, keep the database", "make build",
         "Safe to repeat any number of times. Rebuilds every layer from the source files."),
        ("Stop the website", "Ctrl + C  in the terminal running it", "Stops the site. Data is untouched."),
        ("Stop the database", "docker compose down", "Stops the container. Data survives in a volume."),
        ("Throw the database away completely", "docker compose down -v",
         "Deletes the volume too. Follow with make up && make build."),
        ("Come back tomorrow", "cd ~/Loan-valid-DQ && source .venv/bin/activate && make up && make web-open",
         "Everything is already built; this is only starting it."),
        ("Pick up new changes from GitHub", "git pull && make build",
         "Fetches changes and rebuilds."),
    ]:
        row += 1
        for col, value in enumerate(item, 1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.alignment, cell.border = WRAP, BOX
        ws.cell(row=row, column=2).font = MONO
        ws.cell(row=row, column=2).fill = CODE
        ws.row_dimensions[row].height = 40

    ws = wb.create_sheet("Every command")
    widths(ws, [8, 64, 50])
    row = title(ws, "Every command, in order, with nothing else",
                "For when you have done this once and just want to paste. Lines starting # are "
                "comments, not commands.", 3)
    header(ws, row, ["#", "Command", "Note"])
    sequence = [
        ("# First time only", ""),
        ("sudo apt update && sudo apt install -y make git python3-venv python3-pip",
         "Windows: in the Ubuntu app, with Docker Desktop running"),
        ("cd ~ && git clone https://github.com/robindebruyne1234/Loan-valid-DQ.git",
         "Not in /mnt/c"),
        ("cd Loan-valid-DQ && git checkout ccr-46f6f45a-t9wtd4", ""),
        ("python3 -m venv .venv", ""),
        ("source .venv/bin/activate", "Repeat in every new terminal"),
        ("make deps", ""),
        ("make up", "Starts PostgreSQL in Docker"),
        ("make build", "About 6 minutes"),
        ("make web-open", "Opens http://localhost:8080"),
        ("# Every time after that", ""),
        ("cd ~/Loan-valid-DQ && source .venv/bin/activate && make up && make web-open", ""),
        ("# Optional extras", ""),
        ("make demo-login", "The privacy walkthrough in the terminal"),
        ("make demo-interactive", "Pick a person, type the code, run your own SQL"),
        ("make test", "Run the tests"),
    ]
    k = 0
    for command, note in sequence:
        row += 1
        is_comment = command.startswith("#")
        if not is_comment:
            k += 1
        ws.cell(row=row, column=1, value="" if is_comment else k)
        c = ws.cell(row=row, column=2, value=command)
        ws.cell(row=row, column=3, value=note)
        for col in (1, 2, 3):
            ws.cell(row=row, column=col).border = BOX
            ws.cell(row=row, column=col).alignment = WRAP
        if is_comment:
            c.font = Font(bold=True, color=NAVY)
            for col in (1, 2, 3):
                ws.cell(row=row, column=col).fill = BAND
        else:
            c.font, c.fill = MONO, CODE
        ws.row_dimensions[row].height = 30 if not is_comment else 22

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToHeight = 0
    return wb


def main() -> int:
    """Write the workbook.

    :returns: Process exit code.
    """
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    wb = build()
    wb.save(TARGET)
    print(f"wrote {TARGET.relative_to(ROOT)} -> {len(wb.sheetnames)} tabs: "
          + " | ".join(wb.sheetnames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
