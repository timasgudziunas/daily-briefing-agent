"""The SINGLE swappable LLM interface (Phase 1).

Every LLM call in the system goes through this module. It shells out to the
Claude Code CLI headless (`claude -p`) under the owner's Max subscription.

CRITICAL: never set ANTHROPIC_API_KEY in the environment — that silently bills
the pay-as-you-go API instead of the subscription. Keeping all LLM access behind
this one interface is what makes a future move to the Anthropic API a one-module
change.

TODO (Phase 1): implement `complete(prompt, ...)` calling the Claude Code CLI.
"""
