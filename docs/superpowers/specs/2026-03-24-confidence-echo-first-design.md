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

Inline echo-first instructions in each prompt template. Prompt template text changes for 5 templates, plus a small wiring change in `make_synthesize_brief_node` to pass the formatted transcript to `SYNTHESIZE_PROMPT` (which currently doesn't receive it).

The key mechanism: force the LLM to echo decisions verbatim as chain-of-thought grounding before producing structured output. If it can't copy the text, it hasn't read it. The echo appears as prose before the JSON/markdown; `extract_json` already skips non-JSON preamble by scanning for the first `{` or `[`.

## Changes

### 1. Confidence assessment prompt (`confidence.py` — `_ASSESSMENT_PROMPT`)

Restructure into two explicit steps. Insert after `{transcript}` and before the section rating instructions:

```
Step 1: Write out each decision verbatim (before your JSON).
For each decision above, write: "Decision N: The user decided: [copy the DECIDED text exactly]"

Step 2: Produce your JSON assessment (consistent with Step 1).
Rate each section's readiness. Your ratings MUST be consistent with the decisions you echoed in Step 1.

CRITICAL RULES:
- Do NOT infer decisions the user did not make
- Do NOT extend a decision beyond its literal text
- Do NOT combine or synthesize multiple decisions into a new conclusion
- If a decision directly answers a gap, that gap is closed — do not list it as a gap
- Only reference decisions that appear in the "Decisions Made So Far" section above
```

Update the JSON schema instruction for the evidence field:

```
For the "evidence" field: quote ONLY from the Decisions Made block above. \
Do not synthesize, interpret, or extend. If no decision addresses this \
section, write "No decision made yet."
```

### 2. Question generation prompt (`prompts.py` — `QUESTION_PROMPT`)

Insert immediately after `{transcript}`, before `## Current section readiness`:

```
Before generating questions, list each decision the user has made. \
Do not generate questions that contradict or re-ask these decisions.
```

### 3. Approaches prompt (`prompts.py` — `APPROACHES_PROMPT`)

Insert immediately after `{transcript}`, before `Propose 2-3 distinct`:

```
Before proposing approaches, list each decision the user has made. \
All approaches must be consistent with every listed decision.
```

### 4. Design section prompt (`prompts.py` — `DESIGN_SECTION_PROMPT`)

Insert immediately after `{transcript}`, before `## Previously approved sections`:

```
Before writing this section, list each decision the user has made. \
The section content must reflect these decisions exactly.
```

### 5. Synthesize prompt (`prompts.py` — `SYNTHESIZE_PROMPT`)

`SYNTHESIZE_PROMPT` currently does NOT include `{transcript}`. Two changes needed:

**Template change** — add a decisions block before the existing `## Approved design sections`:

```
## Decisions Made So Far

The following decisions have been confirmed by the user during this brainstorm \
session. These are FINAL — do not contradict, reinterpret, or question them. \
The brief must incorporate every decision.

{transcript}

Before synthesizing, list each decision the user has made.
```

**Node wiring change** — in `make_synthesize_brief_node` in `nodes.py`, add `transcript=_format_transcript_for_assessment(state["transcript"])` to the `SYNTHESIZE_PROMPT.format()` call.

## What Does NOT Change

- Node function logic in `confidence.py` or `nodes.py` (except the synthesize `.format()` call)
- `_format_transcript_for_assessment()` function
- Transcript data schema
- CLI code
- `_build_brainstorm_cached_prefix()` or caching logic
- Confidence scoring math

## Tests

### Prompt content tests (5 tests)

- `test_confidence_prompt_requires_echo_step` — assert the assembled confidence prompt contains "Write out each decision verbatim" and "before your JSON"
- `test_confidence_prompt_contains_critical_rules` — assert "Do NOT infer" and "Do NOT extend" and "Do NOT combine" all appear in the confidence prompt
- `test_confidence_prompt_evidence_quote_only` — assert "quote ONLY from the Decisions Made" in the confidence prompt
- `test_node_prompts_contain_echo_instruction` — assert each of `QUESTION_PROMPT`, `APPROACHES_PROMPT`, `DESIGN_SECTION_PROMPT`, `SYNTHESIZE_PROMPT` contains "list each decision"
- `test_synthesize_node_includes_transcript` — call `make_synthesize_brief_node`, invoke it with a known transcript, assert the prompt sent to the LLM contains the formatted decision text (use `_SpyLLMClient` to capture the prompt)

### TDD order

1. Echo-first Step 1/Step 2 + critical rules in confidence prompt + 3 tests
2. Evidence field constraint in confidence prompt (part of same template change)
3. Echo instructions in QUESTION_PROMPT, APPROACHES_PROMPT, DESIGN_SECTION_PROMPT + 1 test
4. SYNTHESIZE_PROMPT template + node wiring + 1 test
5. Full test suite pass
