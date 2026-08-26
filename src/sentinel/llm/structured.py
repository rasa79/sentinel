# LEARN[04]: uniform JSON→extract→validate→repair for structured LLM output (deep-dive — D1)
# Why this way: every LLM-backed node funnels through one function that asks the model for a
#   JSON object matching a Pydantic schema, extracts it robustly, validates it, and on failure
#   re-prompts with the validation error (a "repair" turn), failing hard after a small retry
#   budget. We do NOT use with_structured_output/function-calling, because the weakest link must
#   be the 7B-class local model (here phi4-mini): it may not reliably emit tool calls, and
#   tool-calling support differs between cloud and local backends. One code path we can reason
#   about and test beats a feature we can't trust on the weakest provider.
# Good sides:
#   - identical behavior across cloud and local providers, so tests and evals are honest in both
#   - the Pydantic schema is the single contract; the model's text output never reaches the graph
#     unless it validated (no silent type drift / hallucinated keys)
#   - a repair turn recovers from small format slips instead of failing the run for a trivially
#     fixable answer, and the small retry budget keeps a runaway loop from hammering the model
# Drawbacks:
#   - prompt-and-parse is inherently more fragile than grammar-constrained decoding (which some
#     backends support); it burns extra tokens on each repair turn
#   - the parser must be robust to code fences, prose, and unbalanced braces — robustness we own
#   - a model that returns flatly wrong JSON after the budget escalates to the caller, which is
#     a hard failure rather than a best-effort guess (intentional, but surfaces as a failed node)
# Concept: "structured output" from an LLM is really three problems. (1) Grammar-constrained
#   decoding constrains sampling so only strings matching a grammar can be produced — powerful
#   but provider-specific. (2) Tool/function calling emits the structured call as a first-class
#   message the runtime hands you typed — also provider-specific and unreliable on small local
#   models. (3) Prompt-and-parse: you ask for JSON, then parse it yourself. For the weakest-link
#   requirement (D1) we pick (3): it works wherever the model can emit text (everywhere) and
#   degenerates gracefully. The repair loop is "trust but verify" for the LLM world: ask (initial
#   prompt + schema), verify (parse + Pydantic validate), and on failure hand the model its own
#   error and ask again (repair). MAX_RETRIES caps the loop so a degenerate model can't spin
#   forever. The schema is dumped to JSON and pasted into the prompt so the model sees the exact
#   shape, and because we validate against the *same* Pydantic model the contract can't drift
#   between the prompt and the parse. The extraction seam is what makes this robust: it strips
#   ``` fences and finds the first *balanced* {...} so surrounding prose and markdown don't break
#   the parse. A Java reader should see this as "deserialize with a schema + retry with the
#   deserialization error", analogous to a Jackson @JsonSchema validator loop.
# See also: LEARN[05] (single OpenAI-compatible client, D3), LEARN[03] (config layering)
from __future__ import annotations

import json
import re

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ValidationError

# Retry budget: the model is invoked up to MAX_RETRIES + 1 times (initial + repairs). This is a
# module constant — configuration only via code, per D1.
MAX_RETRIES = 2


class StructuredOutputError(Exception):
    """Raised when structured output cannot be produced after the repair retry budget is spent."""


def _strip_code_fences(text: str) -> str:
    """Remove a single ```json ... ``` (or bare ``` ... ```) fence if present."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return match.group(1) if match else text


def _extract_json_object(text: str) -> str | None:
    """Return the first *balanced* JSON object literal from ``text``, or ``None``.

    Walks character-by-character tracking brace depth and string state so a JSON object containing
    nested braces or ``{`` inside a string literal is not confused. This is what makes the parser
    tolerate surrounding prose and markdown.
    """
    text = _strip_code_fences(text).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _render_prompt(instruction: str, schema: type[BaseModel]) -> str:
    """Render the JSON-schema-in-prompt instruction (prompt-side technique via Phase 3 prompts)."""
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        instruction
        + "\n\nRespond with ONLY a single valid JSON object that conforms exactly to this JSON "
        + "Schema. Do not include any explanation, notes, or text outside the JSON object. Do not "
        + "wrap it in code fences.\n\nJSON Schema:\n```json\n"
        + schema_json
        + "\n```"
    )


def _invoke_str(model: BaseChatModel, prompt: str) -> str:
    """Invoke a chat model and coerce the response to a plain string."""
    result = model.invoke(prompt)
    content = result.content
    if isinstance(content, str):
        return content
    return str(content)


def _parse_and_validate[T: BaseModel](raw: str, schema: type[T]) -> tuple[T | None, str | None]:
    """Return ``(instance, None)`` on success else ``(None, reason)``."""
    obj = _extract_json_object(raw)
    if obj is None:
        return None, "No JSON object was found in the response."
    try:
        data = json.loads(obj)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    try:
        return schema.model_validate(data), None
    except ValidationError as exc:
        return None, f"Validation error: {exc}"


def structured_call[T: BaseModel](
    model: BaseChatModel,
    instruction: str,
    schema: type[T],
) -> T:
    """Get a validated ``schema``-typed object via the uniform JSON+repair loop (D1)."""
    failure_reason: str | None = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt == 0:
            prompt = _render_prompt(instruction, schema)
        else:
            prompt = (
                _render_prompt(instruction, schema)
                + "\n\nYour previous response was rejected for this reason:\n"
                + (failure_reason or "unknown error")
                + "\n\nFix it and return only the corrected JSON object."
            )
        raw = _invoke_str(model, prompt)
        instance, error = _parse_and_validate(raw, schema)
        if instance is not None:
            return instance
        failure_reason = error

    raise StructuredOutputError(
        f"Structured output failed after {MAX_RETRIES + 1} attempts. Last error: {failure_reason}"
    )
