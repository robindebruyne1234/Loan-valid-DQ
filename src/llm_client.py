"""Provider abstraction for the LLM, with a full audit log of every call.

Three providers behind one interface:

``claude_cli``
    The authenticated Claude Code CLI on this machine, invoked as a plain
    completion endpoint: no tools, no MCP servers, no filesystem access, an
    explicit system prompt, and a working directory outside the repository so
    no project context is picked up. The model therefore sees only the prompt
    it is given -- which is the whole point, because an agent that could read
    the database would prove nothing about the semantic layer.

``anthropic_api``
    A hosted API call, used when ``LLM_API_KEY`` is present. Same interface.

``none``
    Export the prompt and record the step as ``NOT EXECUTED``. No text is ever
    invented: a question with no real response has an empty SQL cell in the
    deliverable, and the status report says so.

Every call writes ``llm_logs/<label>.json`` containing the provider, the model,
the parameters, the full system and user prompts, the raw response, the timing
and the cost. That file is the evidence behind the Questions tab.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src import config, db

LOGGER = db.setup_logging("llm")

#: System prompt for the sandboxed call. Deliberately short: the semantic layer
#: in the user prompt is where the knowledge lives, and a long system prompt
#: would blur the line between "the semantic layer worked" and "the prompt
#: engineering worked".
SYSTEM_PROMPT = (
    "You are a careful analytics engineer. You write PostgreSQL 16 SQL using "
    "only the semantic layer you are given. You never claim to have run a "
    "query, and you answer with exactly one JSON object and no other text."
)

#: Tools disabled on every CLI call, so the model cannot read the repository,
#: the database or the internet. Verified by
#: tests/test_semantic.py and by the recorded transcripts in llm_logs/.
DISABLED_TOOLS: tuple[str, ...] = (
    "Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
    "BashOutput", "KillShell", "SlashCommand", "Agent",
)


@dataclass
class LLMResponse:
    """One LLM call and everything needed to audit it.

    :ivar provider: Provider that served the call.
    :ivar model: Model identifier requested.
    :ivar executed: ``False`` when no call was made (provider ``none``) or the
        call failed; the deliverables then show ``NOT EXECUTED``.
    :ivar text: The model's raw text response.
    :ivar error: Error message when the call failed.
    :ivar duration_sec: Wall clock duration of the call.
    :ivar usage: Token and cost accounting as reported by the provider.
    :ivar raw: The provider's full response payload, stored verbatim.
    """

    provider: str
    model: str
    executed: bool
    text: str = ""
    error: str | None = None
    duration_sec: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    system_prompt: str = SYSTEM_PROMPT
    user_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


def _sandbox_dir() -> str:
    """Return a scratch working directory for the CLI subprocess.

    The CLI is run outside the repository so it cannot pick up ``CLAUDE.md``,
    the project settings or any file in it. Combined with the disabled tools
    this makes the call a pure text completion.

    :returns: Path of an existing, empty-ish directory.
    """
    base = os.environ.get("LLM_SANDBOX_DIR") or "/tmp/berka_llm_sandbox"
    os.makedirs(base, exist_ok=True)
    return base


def call_claude_cli(prompt: str, model: str, timeout: int) -> LLMResponse:
    """Call the local Claude CLI as a sandboxed completion endpoint.

    :param prompt: The full user prompt (semantic layer plus the question).
    :param model: Model identifier passed to ``--model``.
    :param timeout: Hard timeout in seconds.
    :returns: An :class:`LLMResponse`; ``executed`` is ``False`` when the CLI
        is missing, times out or returns a non-zero exit code.
    """
    binary = shutil.which("claude")
    parameters = {
        "model": model,
        "output_format": "json",
        "tools": "all disabled",
        "mcp": "none (--strict-mcp-config with an empty config)",
        "cwd": _sandbox_dir(),
        "system_prompt": "explicit, see system_prompt field",
        "timeout_sec": timeout,
    }
    if not binary:
        return LLMResponse(
            provider="claude_cli",
            model=model,
            executed=False,
            error="the claude CLI is not on PATH",
            user_prompt=prompt,
            parameters=parameters,
        )

    command = [
        binary,
        "-p",
        prompt,
        "--model", model,
        "--output-format", "json",
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--system-prompt", SYSTEM_PROMPT,
        "--disallowedTools", *DISABLED_TOOLS,
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_sandbox_dir(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return LLMResponse(
            provider="claude_cli",
            model=model,
            executed=False,
            error=f"timed out after {timeout}s",
            duration_sec=time.perf_counter() - started,
            user_prompt=prompt,
            parameters=parameters,
        )

    duration = time.perf_counter() - started
    if completed.returncode != 0:
        return LLMResponse(
            provider="claude_cli",
            model=model,
            executed=False,
            error=f"exit code {completed.returncode}: "
                  f"{(completed.stderr or '').strip()[:400]}",
            duration_sec=duration,
            user_prompt=prompt,
            parameters=parameters,
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return LLMResponse(
            provider="claude_cli",
            model=model,
            executed=False,
            error=f"the CLI returned output that is not JSON: {exc}",
            duration_sec=duration,
            raw=completed.stdout[:4000],
            user_prompt=prompt,
            parameters=parameters,
        )

    return LLMResponse(
        provider="claude_cli",
        model=model,
        executed=not payload.get("is_error", False),
        text=payload.get("result", "") or "",
        error=payload.get("api_error_status"),
        duration_sec=duration,
        usage={
            "usage": payload.get("usage"),
            "model_usage": payload.get("modelUsage"),
            "total_cost_usd": payload.get("total_cost_usd"),
            "num_turns": payload.get("num_turns"),
            "permission_denials": payload.get("permission_denials"),
        },
        raw=payload,
        user_prompt=prompt,
        parameters=parameters,
    )


def call_anthropic_api(prompt: str, model: str, timeout: int) -> LLMResponse:
    """Call the hosted Anthropic Messages API.

    :param prompt: The full user prompt.
    :param model: Model identifier.
    :param timeout: Hard timeout in seconds.
    :returns: An :class:`LLMResponse`; ``executed`` is ``False`` when no API
        key is configured or the request fails.
    """
    parameters = {
        "model": model,
        "max_tokens": 4096,
        "temperature": config.LLM_TEMPERATURE,
        "timeout_sec": timeout,
    }
    api_key = os.environ.get(config.LLM_API_KEY_ENV)
    if not api_key:
        return LLMResponse(
            provider="anthropic_api",
            model=model,
            executed=False,
            error=f"{config.LLM_API_KEY_ENV} is not set",
            user_prompt=prompt,
            parameters=parameters,
        )

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 4096,
            "temperature": config.LLM_TEMPERATURE,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return LLMResponse(
            provider="anthropic_api",
            model=model,
            executed=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_sec=time.perf_counter() - started,
            user_prompt=prompt,
            parameters=parameters,
        )

    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    )
    return LLMResponse(
        provider="anthropic_api",
        model=model,
        executed=True,
        text=text,
        duration_sec=time.perf_counter() - started,
        usage={"usage": payload.get("usage")},
        raw=payload,
        user_prompt=prompt,
        parameters=parameters,
    )


def call_ollama(prompt: str, model: str, timeout: int) -> LLMResponse:
    """Call a local Ollama server.

    Kept because it was the documented default stack; it is not reachable from
    the build environment (the model download hosts are not on the egress
    allow-list), so it has never executed here. See DECISIONS.md D005.

    :param prompt: The full user prompt.
    :param model: Model tag, for example ``qwen2.5-coder:7b``.
    :param timeout: Hard timeout in seconds.
    :returns: An :class:`LLMResponse`.
    """
    parameters = {"model": model, "temperature": config.LLM_TEMPERATURE,
                  "host": config.OLLAMA_HOST, "timeout_sec": timeout}
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": config.LLM_TEMPERATURE},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/generate",
        data=body,
        headers={"content-type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return LLMResponse(
            provider="ollama",
            model=model,
            executed=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_sec=time.perf_counter() - started,
            user_prompt=prompt,
            parameters=parameters,
        )
    return LLMResponse(
        provider="ollama",
        model=model,
        executed=True,
        text=payload.get("response", ""),
        duration_sec=time.perf_counter() - started,
        usage={k: payload.get(k) for k in ("eval_count", "prompt_eval_count", "total_duration")},
        raw=payload,
        user_prompt=prompt,
        parameters=parameters,
    )


def complete(prompt: str, provider: str | None = None, model: str | None = None) -> LLMResponse:
    """Send one prompt to the configured provider.

    :param prompt: The full user prompt.
    :param provider: Override for :data:`src.config.LLM_PROVIDER`.
    :param model: Override for :data:`src.config.LLM_MODEL`.
    :returns: An :class:`LLMResponse`. Never raises: a failure is returned as
        ``executed = False`` with the reason, because a pipeline that crashes
        on a model error cannot report honestly on it.
    """
    provider = provider or config.LLM_PROVIDER
    model = model or config.LLM_MODEL
    timeout = config.LLM_TIMEOUT_SECONDS

    if provider == "none":
        return LLMResponse(
            provider="none",
            model=model,
            executed=False,
            error=config.NOT_EXECUTED,
            user_prompt=prompt,
            parameters={"note": "prompt pack exported, no call made"},
        )
    if provider == "claude_cli":
        return call_claude_cli(prompt, model, timeout)
    if provider == "anthropic_api":
        return call_anthropic_api(prompt, model, timeout)
    if provider == "ollama":
        return call_ollama(prompt, model, timeout)
    return LLMResponse(
        provider=provider,
        model=model,
        executed=False,
        error=f"unknown provider '{provider}'",
        user_prompt=prompt,
    )


def write_call_log(label: str, response: LLMResponse, extra: dict[str, Any] | None = None) -> None:
    """Write the full audit record of one call to ``llm_logs/<label>.json``.

    :param label: File name stem, normally the question id and attempt number.
    :param response: The response to record.
    :param extra: Additional context to store alongside, such as the guard
        verdict and the executed rows.
    :returns: ``None``.
    """
    config.LLM_LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "label": label,
        "logged_at_utc": db.utc_now_iso(),
        "git_commit": db.git_commit(),
        "provider": response.provider,
        "model": response.model,
        "parameters": response.parameters,
        "executed": response.executed,
        "error": response.error,
        "duration_sec": round(response.duration_sec, 3),
        "usage": response.usage,
        "system_prompt": response.system_prompt,
        "user_prompt": response.user_prompt,
        "raw_response_text": response.text,
        "raw_provider_payload": response.raw,
        **(extra or {}),
    }
    path = config.LLM_LOG_DIR / f"{label}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    LOGGER.info("logged call -> %s", path.relative_to(config.PROJECT_ROOT))
