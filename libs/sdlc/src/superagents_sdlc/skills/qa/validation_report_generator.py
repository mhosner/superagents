"""ValidationReportGenerator — readiness certification skill.

Produces a structured certification report with honest quality ratings.
Default rating is NEEDS WORK — READY requires overwhelming evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior QA lead producing a readiness certification. Your default \
rating is NEEDS WORK. READY requires overwhelming evidence of coverage. \
No A+ fantasies on first attempts.

## Required output structure

1. **Executive summary** — One-paragraph honest assessment
2. **Compliance results** — Summary of the compliance checker's findings
3. **Risk assessment** — What could go wrong if we proceed
4. **Required fixes** — Must-fix items before proceeding (if any)
5. **Recommended improvements** — Nice-to-have items
6. **Certification** — The final line of your response MUST be exactly one of \
these three ratings on its own line, with no text after it. Choose carefully — \
this determines whether the automated retry loop fires:
   - **READY**: All requirements have corresponding implementation tasks with \
verification steps. Risks are identified and mitigated. Clear to hand to an \
executing agent.
   - **NEEDS WORK**: The plan has gaps that can be fixed by adding, modifying, \
or expanding tasks. Examples: missing implementation tasks for specified \
components, missing test cases for acceptance criteria, incomplete verification \
steps, integration points described but not tasked. These are completeness gaps, \
not design failures. The automated retry will attempt to fix them.
   - **FAILED**: The plan has fundamental problems that cannot be fixed by adding \
tasks. Examples: the architecture contradicts the requirements, the tech spec is \
internally inconsistent, acceptance criteria are mutually exclusive, the chosen \
approach cannot satisfy a hard constraint. Use FAILED only when the plan needs \
to be redesigned, not just completed.

When in doubt between NEEDS WORK and FAILED, choose NEEDS WORK. Most plans with \
missing tasks are incomplete, not wrong. FAILED should be rare.
"""

# Ordered by ascending severity; last match wins in _extract_certification.
_CERTIFICATIONS = ("READY", "NEEDS WORK", "FAILED")


def _extract_certification(response: str) -> str:
    """Extract certification rating from the tail of the report response.

    Scans only the last 10 lines (where the Certification section lives per
    the system prompt's output structure) to avoid matching stray occurrences
    in the compliance results body. Checks READY, NEEDS WORK, FAILED in
    priority order — FAILED wins if multiple are present.

    When no explicit certification is found but the response contains a
    "Required Fixes" section with items, infers "NEEDS WORK" to unblock
    the pipeline loop.

    Args:
        response: Raw LLM response text.

    Returns:
        Certification string or "unknown" if not found.
    """
    tail = "\n".join(response.splitlines()[-10:])
    found = "unknown"
    # Iterates ascending severity; last match wins (FAILED > NEEDS WORK > READY)
    for cert in _CERTIFICATIONS:
        if cert in tail:
            found = cert
    if found == "unknown" and _has_required_fixes(response):
        return "NEEDS WORK"
    return found


def _has_required_fixes(response: str) -> bool:
    """Check whether the response contains a Required Fixes section with items.

    Args:
        response: Raw LLM response text.

    Returns:
        True if a Required Fixes heading is followed by list items.
    """
    lines = response.splitlines()
    in_fixes = False
    for line in lines:
        stripped = line.strip()
        if "required fixes" in stripped.lower():
            in_fixes = True
            continue
        if in_fixes:
            if stripped.startswith("- "):
                return True
            if stripped.startswith("#"):
                in_fixes = False
    return False


class ValidationReportGenerator(BaseSkill):
    """Generate a readiness certification with honest quality ratings."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the validation report.
        """
        self._llm = llm
        super().__init__(
            name="validation_report_generator",
            description=(
                "Generate a structured readiness certification with "
                "honest quality ratings and required fixes"
            ),
            required_context=["compliance_report", "code_plan", "user_stories"],
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
        """Generate a validation report from compliance results.

        Args:
            context: Execution context with compliance report and code plan.

        Returns:
            Artifact pointing to the validation report.
        """
        params = context.parameters

        prompt_parts = [
            f"## Compliance report\n{params['compliance_report']}",
            f"## Code plan\n{params['code_plan']}",
            f"## User stories\n{params['user_stories']}",
        ]

        if "tech_spec" in params:
            prompt_parts.append(f"## Technical specification\n{params['tech_spec']}")
        if "implementation_plan" in params:
            prompt_parts.append(f"## Implementation plan\n{params['implementation_plan']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "validation_report.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="validation_report",
            metadata={"certification": _extract_certification(response)},
        )
