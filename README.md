# Superagents

An agentic software development lifecycle framework that maps AI agents to enterprise SDLC roles — so organizations can adopt agentic coding incrementally, with every persona accountable to a real human.

Built on [Deep Agents](https://github.com/langchain-ai/deepagents) (runtime), [Superpowers](https://github.com/obra/superpowers) (TDD methodology), and the [A2A Protocol](https://github.com/a2aproject/A2A) (agent communication).

## The problem

Enterprise engineering organizations want to adopt agentic coding but face three blockers:

1. **No governance model.** Existing frameworks don't map to the roles and approval chains that regulated industries require. When an AI agent writes code, who approved the spec it implemented? Who reviewed the architecture? Who signed off on the test plan?

2. **All-or-nothing adoption.** Most agentic tools assume full autonomy. Teams can't start with "agents draft, humans decide" and gradually increase autonomy as trust builds.

3. **No observability.** When agents produce artifacts across a multi-step workflow, there's no structured trace showing what happened, what was approved, and where things went wrong.

## How Superagents solves this

### SDLC personas with human owners

Every agent maps to a traditional software development role. The human in that role owns the output.

| Persona | Human Owner | What it does |
|---------|-------------|-------------|
| Product Manager | PM / Product Owner | Generates PRDs, prioritizes backlogs, writes user stories |
| Architect | Tech Lead | Produces technical specs, evaluates tech debt |
| Developer | Dev Team | Implements code via TDD with subagent-driven execution |
| QA | QA Lead | Designs tests, analyzes results, validates quality |
| Scrum Leader | Engineering Manager | Plans sprints, tracks workflows, orchestrates execution |
| Stakeholder Proxy | Product Owner | Simulates stakeholder feedback, generates executive updates |

A CTO can look at this system and see their org chart. That's the point.

### Autonomy gradient

Teams configure how much agents do versus how much humans do:

**Level 1 — Assist.** Agents draft every artifact. Humans review and approve each one before the next phase begins. Implementation is human-led with agent pair programming.

**Level 2 — Hybrid.** Agents own planning artifacts autonomously. Humans approve at phase boundaries (e.g., approve the story batch, then agents TDD each story). Human code review at story completion.

**Level 3 — Autonomous.** Agents execute the full workflow. Humans approve at epic/sprint boundaries. Automated quality gates (test pass rate, review scores) determine proceed/block.

The policy layer intercepts every agent-to-agent handoff and enforces the configured level. Moving from Level 1 to Level 2 is a config change, not a rewrite.

### Telemetry from the ground up

Every persona action, skill execution, handoff, and approval gate decision emits OpenTelemetry spans with structured attributes. This isn't bolted on — it's the first code in the project.

```
trace: sdlc_workflow
  └── persona.product_manager
       ├── skill.prd_generator
       ├── approval_gate.prd_review
       │    ├── approval.outcome = approved
       │    └── gate_duration_ms = 1200
       └── handoff.product_manager_to_architect
            └── artifact.type = prd
```

This gives teams the data to justify moving from Level 1 to Level 2: "Here's the approval rejection rate. Here's the defect rate. Here's the time savings."

### Superpowers TDD enforcement

All implementation follows the [Superpowers](https://github.com/obra/superpowers) methodology — not as a suggestion, but as a mandatory workflow:

1. **Brainstorm** before writing code.
2. **Plan** in small tasks (2–5 minutes each).
3. **RED-GREEN-REFACTOR** — write the failing test first. Always.
4. **Subagent review** — two-stage (spec compliance, then code quality).
5. **Finish cleanly** — verify tests pass, present merge options.

### A2A protocol for agent communication

Personas communicate via the [Agent2Agent Protocol](https://a2a-protocol.org/) — the open standard for agent interoperability. Each persona publishes an Agent Card describing its capabilities. Handoffs carry typed metadata (artifact path, context summary, trace ID). This means personas can eventually run as independent services, not just in-process — enabling multi-team, multi-framework agent collaboration.

## Architecture

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
│  │ PM Skills│  │  Arch    │  │Superpwr  │  │ Layered   │  │
│  │(ported   │  │  Skills  │  │TDD Cycle │  │ Testing   │  │
│  │ from     │  │          │  │          │  │           │  │
│  │MannaRay) │  │          │  │          │  │           │  │
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

## Project structure

```
superagents/
├── libs/
│   ├── superagents/          # SDK (extended from Deep Agents)
│   │   └── superagents/
│   │       └── telemetry/    # OpenTelemetry instrumentation
│   ├── sdlc/                 # SDLC integration package
│   │   └── src/superagents_sdlc/
│   │       ├── personas/     # SDLC persona facades
│   │       ├── skills/       # Ported PM, engineering, QA skills
│   │       ├── policy/       # Autonomy policy engine
│   │       ├── handoffs/     # A2A-based handoff implementation
│   │       └── workflows/    # SDLC workflow definitions
│   ├── cli/                  # Terminal UI (Textual)
│   ├── harbor/               # Evaluation/benchmark framework
│   └── partners/             # Integration packages
├── .github/                  # CI/CD
└── CLAUDE.md                 # Development standards
```

## Status

This project is in early development.

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with [Superpowers plugin](https://github.com/obra/superpowers)

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/superagents.git
cd superagents

# Install the SDLC package and its dependencies
cd libs/sdlc
uv init --name superagents-sdlc --python ">=3.12"
uv add opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
uv add a2a-sdk pydantic
uv add --group test pytest pytest-asyncio
uv add --editable ../superagents
```

### Development

```bash
make test       # Run unit tests (no network)
make lint       # Lint with ruff
make format     # Format with ruff
```

All development follows the Superpowers TDD methodology. See [CLAUDE.md](CLAUDE.md) for standards.

## Influences

Superagents wouldn't exist without these projects:

- **[Deep Agents](https://github.com/langchain-ai/deepagents)** — The SDK and agent harness this project is forked from.
- **[Superpowers](https://github.com/obra/superpowers)** by Jesse Vincent — The TDD-first agentic development methodology that is the engineering backbone of this project.
- **[BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD)** — The persona-driven agile AI framework that inspired the SDLC role mapping and adoption gradient.
- **[Manna Ray](https://github.com/mhosner/manna_ray)** — The PM skills and workflow definitions being ported into the persona layer.
- **[Strangler Fig Newton](https://github.com/mhosner/strangler_fig_newton)** — The legacy migration plugin for monolith-to-microservice decomposition.
- **[A2A Protocol](https://github.com/a2aproject/A2A)** — The open standard for agent-to-agent communication.

## License

MIT
