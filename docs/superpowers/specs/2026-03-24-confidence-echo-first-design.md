# Stop Confidence Assessment Hallucinating Decisions — Design Spec

## Problem

The confidence assessment LLM consistently misreads or fabricates user decisions. Despite the "DECIDED" framing from the previous fix, the LLM latches onto background context and synthesizes its own conclusions rather than reading the actual transcript. Examples:

- User chose "Discovery artifacts with extension point" → assessment says "event subscriptions only"
- User chose "Human-decided, flag cycles" → assessment says "auto-merge cyclic slices"
- Assessment fabricated "Claude writes overrides to JSON" — never discussed

The hallucinations propagate through question generation, approaches, and section writing because all nodes consume the same transcript.

## Root Cause

1. The assessment prompt has a lot of context (idea, codebase context, product context via cached_prefix, plus transcript). The LLM reasons about what makes architectural sense rather than reading what was decided.
2. The "evidence" field in the assessment JSON is unconstrained — the LLM synthesizes and paraphrases, encoding hallucinations as evidence that later nodes treat as authoritative.

## Approach

Inline echo-first instructions in each prompt template (Approach A). No new functions, no code changes to node logic — prompt template text only.

The key mechanism: force the LLM to echo decisions verbatim as chain-of-thought grounding before producing structured output. If it can't copy the text, it hasn't read it. The echo appears as prose before the JSON; `extract_json` already skips non-JSON preamble.

## Changes

### 1. Confidence assessment prompt (`confidence.py`)

Restructure `_ASSESSMENT_PROMPT` into two explicit steps:

**Step 1** (echo): The LLM must write out each decision verbatim before its JSON response. Framed as "Step 1: Write out each decision verbatim (before your JSON)". This is chain-of-thought grounding — no parsing required.

**Step 2** (assess): The existing section rating task, but with critical rules added:

- Do NOT infer decisions the user did not make
- Do NOT extend a decision beyond its literal text
- Do NOT combine or synthesize multiple decisions into a new conclusion
- If a decision directly answers a gap, that gap is closed
- Only reference decisions that appear in the "Decisions Made So Far" section

**Evidence field constraint**: For each section's evidence, quote ONLY from the Decisions Made block. Do not synthesize, interpret, or extend. If no decision addresses this section, write "No decision made yet."

### 2. Question generation prompt (`prompts.py` — `QUESTION_PROMPT`)

Add after the decisions block, before the task instructions:

"Before generating questions, list each decision the user has made. Do not generate questions that contradict or re-ask these decisions."

### 3. Approaches prompt (`prompts.py` — `APPROACHES_PROMPT`)

Add after the decisions block, before the task instructions:

"Before proposing approaches, list each decision. All approaches must be consistent with every listed decision."

### 4. Design section prompt (`prompts.py` — `DESIGN_SECTION_PROMPT`)

Add after the decisions block, before the task instructions:

"Before writing this section, list each relevant decision. The section content must reflect these decisions exactly."

### 5. Synthesize prompt (`prompts.py` — `SYNTHESIZE_PROMPT`)

Lightest touch — works from approved sections, not raw transcript. Add:

"Before synthesizing, list all decisions from the brainstorm session. The brief must incorporate every decision."

Note: `SYNTHESIZE_PROMPT` currently does not include the transcript. Adding this instruction requires also adding `{transcript}` with the formatted decisions block to the template, and wiring it in `make_synthesize_brief_node`. This is the one template that needs a small code change in addition to prompt text.

## What Does NOT Change

- Node function logic in `nodes.py` and `confidence.py` (except synthesize wiring if transcript added)
- `_format_transcript_for_assessment()` function
- Transcript data schema
- CLI code
- `_build_brainstorm_cached_prefix()` or caching logic
- Confidence scoring math

## Tests

### Prompt content tests (4 tests)

- `test_confidence_prompt_requires_echo_step` — assert "Write out each decision verbatim" and "before your JSON" appear in the assembled prompt
- `test_confidence_prompt_contains_critical_rules` — assert "Do NOT infer" and "Do NOT extend" and "Do NOT combine" in prompt
- `test_confidence_prompt_evidence_quote_only` — assert "quote ONLY from the Decisions Made" in prompt
- `test_all_node_prompts_contain_echo_instruction` — assert each of QUESTION_PROMPT, APPROACHES_PROMPT, DESIGN_SECTION_PROMPT, SYNTHESIZE_PROMPT contains "list each decision" or equivalent

### TDD order

1. Echo-first Step 1/Step 2 + critical rules in confidence prompt + 3 tests
2. Evidence field constraint in confidence prompt + 1 test
3. Echo instructions in all 4 remaining node prompts + 1 test
4. Full test suite pass
