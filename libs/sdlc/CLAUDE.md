# Superagents SDLC — Integration Architecture

> **This is `libs/sdlc/CLAUDE.md`.** The root `CLAUDE.md` in the monorepo root contains
> Superagents development standards (code quality, testing, commits, CLI). Both files
> are loaded by Claude Code when working in this directory. This file covers the
> integration-specific architecture, personas, and workflows.

## Vision

Build an agentic software development lifecycle framework that combines:
- **BMAD-style SDLC personas** as the enterprise-legible governance layer
- **Manna Ray PM skills** as the domain implementation behind persona facades
- **Superpowers TDD methodology** as the engineering execution engine
- **Deep Agents SDK** as the runtime and orchestrator
- **A2A Protocol** as the inter-agent communication contract
- **OpenTelemetry** as the observability backbone from day one

The goal: an adoption-gradient framework where enterprise teams can dial autonomy from "agents assist, humans decide" to "agents execute, humans approve at boundaries" — with every persona mapping to a real human role that owns the output.

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Autonomy Policy Layer                     │
│         (Level 1: assist → Level 2: hybrid → Level 3: auto) │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │    PM    │  │ Architect│  │   Dev    │  │    QA     │  │
│  │ Persona  │  │ Persona  │  │ Persona  │  │  Persona  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       │              │              │               │       │
│  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐  ┌─────▼─────┐  │
│  │Manna Ray │  │ Deep     │  │Superpwr  │  │ Layered   │  │
│  │PM Skills │  │ Agents   │  │TDD Cycle │  │ Testing   │  │
│  │(31 skills│  │ Skills   │  │(RED-GRN- │  │ (accept + │  │
│  │ ported)  │  │          │  │ REFACTOR)│  │  unit)    │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│              A2A Protocol (handoffs + discovery)             │
├─────────────────────────────────────────────────────────────┤
│              Deep Agents SDK (orchestration runtime)         │
├─────────────────────────────────────────────────────────────┤
│              OpenTelemetry (traces, spans, metrics)          │
└─────────────────────────────────────────────────────────────┘
```

## SDLC personas

Each persona maps to a human role in a traditional enterprise org. The human in that role is the approval authority at their autonomy level.

| Persona | Human Owner | Manna Ray Skills | Superpowers Phase |
|---------|-------------|-----------------|-------------------|
| Product Manager | PM / Product Owner | prd-generator, prioritization-engine, roadmap-builder, user-story-writer, backlog-prioritizer | brainstorming |
| Architect | Tech Lead / Principal Eng | technical-spec-writer, tech-debt-evaluator | brainstorming, writing-plans |
| Developer | Dev Team | (code generation) | TDD cycle, subagent-driven-development |
| QA | QA Lead | ab-test-designer, ab-test-analyzer, funnel-analyzer | test-driven-development, verification |
| Scrum Master | Scrum Master / EM | quarterly-planning-template, weekly-plan, daily-plan | executing-plans, finishing-a-development-branch |
| Stakeholder Proxy | Product Owner | stakeholder-simulator, executive-update-generator | requesting-code-review |

## Autonomy levels

### Level 1 — Assist
Agents draft artifacts. Humans review and approve each one before the next phase.
- PM Persona drafts PRD → human PM approves → Architect Persona drafts spec → human architect approves → ...
- Implementation is human-led with agent pair programming.
- All handoffs emit `approval_requested` telemetry events and block.

### Level 2 — Hybrid
Agents own planning artifacts with human approval gates at phase boundaries.
- PM Persona produces PRD through stories autonomously.
- Human approves the story batch, then Dev Persona runs Superpowers TDD cycle per story.
- Human reviews at story completion (code review gate).
- Handoffs emit `auto_proceeded` or `approval_requested` based on policy.

### Level 3 — Autonomous
Agents execute full Superpowers workflow (brainstorm → plan → subagent TDD → review).
- Humans approve at epic/sprint boundaries, not individual stories.
- Automated quality gates (test pass rate, review score) determine proceed/block.
- All decisions logged for audit.

## Handoff contract

Agent-to-agent handoffs follow A2A protocol semantics:
- Each persona publishes an **Agent Card** describing capabilities and accepted input.
- Handoffs carry typed metadata (reason, priority, source_artifact_path).
- Input filters control what conversation history the receiving persona sees.
- The autonomy policy layer intercepts every handoff to enforce approval gates.

Handoff artifact format (the contract between personas):
```python
class PersonaHandoff(BaseModel):
    """Typed, serializable handoff between SDLC personas.

    Must round-trip through model_dump_json() / model_validate_json().
    No Python object references in the payload.
    """
    source_persona: str          # e.g., "product_manager"
    target_persona: str          # e.g., "architect"
    artifact_type: str           # e.g., "prd", "tech_spec", "story"
    artifact_path: str           # filesystem path (str, not Path — must JSON-serialize)
    context_summary: str         # compressed context for the receiving persona
    autonomy_level: int          # 1, 2, or 3
    requires_approval: bool      # derived from autonomy policy
    trace_id: str                # OpenTelemetry trace ID
    parent_span_id: str          # for span parenting
