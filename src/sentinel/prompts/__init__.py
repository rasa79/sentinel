#  LEARN[16]: prompt design for weak models — schema-in-prompt + few-shot + repair loop (QS-4
# cross-ref)
# Why this way: every LLM-backed prompt embeds an explicit JSON schema block, one worked few-shot
#   example, and a "respond with JSON only" instruction, then routes through the repair loop
#   (see LEARN[04]). This is defense in depth for small local models.
# Good sides:
#   - a schema block gives the model the exact shape, so prompt-and-parse (LEARN[04]) has a target
#   - few-shot examples stabilize small models that over-improvise structure on a bare instruction
#   - the repair loop catches and fixes format slips rather than failing the run
# Drawbacks:
#    - inlining the schema duplicates the Pydantic model in prose, so they can drift if edited by
#   hand
#   - few-shot tokens inflate the request; too many examples confuse a small model
#   - prompt versioning is manual and easy to forget (hence PROMPT_VERSION per module)
#  Concept: a small model is brittle about FORMAT — it may return prose, a list, or drop a required
# key.
#    Three mechanical techniques reduce that. (1) Put the JSON Schema in the prompt so the model
#   sees the
#    target shape (the schema block mirrors the Pydantic model exactly; a drift-guard test keeps
#   them in
#   sync). (2) Show one worked input->output example so the model can imitate structure rather than
#   invent it — the single most effective lever on a small model, because imitation is easier than
#    reasoning about an abstract instruction. (3) Route through the uniform validate+repair loop, so
#   a
#    format slip becomes a repair turn rather than a hard failure. This is the same defense in depth
#   a
#    Java engineer sees as schema validation + a migration guard + a retry wrapper: the layers each
#   cover
#    a different failure. Prompt versioning (PROMPT_VERSION) lets you change wording and still
#   compare
#    behaviour between prompt versions, exactly like versioning a template that feeds a stable
#   parser.
#    See LEARN[04] for the D1 structured-output loop; this comment adds only the prompt-side
#   technique.
# See also: LEARN[04] (structured output loop), the per-prompt design comments in this package
"""Versioned LLM prompt builders for the Sentinel agent (PLAN.md Task 3.2).

Each sub-module exports a ``PROMPT_VERSION``, a hard-coded JSON schema block that mirrors a
Pydantic model (kept in sync by ``tests/unit/test_prompts.py``), and a ``build_*_prompt(...)``
function. See LEARN[16] for why the schema block + few-shot + repair loop are used.
"""
