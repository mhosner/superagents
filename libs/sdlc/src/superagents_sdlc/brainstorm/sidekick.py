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


SKILLS: list[SidekickSkill] = [
    SidekickSkill(
        key="1",
        name="Pros & cons",
        description="Analyze tradeoffs for each option",
        prompt_template=PROS_CONS_PROMPT,
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