```

## Telemetry

Every agent action emits OpenTelemetry spans. Non-negotiable from the start.

### Span hierarchy
```
trace: sdlc_workflow
  └── span: persona.product_manager.prd_generation
       ├── span: skill.prd_generator.execute
       ├── span: approval_gate.prd_review
       │    ├── attribute: autonomy_level=2
       │    ├── attribute: auto_approved=true
       │    └── attribute: gate_duration_ms=0
       └── span: handoff.pm_to_architect
            ├── attribute: artifact_type=prd
            └── attribute: target_persona=architect
```

### Required span attributes
- `persona.name` — which SDLC persona is acting
- `skill.name` — which underlying skill is executing
- `autonomy.level` — current policy level (1/2/3)
- `approval.required` — whether a human gate was hit
- `approval.outcome` — approved/rejected/auto_proceeded
- `artifact.type` — what was produced
- `handoff.source` / `handoff.target` — for inter-persona transfers

### Metrics to track from day one
- Time-to-approval per gate per autonomy level
- Skill execution duration
- Approval rejection rate by persona
- TDD cycle time (red → green → refactor)
- Subagent review pass rate (first attempt vs retry)

## Development workflow

This project follows the Superpowers methodology:

1. **Brainstorm before code** — Clarify what you're building. Save the design doc.
2. **Plan in small tasks** — 2-5 minute tasks with exact file paths and verification steps.
3. **RED-GREEN-REFACTOR** — Write the failing test first. Always. No exceptions.
4. **Subagent review** — Two-stage: spec compliance, then code quality.
5. **Finish cleanly** — Verify tests pass, present merge options, clean up.

## Tech stack

- **Runtime**: Python 3.12+
- **Package management**: uv
- **Testing**: pytest (asyncio_mode = "auto" — do NOT add `@pytest.mark.asyncio`)
- **Linting**: ruff
- **Type checking**: ty
- **Telemetry**: opentelemetry-api, opentelemetry-sdk (via superagents SDK)
- **LLM**: Anthropic API via `AnthropicLLMClient` (optional extra)
- **Brainstorm**: LangGraph StateGraph with `interrupt()` for HITL
- **CI**: GitHub Actions

## Project structure (current)

```
libs/superagents/                    # SDK (extended from upstream Deep Agents)
├── superagents/
│   └── telemetry/                   # OpenTelemetry instrumentation
│       ├── __init__.py              # Public API re-exports
│       ├── provider.py              # TracerProvider lifecycle
│       └── spans.py                 # Four span context managers
└── tests/unit_tests/test_telemetry/

