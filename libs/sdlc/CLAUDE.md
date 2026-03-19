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

- **Runtime**: Python 3.12+, Deep Agents SDK
- **Package management**: uv
- **Testing**: pytest (asyncio_mode = "auto")
- **Linting**: ruff
- **Type checking**: ty
- **Telemetry**: opentelemetry-api, opentelemetry-sdk
- **Agent communication**: a2a-sdk (A2A Python SDK)
- **CI**: GitHub Actions

## Project structure (target)

```
libs/superagents/                    # SDK (extended from upstream Deep Agents)
├── superagents/
│   └── telemetry/                   # Phase 1: OpenTelemetry instrumentation
│       ├── __init__.py              # Public API re-exports
│       ├── provider.py              # TracerProvider lifecycle
│       └── spans.py                 # Four span context managers
└── tests/unit_tests/test_telemetry/

libs/sdlc/                           # SDLC integration package (depends on superagents)
├── pyproject.toml
├── src/superagents_sdlc/
│   ├── skills/                      # Skill contract
│   │   └── base.py                  # BaseSkill ABC + SkillContext + Artifact + SkillValidationError
│   ├── personas/                    # SDLC persona facades
│   │   ├── base.py                  # BasePersona ABC with telemetry, policy, transport
│   │   ├── product_manager.py       # PM persona wrapping Manna Ray skills
│   │   ├── architect.py             # Architect persona
│   │   ├── developer.py             # Developer persona (Superpowers TDD)
│   │   ├── qa.py                    # QA persona (layered testing)
│   │   ├── scrum_master.py          # Scrum Master persona
│   │   └── stakeholder_proxy.py     # Stakeholder simulator persona
│   ├── skills/                      # Ported Manna Ray skills as Deep Agents Skills
│   │   ├── pm/                      # Product management skills
│   │   ├── engineering/             # Technical skills
│   │   └── qa/                      # Quality assurance skills
│   ├── policy/                      # Autonomy policy engine
│   │   ├── config.py                # PolicyConfig Pydantic model + YAML/env loaders
│   │   ├── gates.py                 # ApprovalGate protocol + Auto/Mock implementations
│   │   └── engine.py                # PolicyEngine (intercepts handoffs, enforces gates)
│   ├── handoffs/                    # A2A-shaped handoff implementation
│   │   ├── contract.py              # PersonaHandoff + HandoffResult Pydantic models
│   │   ├── transport.py             # Transport protocol + InProcessTransport
│   │   └── registry.py              # PersonaRegistry (lookup by name)
│   └── workflows/                   # SDLC workflow definitions
│       ├── idea_to_sprint.py        # Full planning-to-code workflow
│       ├── quick_spec.py            # Fast path for small changes
│       └── feedback_loop.py         # Post-launch analysis workflow
└── tests/
    ├── unit_tests/
    │   ├── test_skills/
    │   ├── test_personas/
    │   ├── test_policy/
    │   └── test_handoffs/
    └── integration_tests/
```

## Key dependencies

```toml
[project]
name = "superagents-sdlc"
dependencies = [
    "superagents",               # SDK with telemetry (editable install from ../superagents)
    "deepagents>=0.1.0",
    "a2a-sdk>=0.3.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
]
```

Telemetry lives in the superagents SDK package (`superagents.telemetry`), not as a
separate package. `superagents_sdlc` imports from it:

```python
from superagents.telemetry import persona_span, skill_span, handoff_span, approval_gate_span
```

The editable install (`uv add --editable ../superagents`) is set up during bootstrapping.

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
