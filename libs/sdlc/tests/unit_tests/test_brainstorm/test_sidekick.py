"""Tests for brainstorm sidekick callout skills."""

from __future__ import annotations

from superagents_sdlc.brainstorm.sidekick import SKILLS, SidekickContext, run_sidekick_skill
from superagents_sdlc.skills.llm import StubLLMClient


def test_skills_registry_has_pros_cons():
    assert any(s.key == "1" and "pros" in s.name.lower() for s in SKILLS)


def test_sidekick_context_dataclass():

    ctx = SidekickContext(
        idea="Add dark mode",
        question_text="Which storage?",
        options=["PostgreSQL", "SQLite"],
        targets_section="technical_constraints",
        decisions_so_far="Chose React frontend",
        selected_approach="Monolith",
        product_context="Web app",
    )
    assert ctx.idea == "Add dark mode"
    assert ctx.options == ["PostgreSQL", "SQLite"]


async def test_run_sidekick_skill_calls_llm():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "### PostgreSQL\n**Pros:** Great"})
    ctx = SidekickContext(
        idea="Add dark mode",
        question_text="Which storage?",
        options=["PostgreSQL"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    result = await run_sidekick_skill(SKILLS[0], ctx, llm)
    assert len(llm.calls) == 1
    assert "PostgreSQL" in result


async def test_run_sidekick_skill_includes_idea():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="Recipe sharing app",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Recipe sharing app" in prompt


async def test_run_sidekick_skill_includes_options():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["PostgreSQL", "SQLite"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "PostgreSQL" in prompt
    assert "SQLite" in prompt


async def test_run_sidekick_skill_includes_decisions():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="Chose React frontend",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Chose React frontend" in prompt


async def test_run_sidekick_skill_freetext_question():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="What matters?",
        options=None,
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "open-ended" in prompt.lower()


async def test_run_sidekick_skill_includes_approach():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="",
        selected_approach="Microservices",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Microservices" in prompt


async def test_run_sidekick_skill_omits_approach_when_empty():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[0], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Selected approach" not in prompt


async def test_run_sidekick_skill_returns_llm_response():

    llm = StubLLMClient(responses={"Analyze the pros and cons": "### A\n**Pros:** Good"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    result = await run_sidekick_skill(SKILLS[0], ctx, llm)
    assert result == "### A\n**Pros:** Good"


# -- Three-skill registry tests --


def test_skills_registry_has_three_skills():
    assert len(SKILLS) == 3
    assert SKILLS[0].key == "1"
    assert SKILLS[1].key == "2"
    assert SKILLS[2].key == "3"
    assert "pros" in SKILLS[0].name.lower()
    assert "outside" in SKILLS[1].name.lower()
    assert "consequences" in SKILLS[2].name.lower()


# -- Outside the box tests --


async def test_outside_box_skill_calls_llm():
    llm = StubLLMClient(responses={"Propose one alternative": "### Event sourcing\n**What it is:** ..."})
    ctx = SidekickContext(
        idea="Recipe app",
        question_text="Storage?",
        options=["PostgreSQL", "SQLite"],
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    result = await run_sidekick_skill(SKILLS[1], ctx, llm)
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0]
    assert "Recipe app" in prompt
    assert "PostgreSQL" in prompt
    assert "Event sourcing" in result


async def test_outside_box_freetext_question():
    llm = StubLLMClient(responses={"Propose one alternative": "### Fresh angle"})
    ctx = SidekickContext(
        idea="App",
        question_text="What matters?",
        options=None,
        targets_section="",
        decisions_so_far="",
        selected_approach="",
        product_context="",
    )
    result = await run_sidekick_skill(SKILLS[1], ctx, llm)
    prompt = llm.calls[0][0]
    assert "open-ended" in prompt.lower()
    assert "Fresh angle" in result


# -- Unforeseen consequences tests --


async def test_consequences_skill_calls_llm():
    llm = StubLLMClient(responses={"identify 2-3": "### PostgreSQL\n- **Forces:** Migrations"})
    ctx = SidekickContext(
        idea="Recipe app",
        question_text="Storage?",
        options=["PostgreSQL", "SQLite"],
        targets_section="",
        decisions_so_far="Chose React",
        selected_approach="",
        product_context="",
    )
    result = await run_sidekick_skill(SKILLS[2], ctx, llm)
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0]
    assert "Recipe app" in prompt
    assert "PostgreSQL" in prompt
    assert "Migrations" in result


async def test_consequences_skill_includes_decisions():
    llm = StubLLMClient(responses={"identify 2-3": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="Using GraphQL API",
        selected_approach="",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[2], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Using GraphQL API" in prompt


async def test_consequences_skill_includes_approach():
    llm = StubLLMClient(responses={"identify 2-3": "Result"})
    ctx = SidekickContext(
        idea="App",
        question_text="Q?",
        options=["A"],
        targets_section="",
        decisions_so_far="",
        selected_approach="Microservices",
        product_context="",
    )
    await run_sidekick_skill(SKILLS[2], ctx, llm)
    prompt = llm.calls[0][0]
    assert "Microservices" in prompt
