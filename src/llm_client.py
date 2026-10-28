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

``ollama``
    A local Ollama server, so the walkthrough runs with no API key and no paid
    inference. Output is constrained to the answer's JSON schema, and every
    way a local runtime fails -- not running, model not pulled, too slow,
    empty, cut off -- comes back as a typed, actionable error.

``none``
    Export the prompt and record the step as ``NOT EXECUTED``. No text is ever
    invented: a question with no real response has an empty SQL cell in the
    deliverable, and the status report says so.

Every call writes ``llm_logs/<label>.json`` containing the provider, the model,
the parameters, the full system and user prompts, the raw response, the timing
and the cost. That file is the evidence behind the Questions tab.
"""

from __future__ import annotations

import argparse
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

#: The answer contract of ``semantic/prompt_template.md`` as a JSON schema.
#: Ollama constrains decoding to it, so a small model cannot wrap the object
#: in prose or drop a field. Whether the SQL inside is right is still for the
#: guard and the database to decide.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "reasoning": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sql", "reasoning", "assumptions", "caveats"],
}

#: Characters per token used to size a prompt before it is sent. Measured on
#: this project's prompt, 30,747 characters were 7,979 qwen2.5 tokens (3.85).
#: The low figure over-estimates on purpose, because an under-estimate is the
#: failure that matters: Ollama 0.40 truncates an oversized prompt without an
#: error, and the model then answers fluently from part of the semantic layer.
PROMPT_CHARS_PER_TOKEN_LOW = 3.0

#: Fewer evaluated tokens than this ratio implies means part of the prompt
#: was dropped. Ollama reports the full prompt count even when it reuses its
#: cache, so a low count is truncation, not caching.
PROMPT_CHARS_PER_TOKEN_HIGH = 6.0


@dataclass
class LLMResponse:
    """One LLM call and everything needed to audit it.

    :ivar provider: Provider that served the call.
    :ivar model: Model identifier requested.
    :ivar executed: ``False`` when no call was made (provider ``none``) or the
        call failed; the deliverables then show ``NOT EXECUTED``.
    :ivar text: The model's raw text response.
    :ivar error: Error message when the call failed.
    :ivar error_kind: Machine-readable failure class, for example
        ``runtime_unavailable`` or ``model_missing``; ``None`` on success.
    :ivar duration_sec: Wall clock duration of the call.
    :ivar usage: Token and cost accounting as reported by the provider.
    :ivar raw: The provider's full response payload, stored verbatim.
    """

    provider: str
    model: str
    executed: bool
    text: str = ""
    error: str | None = None
    error_kind: str | None = None
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


def _ollama_http_error(exc: urllib.error.HTTPError, model: str) -> tuple[str, str]:
    """Classify an HTTP error answered by Ollama.

    :param exc: The error, whose body carries Ollama's own message.
    :param model: Model tag that was requested.
    :returns: ``(error_kind, actionable message)``.
    """
    try:
        detail = str(json.loads(exc.read().decode("utf-8", "replace")).get("error", ""))
    except (ValueError, OSError, AttributeError):
        detail = ""
    if exc.code == 404 and "not found" in detail.lower():
        return "model_missing", (f"model '{model}' is not installed in Ollama; "
                                 f"run: ollama pull {model}")
    return "http_error", f"Ollama answered HTTP {exc.code}: {detail or exc.reason}"


def _is_timeout(exc: BaseException) -> bool:
    """Whether a urllib failure was a timeout, raised directly or wrapped.

    :param exc: The exception.
    :returns: ``True`` for a connect or read timeout.
    """
    return isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)


def call_ollama(prompt: str, model: str, timeout: int) -> LLMResponse:
    """Call a local Ollama server, with the answer constrained to JSON.

    The request sets the context window explicitly: Ollama's default is
    smaller than the semantic layer, and an unset window drops the start of
    the prompt without saying so. It also constrains decoding to
    :data:`ANSWER_SCHEMA`, which is what makes a small model usable here.

    :param prompt: The full user prompt.
    :param model: Model tag, for example ``qwen2.5-coder:3b``.
    :param timeout: Hard timeout in seconds.
    :returns: An :class:`LLMResponse`; on failure ``executed`` is ``False``
        and ``error_kind`` says which failure it was.
    """
    options = {
        "temperature": config.LLM_TEMPERATURE,
        "num_ctx": config.OLLAMA_NUM_CTX,
        "num_predict": config.OLLAMA_NUM_PREDICT,
    }
    if config.OLLAMA_NUM_GPU is not None:
        options["num_gpu"] = config.OLLAMA_NUM_GPU
    parameters = {"model": model, "host": config.OLLAMA_HOST, "timeout_sec": timeout,
                  "keep_alive": config.OLLAMA_KEEP_ALIVE, "format": "ANSWER_SCHEMA",
                  **options}
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "format": ANSWER_SCHEMA,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": options,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/generate",
        data=body,
        headers={"content-type": "application/json"},
    )

    def failure(kind: str, error: str, raw: Any = None) -> LLMResponse:
        return LLMResponse(provider="ollama", model=model, executed=False, error=error,
                           error_kind=kind, duration_sec=time.perf_counter() - started,
                           raw=raw, user_prompt=prompt, parameters=parameters)

    started = time.perf_counter()
    prompt_chars = len(prompt) + len(SYSTEM_PROMPT)
    estimated = int(prompt_chars / PROMPT_CHARS_PER_TOKEN_LOW)
    if estimated + config.OLLAMA_NUM_PREDICT > config.OLLAMA_NUM_CTX:
        return failure("context_overflow",
                       f"the prompt may be up to {estimated} tokens, which with "
                       f"{config.OLLAMA_NUM_PREDICT} for the answer does not fit "
                       f"OLLAMA_NUM_CTX={config.OLLAMA_NUM_CTX}; raise OLLAMA_NUM_CTX")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return failure(*_ollama_http_error(exc, model))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        if _is_timeout(exc):
            return failure("timeout", f"Ollama gave no answer within {timeout}s; raise "
                                      "LLM_TIMEOUT_SECONDS or use a smaller model")
        reason = getattr(exc, "reason", exc)
        return failure("runtime_unavailable",
                       f"Ollama is not reachable at {config.OLLAMA_HOST} ({reason}); start "
                       "the Ollama app or run `ollama serve`")
    except (ValueError, UnicodeDecodeError) as exc:
        return failure("malformed_response", f"Ollama returned a body that is not JSON: {exc}")

    if not isinstance(payload, dict):
        return failure("malformed_response", "Ollama returned JSON that is not an object")
    # The token ids of the whole conversation: tens of kilobytes of integers
    # that say nothing an auditor can read. Everything else is kept verbatim.
    payload.pop("context", None)
    if payload.get("error"):
        return failure("http_error", f"Ollama reported an error: {payload['error']}", payload)

    nanos = 1e-9
    usage = {
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
        "load_sec": round((payload.get("load_duration") or 0) * nanos, 3),
        "prompt_eval_sec": round((payload.get("prompt_eval_duration") or 0) * nanos, 3),
        "eval_sec": round((payload.get("eval_duration") or 0) * nanos, 3),
        "total_sec": round((payload.get("total_duration") or 0) * nanos, 3),
        "done_reason": payload.get("done_reason"),
        "cost_usd": 0.0,
    }
    text = payload.get("response") or ""
    result = LLMResponse(provider="ollama", model=model, executed=True, text=text,
                         duration_sec=time.perf_counter() - started, usage=usage,
                         raw=payload, user_prompt=prompt, parameters=parameters)

    prompt_tokens = int(payload.get("prompt_eval_count") or 0)
    if prompt_tokens and (
        prompt_tokens >= config.OLLAMA_NUM_CTX - config.OLLAMA_NUM_PREDICT
        or prompt_tokens < prompt_chars / PROMPT_CHARS_PER_TOKEN_HIGH
    ):
        result.executed, result.error_kind = False, "context_overflow"
        result.error = (f"Ollama evaluated {prompt_tokens} tokens of a {prompt_chars}-character "
                        f"prompt in a {config.OLLAMA_NUM_CTX}-token window, so part of the "
                        "semantic layer was probably dropped; raise OLLAMA_NUM_CTX")
    elif payload.get("done_reason") == "length":
        result.executed, result.error_kind = False, "output_truncated"
        result.error = (f"the answer was cut off at {config.OLLAMA_NUM_PREDICT} tokens; "
                        "raise OLLAMA_NUM_PREDICT")
    elif not text.strip():
        result.executed, result.error_kind = False, "empty_response"
        result.error = "the model returned an empty response"
    return result


def ollama_status(model: str | None = None, timeout: float = 3.0) -> dict[str, Any]:
    """Whether the Ollama runtime answers and holds the model. Generates nothing.

    :param model: Model tag to look for; defaults to the configured one.
    :param timeout: Seconds to wait for the runtime.
    :returns: ``{"host", "model", "reachable", "model_present", "models",
        "error"}``; ``error`` is ``None`` only when both checks pass.
    """
    model = model or (config.LLM_MODEL if config.LLM_PROVIDER == "ollama"
                      else config.LLM_DEFAULT_MODELS["ollama"])
    status: dict[str, Any] = {"host": config.OLLAMA_HOST, "model": model, "reachable": False,
                              "model_present": False, "models": [], "error": None}
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=timeout) as response:
            listing = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        status["error"] = (f"Ollama is not reachable at {config.OLLAMA_HOST} "
                           f"({getattr(exc, 'reason', exc)}); start the Ollama app or run "
                           "`ollama serve`")
        return status
    status["reachable"] = True
    status["models"] = sorted(m.get("name", "") for m in listing.get("models", []))
    wanted = model if ":" in model else f"{model}:latest"
    status["model_present"] = wanted in status["models"]
    if not status["model_present"]:
        status["error"] = f"model '{model}' is not installed in Ollama; run: ollama pull {model}"
    return status


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
    model = model or (config.LLM_MODEL if provider == config.LLM_PROVIDER
                      else config.LLM_DEFAULT_MODELS.get(provider, config.LLM_MODEL))
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
        "error_kind": response.error_kind,
        "duration_sec": round(response.duration_sec, 3),
        "usage": response.usage,
        "system_prompt": response.system_prompt,
        "user_prompt": response.user_prompt,
        "raw_response_text": response.text,
        "raw_provider_payload": response.raw,
        **(extra or {}),
    }
    path = config.LLM_LOG_DIR / f"{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    LOGGER.info("logged call -> %s", path.relative_to(config.PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    """Check that the configured runtime can answer, optionally warming it up.

    The warm-up sends one real question with the real semantic layer, which
    loads the model and leaves the evaluated semantic layer in Ollama's cache,
    so the first visitor question does not pay for either. Its SQL is never
    executed; it is a timing and format check only.

    :param argv: Command-line arguments; ``None`` reads ``sys.argv``.
    :returns: ``0`` when the runtime is ready, ``1`` when it is not.
    """
    parser = argparse.ArgumentParser(description="Check the configured LLM runtime.")
    parser.add_argument("--warm", action="store_true",
                        help="send one real question and report its timings")
    args = parser.parse_args(argv)
    LOGGER.info("check | provider=%s model=%s", config.LLM_PROVIDER, config.LLM_MODEL)

    if config.LLM_PROVIDER == "ollama":
        status = ollama_status()
        LOGGER.info("check | host %s reachable=%s", status["host"], status["reachable"])
        if status["reachable"]:
            LOGGER.info("check | installed models: %s", ", ".join(status["models"]) or "none")
        if status["error"]:
            LOGGER.error("check | %s", status["error"])
            return 1
        LOGGER.info("check | num_ctx=%d num_predict=%d num_gpu=%s keep_alive=%s timeout=%ds",
                    config.OLLAMA_NUM_CTX, config.OLLAMA_NUM_PREDICT,
                    "auto" if config.OLLAMA_NUM_GPU is None else config.OLLAMA_NUM_GPU,
                    config.OLLAMA_KEEP_ALIVE, config.LLM_TIMEOUT_SECONDS)
    elif config.LLM_PROVIDER == "claude_cli" and not shutil.which("claude"):
        LOGGER.error("check | the claude CLI is not on PATH; set LLM_PROVIDER=ollama for local mode")
        return 1

    if not args.warm:
        return 0
    from src import run_questions, semantic_context  # noqa: PLC0415 - avoids an import cycle

    pack = semantic_context.render_context_pack(semantic_context.load_semantic_layer())
    prompt = run_questions.build_prompt(pack, "WARMUP", "How many clients are there?")
    LOGGER.info("check | warming up with a %d-character prompt (SQL is not executed)", len(prompt))
    response = complete(prompt)
    write_call_log("local/warmup", response, {"surface": "llm-check --warm"})
    if not response.executed:
        LOGGER.error("check | warm-up failed [%s]: %s", response.error_kind, response.error)
        return 1
    parsed, parse_error = run_questions.parse_model_output(response.text)
    LOGGER.info("check | warm-up answered in %.1fs | usage %s", response.duration_sec, response.usage)
    LOGGER.info("check | answer shape: %s", "valid JSON with sql" if parsed else parse_error)
    return 0 if parsed else 1


if __name__ == "__main__":
    raise SystemExit(main())
