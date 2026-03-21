"""Tests for QA persona FindingsRouter integration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.qa import QAPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


async def test_qa_persona_runs_findings_router_on_needs_work(tmp_path: Path):
    """QA persona runs FindingsRouter when certification is NEEDS WORK."""
    manifest = json.dumps({
        "certification": "NEEDS WORK",
        "total_findings": 1,
        "routing": {
            "product_manager": [],
            "architect": [
                {
                    "id": "RF-1",
                    "summary": "Missing caching",
                    "detail": "Spec has no caching.",
                    "affected_artifact": "tech_spec",
                    "related_requirements": [
                        {"id": "S1-AC3", "text": "Under 200ms"},
                    ],
                },
            ],
            "developer": [],
        },
    })

    stub = StubLLMClient(
        responses={
            # Compliance checker
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
            ),
            # Validation report generator
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nGaps found.\n"
                "## Required Fixes\n- RF-1: Missing caching\n"
                "## Certification\nNEEDS WORK"
            ),
            # Findings router
            "## Validation report\n": manifest,
        }
    )

    config = PolicyConfig(autonomy_level=3)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    qa = QAPersona(llm=stub, policy_engine=engine, transport=transport)
    registry.register(qa)

    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1\n- [ ] Step 1",
            "user_stories": "## S1-AC3\nUnder 200ms",
            "tech_spec": "# Spec\nREST API",
        },
        trace_id="trace-1",
    )

    artifacts = await qa.run_validation(context)

    assert len(artifacts) == 3
    assert artifacts[2].artifact_type == "routing_manifest"
    assert (tmp_path / "routing_manifest.json").exists()


async def test_qa_persona_skips_router_on_ready(tmp_path: Path):
    """QA persona skips FindingsRouter when certification is READY."""
    stub = StubLLMClient(
        responses={
            "## Plan structure analysis\n": (
                "## Compliance Check\n| Feature | PASS |\n"
                "## Summary\nTotal: 1 | Pass: 1\nOverall: READY"
            ),
            "## Compliance report\n": (
                "# Validation Report\n## Executive Summary\nAll good.\n"
                "## Certification\nREADY"
            ),
        }
    )

    config = PolicyConfig(autonomy_level=3)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    qa = QAPersona(llm=stub, policy_engine=engine, transport=transport)
    registry.register(qa)

    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1\n- [ ] Step 1",
            "user_stories": "## S1-AC3\nUnder 200ms",
            "tech_spec": "# Spec\nREST API",
        },
        trace_id="trace-1",
    )

    artifacts = await qa.run_validation(context)

    assert len(artifacts) == 2
    assert all(a.artifact_type != "routing_manifest" for a in artifacts)