libs/sdlc/                           # SDLC integration package
├── pyproject.toml
├── src/superagents_sdlc/
│   ├── brainstorm/                  # LangGraph brainstorm subgraph
│   │   ├── state.py                 # BrainstormState TypedDict (13 fields)
│   │   ├── nodes.py                 # Node factories (explore, question, coverage, approaches, design, synthesize)
│   │   ├── prompts.py               # Prompt templates for brainstorm nodes
│   │   └── graph.py                 # StateGraph assembly with interrupt/resume flow
│   ├── personas/                    # SDLC persona facades
│   │   ├── base.py                  # BasePersona ABC with telemetry, policy, transport
│   │   ├── product_manager.py       # PM persona (idea → PRD + stories + backlog)
│   │   ├── architect.py             # Architect persona (PRD → spec + plan)
│   │   ├── developer.py             # Developer persona (plan → code via TDD)
│   │   └── qa.py                    # QA persona (compliance + validation + findings routing)
│   ├── skills/                      # Skill implementations
│   │   ├── base.py                  # BaseSkill ABC + SkillContext + Artifact
│   │   ├── llm.py                   # LLMClient protocol + StubLLMClient + AnthropicLLMClient
│   │   ├── pm/                      # PrdGenerator, PrioritizationEngine, UserStoryWriter
│   │   ├── engineering/             # TechSpecWriter, ImplementationPlanner, CodePlanner, plan_parser
│   │   └── qa/                      # SpecComplianceChecker, ValidationReportGenerator, FindingsRouter
│   ├── policy/                      # Autonomy policy engine
│   │   ├── config.py                # PolicyConfig Pydantic model + YAML/env loaders
│   │   ├── gates.py                 # ApprovalGate protocol + Auto/Mock implementations
│   │   └── engine.py                # PolicyEngine (intercepts handoffs, enforces gates)
│   ├── handoffs/                    # A2A-shaped handoff implementation
│   │   ├── contract.py              # PersonaHandoff + HandoffResult Pydantic models
│   │   ├── transport.py             # Transport protocol + InProcessTransport
│   │   └── registry.py              # PersonaRegistry (lookup by name)
│   ├── workflows/                   # Pipeline orchestration
│   │   ├── orchestrator.py          # PipelineOrchestrator (run_idea_to_code, run_spec_from_prd, etc.)
│   │   ├── result.py                # PipelineResult dataclass with retry tracking
│   │   └── narrative.py             # NarrativeWriter (session narration to markdown)
│   └── cli.py                       # Standalone CLI (superagents-sdlc command)
└── tests/
    ├── unit_tests/
    │   ├── test_skills/
    │   ├── test_personas/
    │   ├── test_policy/
    │   ├── test_handoffs/
    │   ├── test_workflows/
    │   ├── test_brainstorm/
    │   └── test_cli.py
    └── integration_tests/
```

## Key dependencies

```toml
[project]
name = "superagents-sdlc"
dependencies = [
    "superagents",               # SDK with telemetry (editable install from ../superagents)
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "langgraph>=1.1.2,<2.0.0",  # brainstorm subgraph
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.40.0", "python-dotenv>=1.0.0"]

[project.scripts]
superagents-sdlc = "superagents_sdlc.cli:main"
```

Telemetry lives in the superagents SDK package (`superagents.telemetry`), not as a
separate package. `superagents_sdlc` imports from it:

```python
from superagents.telemetry import persona_span, skill_span, handoff_span, approval_gate_span
```

The `anthropic` extra is optional — the CLI works with `--stub` without it. Install
with `pip install superagents-sdlc[anthropic]` for real LLM calls.

## Code standards

- All Python code must include type hints and return types.
- Google-style docstrings with Args, Returns, Raises.
- Single backticks for inline code, never Sphinx double backticks.
- Prefer single-word variable names where possible.
- No `eval()`, `exec()`, `pickle` on user input.
- No bare `except:` — use `msg` variable for error messages.
- Inline `# noqa: RULE` for individual lint suppressions.
- Conventional Commits, lowercase, scope required.
- Skill subpackage dependency direction: `qa` depends on `engineering`, never the reverse. No circular imports between skill subpackages.

## References

- [Deep Agents SDK](https://github.com/langchain-ai/deepagents) — Runtime and orchestration
- [Superpowers](https://github.com/obra/superpowers) — TDD workflow methodology
- [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) — Persona model inspiration
- [Manna Ray](https://github.com/mhosner/manna_ray) — PM skill definitions to port
- [Strangler Fig Newton](https://github.com/mhosner/strangler_fig_newton) — Legacy migration plugin
- [A2A Protocol](https://github.com/a2aproject/A2A) — Agent-to-agent communication
- [OpenAI Agents Handoffs](https://openai.github.io/openai-agents-python/handoffs/) — Handoff pattern reference
