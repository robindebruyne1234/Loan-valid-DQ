"""Windows startup for the local model, driven through scripts/windows.ps1.

These run the real script in Windows PowerShell, so they skip -- and say so
-- anywhere else. None of them needs a model: the runtime is either a closed
port or :mod:`tests.fake_ollama`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from src import config
from tests import fake_ollama

SCRIPT = config.PROJECT_ROOT / "scripts" / "windows.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="scripts/windows.ps1 runs only under Windows PowerShell",
)


def run_script(target: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run one windows.ps1 target with the script's own LLM defaults.

    :param target: The target name.
    :param env: Environment overrides.
    :returns: The completed process; ``out`` is stdout and stderr together.
    """
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("LLM_", "OLLAMA_"))}
    clean.update(env)
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), target],
        env=clean, capture_output=True, text=True, timeout=180, cwd=config.PROJECT_ROOT,
        check=False,
    )


def output(result: subprocess.CompletedProcess[str]) -> str:
    """Everything the script printed.

    :param result: A finished run.
    :returns: stdout followed by stderr.
    """
    return (result.stdout or "") + (result.stderr or "")


def test_the_script_parses_without_errors() -> None:
    """A syntax error in a runner only shows when someone runs that target."""
    command = (
        "$errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', "
        "[ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, output(result)


def test_local_mode_is_the_default_and_reports_an_absent_runtime() -> None:
    """No LLM settings at all: Ollama with its model, and a clear refusal."""
    result = run_script("llm-check", OLLAMA_HOST=fake_ollama.closed_port_url())
    text = output(result)
    assert result.returncode != 0, text
    assert "provider=ollama" in text
    assert config.LLM_DEFAULT_MODELS["ollama"] in text
    assert "not reachable" in text


def test_local_mode_keeps_the_model_on_the_cpu_unless_told_otherwise() -> None:
    """The stable default on a small laptop GPU; -1 hands the choice to Ollama."""
    with fake_ollama.running() as fake:
        default = output(run_script("llm-check", OLLAMA_HOST=fake.url))
        chosen = output(run_script("llm-check", OLLAMA_HOST=fake.url, OLLAMA_NUM_GPU="-1"))
    assert "num_gpu=0" in default
    assert "num_gpu=-1" in chosen


def test_llm_check_passes_against_a_ready_runtime() -> None:
    """Reachable and pulled is ready."""
    with fake_ollama.running() as fake:
        result = run_script("llm-check", OLLAMA_HOST=fake.url)
    assert result.returncode == 0, output(result)


def test_llm_check_names_the_missing_model() -> None:
    """Reachable but not pulled: the command that fixes it."""
    with fake_ollama.running() as fake:
        fake.models = []
        result = run_script("llm-check", OLLAMA_HOST=fake.url)
    assert result.returncode != 0
    assert f"ollama pull {config.LLM_DEFAULT_MODELS['ollama']}" in output(result)


def test_an_explicit_provider_is_left_alone() -> None:
    """The local default applies only when nothing was chosen."""
    result = run_script("llm-check", LLM_PROVIDER="none")
    assert result.returncode == 0, output(result)
    assert "provider=none" in output(result)


def test_local_mode_cannot_overwrite_the_recorded_claude_run() -> None:
    """``questions`` writes the evidence the deliverables are built from.

    In local mode it refuses and names the target that writes elsewhere, and
    the recorded file is byte-for-byte unchanged.
    """
    before = config.LLM_RESULTS_JSON.read_bytes()
    result = run_script("questions", OLLAMA_HOST=fake_ollama.closed_port_url())
    assert result.returncode != 0
    assert "questions-local" in output(result)
    assert config.LLM_RESULTS_JSON.read_bytes() == before
