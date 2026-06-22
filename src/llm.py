"""The SINGLE swappable LLM interface (Phase 1).

Every LLM call in the system goes through `complete()` / `complete_json()` here.
It shells out to the Claude Code CLI headless (`claude -p`) under the owner's Max
subscription, passing the prompt on stdin (no command-line length limits).

CRITICAL: never set ANTHROPIC_API_KEY in the environment — that silently bills
the pay-as-you-go API instead of the subscription. As defense in depth, the
child process is launched with that key explicitly stripped from its environment.

Swappability: this module is the only thing that knows *how* LLM calls happen.
Moving to the Anthropic API later (if headless subscription billing changes) is a
one-file change — callers only depend on `complete()` / `complete_json()`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 240  # seconds; curation prompts can take a while headless
_JSON_SYSTEM = "You output a single strict JSON value only — no prose, no markdown fences."


class LLMError(RuntimeError):
    """Raised when the Claude CLI call fails or returns nothing usable."""


def _claude_path() -> str:
    path = shutil.which("claude")
    if not path:
        raise LLMError(
            "`claude` CLI not found on PATH. The LLM step runs through Claude "
            "Code headless under the Max subscription."
        )
    return path


def _child_env() -> dict[str, str]:
    """Environment for the CLI with ANTHROPIC_API_KEY stripped (stay on the sub)."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def complete(
    prompt: str,
    system: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: list[str] | None = None,
) -> str:
    """Run one headless completion and return the model's text output.

    `prompt` goes on stdin; `system` (optional) is appended to the system prompt.

    `allowed_tools` pre-approves Claude Code tools for this call (e.g.
    ["WebSearch", "WebFetch"]), turning the completion into a small research
    agent that can gather live context before answering. Only the listed tools
    are permitted — anything else stays denied, so this is safe to enable for the
    research-backed prediction step. When None (the default) it's a plain,
    tool-free completion. Research calls run longer, so pass a larger `timeout`.

    Raises LLMError on non-zero exit, timeout, or empty output.
    """
    cmd = [_claude_path(), "-p", "--output-format", "text"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if system:
        cmd += ["--append-system-prompt", system]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"Claude CLI timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise LLMError(
            f"Claude CLI exited {result.returncode}: {result.stderr.strip()[:500]}"
        )

    out = (result.stdout or "").strip()
    if not out:
        raise LLMError("Claude CLI returned empty output.")
    return out


def _extract_json(text: str):
    """Pull the first JSON value out of `text`, tolerating stray prose/fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip a ```json ... ``` fence
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Could not parse JSON from model output:\n{text[:500]}")


def complete_json(
    prompt: str,
    system: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: list[str] | None = None,
):
    """Run a completion expected to return JSON, and parse it.

    Prepends a strict-JSON instruction to any caller-supplied system prompt.
    `allowed_tools` is forwarded to `complete` (see there) for research-backed
    JSON calls.
    """
    sys_prompt = _JSON_SYSTEM if not system else f"{system}\n\n{_JSON_SYSTEM}"
    raw = complete(prompt, system=sys_prompt, timeout=timeout, allowed_tools=allowed_tools)
    return _extract_json(raw)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("text:", complete("Reply with exactly: PONG"))
    print("json:", complete_json('Return {"ok": true} and nothing else.'))
