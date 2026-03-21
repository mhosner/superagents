"""FindingsRouter — routes QA findings to responsible personas.

Produces a JSON routing manifest classifying each Required Fix from the
validation report to exactly one persona (product_manager, architect, or
developer) with verbatim acceptance criterion text for self-contained
revision briefs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior QA engineer routing findings to the persona responsible \
for fixing each issue. Your output is ONLY valid JSON — no preamble, no \
explanation, no markdown fences.

## Root cause classification rules

Route each finding to exactly one persona based on root cause:

- **product_manager**: Acceptance criteria are vague, contradictory, or \
missing. The requirement itself is the problem.
- **architect**: The technical specification never defined a constraint, \
missed a component, or has a design flaw (e.g., race condition, missing \
caching layer). Even if the implementation plan also missed it, route to \
architect if the spec gap is the root cause.
- **developer**: The specification defines the requirement correctly but \
the code plan doesn't implement it, implements it incorrectly, or is \
missing test coverage for it.

## Examples

- Spec never mentions caching but AC requires <200ms response → architect
- Spec defines caching but code plan has no cache implementation → developer
- AC says "handles concurrent updates" but doesn't define expected behavior → product_manager
- Spec has race condition in transaction design → architect
- Spec defines transaction correctly but code plan uses read-before-write → developer

## Output schema

{
  "certification": "<certification from validation report>",
  "total_findings": <integer>,
  "routing": {
    "product_manager": [<findings>],
    "architect": [<findings>],
    "developer": [<findings>]
  }
}

Each finding object:
{
  "id": "RF-<N>",
  "summary": "One sentence description",
  "detail": "Full finding text from the validation report",
  "affected_artifact": "<prd | user_story | tech_spec | implementation_plan | code_plan>",
  "related_requirements": [
    {"id": "<requirement ID>", "text": "Exact acceptance criterion text from user stories"}
  ]
}
"""

_REQUIRED_FIELDS = {"id", "summary", "detail", "affected_artifact", "related_requirements"}


def _validate_manifest(data: dict[str, Any]) -> None:
    """Light validation of the routing manifest structure.

    Args:
        data: Parsed JSON manifest.

    Raises:
        ValueError: If required keys or fields are missing.
    """
    for key in ("certification", "total_findings", "routing"):
        if key not in data:
            msg = f"Routing manifest missing required key: {key}"
            raise ValueError(msg)

    routing = data["routing"]
    for persona in ("product_manager", "architect", "developer"):
        if persona not in routing:
            msg = f"Routing manifest missing required key: routing.{persona}"
            raise ValueError(msg)
        for finding in routing[persona]:
            missing = _REQUIRED_FIELDS - set(finding.keys())
            if missing:
                fid = finding.get("id", "?")
                fields = ", ".join(sorted(missing))
                msg = f"Finding {fid} missing required field: {fields}"
                raise ValueError(msg)


class FindingsRouter(BaseSkill):
    """Route QA findings to the persona responsible for fixing each issue."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the routing manifest.
        """
        self._llm = llm
        super().__init__(
            name="findings_router",
            description=(
                "Route QA findings to responsible personas with "
                "verbatim acceptance criteria for revision briefs"
            ),
            required_context=["validation_report", "user_stories"],
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
        """Generate a routing manifest from the validation report.

        Args:
            context: Execution context with validation_report and user_stories.

        Returns:
            Artifact pointing to the routing manifest JSON file.

        Raises:
            ValueError: If the LLM response is not valid JSON or fails
                structural validation.
        """
        params = context.parameters

        prompt_parts = [
            f"## Validation report\n{params['validation_report']}",
            f"## User stories\n{params['user_stories']}",
        ]

        if "tech_spec" in params:
            prompt_parts.append(f"## Technical specification\n{params['tech_spec']}")
        if "code_plan" in params:
            prompt_parts.append(f"## Code plan\n{params['code_plan']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        # Strip markdown fences if the LLM wraps JSON in ```json blocks
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        try:
            manifest = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse routing manifest as JSON: {exc}"
            raise ValueError(msg) from exc

        _validate_manifest(manifest)

        output_path = context.artifact_dir / "routing_manifest.json"
        output_path.write_text(json.dumps(manifest, indent=2))

        return Artifact(
            path=str(output_path),
            artifact_type="routing_manifest",
            metadata={"total_findings": str(manifest["total_findings"])},
        )
