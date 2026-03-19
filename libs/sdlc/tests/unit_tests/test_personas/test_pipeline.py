"""End-to-end pipeline tests: PM → Architect → Developer → QA.

Full stack with StubLLMClient as the only fake. Real PolicyEngine,
InProcessTransport, PersonaRegistry, and telemetry.
"""

from __future__ import annotations

from pathlib import Path

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.personas.product_manager import ProductManagerPersona
from superagents_sdlc.personas.qa import QAPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate, MockApprovalGate
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.skills.llm import StubLLMClient


def _make_pipeline_llm() -> StubLLMClient:
    """StubLLMClient with canned responses for all skills across all personas.

    Keys use exact prompt section headers to avoid substring collisions.
    """
    return StubLLMClient(
        responses={
            # PM skills
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            # Architect skills
            "## PRD\n": "# Tech Spec\n## Architecture\nMicroservices with REST API",
            "## Technical specification\n": ("## Tasks\n1. Create model\n2. Build API\n3. Add UI"),
            # Developer skills
            "## Implementation plan\n": (
                "## Task 1: DarkModeToggle\n"
                "### RED\ntest_toggle_switches_theme\n"
                "### GREEN\ndef toggle(): pass"
            ),
            # QA skills
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nTotal: 2 | Pass: 1 | Fail: 1\n"
                "Overall: NEEDS WORK"
            ),
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage.\n"
                "## Certification\nNEEDS WORK"
            ),
        }
    )


def _make_pipeline(
    tmp_path: Path,
    *,
    autonomy_level: int = 2,
    gate=None,
) -> tuple[ProductManagerPersona, ArchitectPersona, DeveloperPersona, StubLLMClient]:
    """Wire up the full PM → Architect → Developer pipeline."""
    stub_llm = _make_pipeline_llm()
    if gate is None:
        gate = AutoApprovalGate()
    config = PolicyConfig(autonomy_level=autonomy_level)
    engine = PolicyEngine(config=config, gate=gate)
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    pm = ProductManagerPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    architect = ArchitectPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    developer = DeveloperPersona(llm=stub_llm, policy_engine=engine, transport=transport)

    registry.register(pm)
    registry.register(architect)
    registry.register(developer)

    return pm, architect, developer, stub_llm


