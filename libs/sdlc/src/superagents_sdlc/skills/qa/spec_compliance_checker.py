"""SpecComplianceChecker — gap analysis between specs and implementation artifacts.

Defaults to skepticism: identifies minimum 3-5 issues even on solid plans.
Structured PASS/FAIL per requirement with exact spec text citations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError
from superagents_sdlc.skills.engineering.plan_parser import extract_tasks, summarize_plan

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior QA engineer performing a compliance review. Your default \
stance is skepticism — assume NEEDS WORK until proven otherwise.

## Review methodology

For each user story and spec requirement:
1. **Quote** the exact spec text
2. **Quote** the corresponding code plan section (or note "NOT FOUND")
3. **Verdict**: PASS / FAIL / PARTIAL with brief justification

## Mandatory checks

- Every user story must have a corresponding implementation task
- Every implementation task must trace back to a requirement
- Acceptance criteria must have concrete verification steps (not vague)
- Identify minimum 3-5 risks, gaps, or ambiguities even on solid plans

## Automatic FAIL triggers

- Requirement with no corresponding implementation task
- Implementation task with no corresponding requirement
- Vague acceptance criteria without concrete verification

## Output structure

1. Per-requirement compliance table
2. Summary: total checks, pass count, fail count, partial count
3. Overall assessment: PASS / NEEDS WORK / FAIL
"""


class SpecComplianceChecker(BaseSkill):
    """Line-by-line gap analysis between specs and implementation artifacts."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the compliance report.
        """
        self._llm = llm
        super().__init__(
            name="spec_compliance_checker",
            description=(
                "Line-by-line gap analysis between specifications and "
                "implementation artifacts, defaulting to skepticism"
            ),
            required_context=["code_plan", "user_stories", "tech_spec"],
        )

    def validate(self, context: SkillContext) -> None:
        """Check that required context parameters are present.

        Args:
            context: Execution context to validate.

        Raises:
            SkillValidationError: If a required parameter is missing.
        """
        for key in self.required_context:
            if key not in context.parameters:
                msg = f"Missing required context parameter: {key}"
                raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        """Run compliance check against the code plan.

        Parses the code plan for structured task data, then composes
        a prompt with both quantitative summary and raw plan text.

        Args:
            context: Execution context with code plan, user stories, and tech spec.

        Returns:
            Artifact pointing to the compliance report.
        """
        params = context.parameters
        code_plan = params["code_plan"]

        # Parse plan for structured analysis
        tasks = extract_tasks(code_plan)
        summary = summarize_plan(tasks)

        prompt_parts = [
            summary,
            f"## Code plan\n{code_plan}",
            f"## User stories\n{params['user_stories']}",
            f"## Technical specification\n{params['tech_spec']}",
        ]

        if "implementation_plan" in params:
            prompt_parts.append(f"## Implementation plan\n{params['implementation_plan']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(
            prompt, system=_SYSTEM_PROMPT, cached_prefix=context.cached_prefix,
        )

        output_path = context.artifact_dir / "compliance_report.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="compliance_report",
            metadata={"framework": "spec_compliance"},
        )
