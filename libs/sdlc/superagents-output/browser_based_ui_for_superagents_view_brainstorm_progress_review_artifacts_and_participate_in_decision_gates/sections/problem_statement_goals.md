# Problem Statement & Goals

## Problem Statement

The Superagents SDLC framework currently operates exclusively through a CLI interface and direct LangGraph interrupt/resume mechanics. This works well for developers and technical leads who live in terminals, but creates a fundamental participation barrier for a critical user class: the **non-technical stakeholders who own SDLC decisions**.

Product Managers, Product Owners, and other persona owners need to review PRDs, approve tech specs, question story priorities, annotate implementation plans, and participate in brainstorm sessions. Today, they must either learn CLI workflows or rely on a technical intermediary to relay their decisions — introducing latency, lossy translation, and a broken chain of accountability. The autonomy policy model (Level 1 through Level 3) is predicated on human approval at defined gates, but the framework provides only one surface for that approval.

This is not a visibility problem. Stakeholders don't need a dashboard to watch agents work. They need to **actively participate in the decision workflow** — reviewing artifacts, annotating specific sections, approving or rejecting with structured rationale, and responding to brainstorm questions — through an interface that meets them where they are: the browser.

## Goals

### G1: Enable browser-based decision participation
Deliver a browser UI where SDLC persona owners can review artifacts, annotate specific sections, and approve, reject, or request changes at every decision gate defined by the autonomy policy layer. The pending decision is the primary interaction unit — progress context is secondary.

### G2: Support full brainstorm participation from the browser
Extend browser-based participation beyond artifact review gates to include interactive brainstorm sessions. Brainstorm interrupts surface as decision cards in the same card-based queue pattern, allowing users to review context and respond asynchronously at their own pace.

### G3: Establish a surface-agnostic decision layer
Architect the decision and artifact review layer so that browser, CLI, and future agentic (MCP) interfaces are first-class peers. The decision layer is surface-agnostic; each client renders and collects decisions in its native idiom. The browser UI is the primary new surface to build, but it must not create a browser-privileged architecture.

### G4: Preserve existing CLI without disruption
The existing CLI continues to work as-is via direct LangGraph interrupt/resume in V1. CLI refactoring to consume the shared decision layer is explicitly a future task — V1 must not break, modify, or degrade the current CLI experience.

### G5: Route decisions through existing governance infrastructure
Annotations made in the browser are codified as IdeaMemory entries when they constitute design decisions, then packaged as structured findings and routed through the existing PolicyEngine and FindingsRouter chain. No parallel governance path — the browser is a new surface for the same decision machinery.

### G6: Ensure accessibility from day one
The card-based interaction model must be WCAG 2.1 AA compliant: keyboard navigable, screen reader compatible, sufficient color contrast, and no information conveyed by color alone. Accessibility is a V1 requirement, not a future enhancement.

## Non-Goals

- **Real-time collaboration / multi-user editing** — V1 supports one decision-maker per gate, consistent with the existing persona ownership model.
- **CLI refactoring** — The existing CLI is not refactored to use the shared decision layer in V1. It continues operating via direct interrupt.
- **Agent execution control** — The browser UI is for decision participation, not for starting, stopping, or configuring agent pipelines.
- **Custom dashboards or analytics** — OpenTelemetry metrics are already emitted; building visualization or analytics UIs on top of them is out of scope.
- **Mobile-optimized UI** — Responsive design is good practice but a dedicated mobile experience is not a V1 target.

## Success Criteria

- A PM / Product Owner can complete a full artifact review cycle (receive decision card → read summary → expand full artifact → annotate sections → approve or reject with rationale) entirely in the browser, with no CLI interaction required.
- A non-technical stakeholder can participate in an active brainstorm session from the browser, answering questions and reviewing approaches through the same card-based queue.
- The existing 542+ tests continue passing with no modifications to current CLI or pipeline code.
- All decision gate interactions in the browser flow through the existing PolicyEngine approval gate mechanics — no bypass path exists.
- The browser UI passes automated WCAG 2.1 AA audit (axe-core or equivalent) on all decision card views.