async def _run_full_pipeline(
    tmp_path: Path,
    pm: ProductManagerPersona,
    architect: ArchitectPersona,
    developer: DeveloperPersona,
) -> tuple[list, list, list]:
    """Run PM → Architect → Developer and return all artifact lists."""
    # PM phase
    pm_context = SkillContext(
        artifact_dir=tmp_path / "pm",
        parameters={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects, hates eye strain",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "pm").mkdir()
    pm_artifacts = await pm.run_idea_to_sprint("Add dark mode", pm_context)

    # Adapter: mount PM outputs into Architect context
    prd_content = Path(pm_artifacts[1].path).read_text()
    arch_context = SkillContext(
        artifact_dir=tmp_path / "architect",
        parameters={
            "prd": prd_content,
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "architect").mkdir()

    arch_handoff = architect.received[-1]
    arch_artifacts = await architect.handle_handoff(arch_handoff, arch_context)

    # Developer: handle handoff from architect
    dev_context = SkillContext(
        artifact_dir=tmp_path / "developer",
        parameters={},
        trace_id="trace-pipeline",
    )
    (tmp_path / "developer").mkdir()

    dev_handoff = developer.received[-1]
    dev_artifacts = await developer.handle_handoff(dev_handoff, dev_context)

    return pm_artifacts, arch_artifacts, dev_artifacts


async def test_pipeline_pm_to_architect_to_developer(exporter, tmp_path):
    pm, architect, developer, stub_llm = _make_pipeline(tmp_path)

    pm_artifacts, arch_artifacts, dev_artifacts = await _run_full_pipeline(
        tmp_path, pm, architect, developer
    )

    all_artifacts = pm_artifacts + arch_artifacts + dev_artifacts
    assert len(all_artifacts) == 6
    types = [a.artifact_type for a in all_artifacts]
    assert types == [
        "backlog",
        "prd",
        "user_story",
        "tech_spec",
        "implementation_plan",
        "code",
    ]

    # Verify tech spec content reached Developer's code_planner prompt via metadata
    dev_prompt = stub_llm.calls[-1][0]
    assert "Microservices" in dev_prompt or "REST API" in dev_prompt


async def test_pipeline_emits_three_persona_spans(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    persona_names = {s.name for s in spans if s.name.startswith("persona.")}
    assert "persona.product_manager" in persona_names
    assert "persona.architect" in persona_names
    assert "persona.developer" in persona_names


async def test_pipeline_handoff_chain(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    sources_targets = [
        (s.attributes["handoff.source"], s.attributes["handoff.target"]) for s in handoff_spans
    ]
    assert ("product_manager", "architect") in sources_targets
    assert ("architect", "developer") in sources_targets


async def test_pipeline_level_2_planning_auto_proceeds(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path, autonomy_level=2)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    for gs in gate_spans:
        assert gs.attributes["approval.outcome"] == "auto_proceeded"


async def test_pipeline_level_1_all_handoffs_require_approval(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(
        tmp_path, autonomy_level=1, gate=MockApprovalGate(should_approve=True)
    )

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    for gs in gate_spans:
        assert gs.attributes["approval.required"] is True
        assert gs.attributes["approval.outcome"] == "approved"


# -- Phase 5: PM → Architect → Developer → QA pipeline --


def _make_pipeline_with_qa(
    tmp_path: Path,
    *,
    autonomy_level: int = 2,
    gate=None,
) -> tuple[
    ProductManagerPersona,
    ArchitectPersona,
    DeveloperPersona,
    QAPersona,
    StubLLMClient,
]:
    """Wire up the full PM → Architect → Developer → QA pipeline."""
    stub_llm = _make_pipeline_llm()
    if gate is None:
        gate = AutoApprovalGate()
    config = PolicyConfig(autonomy_level=autonomy_level)
    engine = PolicyEngine(config=config, gate=gate)
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    pm = ProductManagerPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    architect = ArchitectPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    developer = DeveloperPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    qa = QAPersona(llm=stub_llm, policy_engine=engine, transport=transport)

    registry.register(pm)
    registry.register(architect)
    registry.register(developer)
    registry.register(qa)

    return pm, architect, developer, qa, stub_llm


async def _run_full_pipeline_with_qa(
    tmp_path: Path,
    pm: ProductManagerPersona,
    architect: ArchitectPersona,
    developer: DeveloperPersona,
    qa: QAPersona,
) -> tuple[list, list, list, list]:
    """Run PM → Architect → Developer → QA and return all artifact lists."""
    # PM phase
    pm_context = SkillContext(
        artifact_dir=tmp_path / "pm",
        parameters={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects, hates eye strain",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "pm").mkdir()
    pm_artifacts = await pm.run_idea_to_sprint("Add dark mode", pm_context)

    # Adapter: mount PM outputs into Architect context
    prd_content = Path(pm_artifacts[1].path).read_text()
    arch_context = SkillContext(
        artifact_dir=tmp_path / "architect",
        parameters={
            "prd": prd_content,
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "architect").mkdir()
    arch_handoff = architect.received[-1]
    arch_artifacts = await architect.handle_handoff(arch_handoff, arch_context)

    # Developer: handle handoff from architect
    dev_context = SkillContext(
        artifact_dir=tmp_path / "developer",
        parameters={},
        trace_id="trace-pipeline",
    )
    (tmp_path / "developer").mkdir()
    dev_handoff = developer.received[-1]
    dev_artifacts = await developer.handle_handoff(dev_handoff, dev_context)

    # QA: handle handoff from developer
    qa_context = SkillContext(
        artifact_dir=tmp_path / "qa",
        parameters={},
        trace_id="trace-pipeline",
    )
    (tmp_path / "qa").mkdir()
    qa_handoff = qa.received[-1]
    qa_artifacts = await qa.handle_handoff(qa_handoff, qa_context)

    return pm_artifacts, arch_artifacts, dev_artifacts, qa_artifacts


async def test_pipeline_pm_to_qa(exporter, tmp_path):
    pm, architect, developer, qa, stub_llm = _make_pipeline_with_qa(tmp_path)

    pm_art, arch_art, dev_art, qa_art = await _run_full_pipeline_with_qa(
        tmp_path, pm, architect, developer, qa
    )

    all_artifacts = pm_art + arch_art + dev_art + qa_art
    assert len(all_artifacts) == 8
    types = [a.artifact_type for a in all_artifacts]
    assert types == [
        "backlog",
        "prd",
        "user_story",
        "tech_spec",
        "implementation_plan",
        "code",
        "compliance_report",
        "validation_report",
    ]

    # Verify tech spec content reached QA's compliance checker prompt via metadata
    qa_prompts = [c[0] for c in stub_llm.calls if "## Code plan\n" in c[0]]
    assert len(qa_prompts) >= 1


async def test_pipeline_emits_four_persona_spans(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    persona_names = {s.name for s in spans if s.name.startswith("persona.")}
    assert "persona.product_manager" in persona_names
    assert "persona.architect" in persona_names
    assert "persona.developer" in persona_names
    assert "persona.qa" in persona_names


async def test_pipeline_four_persona_handoff_chain(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    sources_targets = [
        (s.attributes["handoff.source"], s.attributes["handoff.target"]) for s in handoff_spans
    ]
    assert ("product_manager", "architect") in sources_targets
    assert ("architect", "developer") in sources_targets
    assert ("developer", "qa") in sources_targets


async def test_pipeline_level_2_code_handoff_requires_approval(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(
        tmp_path, autonomy_level=2, gate=MockApprovalGate(should_approve=True)
    )

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    # Developer→QA handoff carries code artifact → requires approval at L2
    dev_to_qa = [gs for gs in gate_spans if "developer_to_qa" in gs.name]
    assert len(dev_to_qa) == 1
    assert dev_to_qa[0].attributes["approval.required"] is True
    assert dev_to_qa[0].attributes["approval.outcome"] == "approved"

    # PM→Architect and Architect→Developer carry planning artifacts → auto-proceed
    planning_gates = [gs for gs in gate_spans if "developer_to_qa" not in gs.name]
    for pg in planning_gates:
        assert pg.attributes["approval.outcome"] == "auto_proceeded"


async def test_pipeline_metadata_reaches_qa(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    # Verify QA received a handoff with metadata containing upstream paths
    assert len(qa.received) == 1
    meta = qa.received[0].metadata
    assert "tech_spec_path" in meta
    assert meta["tech_spec_path"] != ""
