"""Brainstorm sidekick — callout skills for the ? menu.

Provides thinking tools (pros/cons, etc.) that run an LLM call with the
current brainstorm context and display the result. The graph never knows
these calls happened — they're advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superagents_sdlc.skills.llm import LLMClient

SIDEKICK_SYSTEM = (
    "You are a brainstorming advisor helping someone think through a design decision. "
    "Be concise, specific, and balanced. Your job is to help them think clearly, "
    "not to make the decision for them. "
    "Use plain language. Avoid jargon unless the question is technical."
)

PROS_CONS_PROMPT = """\
The user is brainstorming a product idea and has reached a decision point.

## Their idea
{idea}

## The question
{question_text}

## Options
{options_formatted}

## What's been decided so far
{decisions_so_far}

{approach_context}

Analyze the pros and cons of each option in the context of this specific project. \
Consider how each option interacts with decisions already made. \
Be specific — reference the idea and prior decisions, don't give generic advice.

Format as:

### [Option name]
**Pros:** [2-3 specific advantages for this project]
**Cons:** [2-3 specific disadvantages or risks for this project]
**Best when:** [one-sentence scenario where this is the right call]

Keep it concise. The user needs to make a decision, not read an essay.
"""


@dataclass
class SidekickSkill:
    """A callout skill available from the ? menu."""

    key: str
    name: str
    description: str
    prompt_template: str


@dataclass
class SidekickContext:
    """Context available to callout skills."""

    idea: str
    question_text: str
    options: list[str] | None
    targets_section: str
    decisions_so_far: str
    selected_approach: str
    product_context: str


OUTSIDE_BOX_PROMPT = """\
The user is brainstorming a product idea and has reached a decision point. \
The options presented may not cover every possibility. Suggest a creative \
alternative that isn't on the list.

## Their idea
{idea}

## The question
{question_text}

## Current options
{options_formatted}

## What's been decided so far
{decisions_so_far}

{approach_context}

Propose one alternative option that isn't listed above. It should be:
- Genuinely different from the existing options, not a hybrid or tweak
- Realistic and implementable in the context of this project
- Consistent with decisions already made in IdeaMemory

Format as:

### [Your proposed option]
**What it is:** [2-3 sentence description]
**Why consider it:** [specific advantage for this project that the listed options don't offer]
**The catch:** [honest tradeoff or risk]

Then briefly explain why the existing options might have missed this angle.

Keep it to one strong suggestion. The user doesn't need a brainstorm within a brainstorm.
"""

CONSEQUENCES_PROMPT = """\
The user is brainstorming a product idea and is about to make a decision. \
Help them think about second-order effects — what this choice forces, \
enables, or closes off downstream.

## Their idea
{idea}

## The question
{question_text}

## Options being considered
{options_formatted}

## What's been decided so far
{decisions_so_far}

{approach_context}

For each option (or for the decision space if open-ended), identify 2-3 \
downstream consequences the user might not be considering. Focus on:
- What this choice **forces** later (constraints it creates)
- What this choice **closes off** (options it eliminates)
- What this choice **enables** (opportunities it opens)

Reference specific prior decisions from IdeaMemory where relevant — \
show how this choice interacts with what's already been decided.

Format as:

### [Option name]
- **Forces:** [consequence that becomes unavoidable]
- **Closes off:** [option or approach that becomes impractical]
- **Enables:** [opportunity or simplification that becomes possible]

Be specific to this project. Generic advice like "adds complexity" is not helpful. \
Name the specific components, workflows, or user experiences affected.

Keep each option to 3 bullets maximum. Concise and actionable.
"""

SKILLS: list[SidekickSkill] = [
    SidekickSkill(
        key="1",
        name="Pros & cons",
        description="Analyze tradeoffs for each option",
        prompt_template=PROS_CONS_PROMPT,
    ),
    SidekickSkill(
        key="2",
        name="Outside the box",
        description="Suggest an option not on the list",
        prompt_template=OUTSIDE_BOX_PROMPT,
    ),
    SidekickSkill(
        key="3",
        name="Unforeseen consequences",
        description="Downstream implications of this choice",
        prompt_template=CONSEQUENCES_PROMPT,
    ),
]


async def run_sidekick_skill(
    skill: SidekickSkill,
    context: SidekickContext,
    llm: LLMClient,
) -> str:
    """Run a callout skill and return the formatted result.

    Args:
        skill: The skill to execute.
        context: Current brainstorm context.
        llm: LLM client for the call.

    Returns:
        Formatted string to display to the user.
    """
    if context.options:
        options_formatted = "\n".join(f"- {opt}" for opt in context.options)
    else:
        options_formatted = (
            "This is an open-ended question — no predefined options. "
            "Help the user think about what dimensions matter for their answer."
        )

    approach_context = ""
    if context.selected_approach:
        approach_context = f"## Selected approach\n{context.selected_approach}"

    prompt = skill.prompt_template.format(
        idea=context.idea,
        question_text=context.question_text,
        options_formatted=options_formatted,
        decisions_so_far=context.decisions_so_far or "(nothing decided yet)",
        approach_context=approach_context,
    )

    return await llm.generate(prompt, system=SIDEKICK_SYSTEM)
