"""Tests for brainstorm narrative renderer."""

from __future__ import annotations

from superagents_sdlc.brainstorm.narrative import render_narrative_markdown


def test_render_empty_entries():
    """Empty list produces a document with the idea title and no event content."""
    result = render_narrative_markdown([], "Add dark mode")
    assert "# Brainstorm Narrative: Add dark mode" in result
    assert "## Exploration" not in result


def test_render_assessment_entry():
    """Single assessment entry renders with confidence, delta, readiness, and gap count."""
    entries = [{
        "event": "assessment",
        "round": 0,
        "confidence": 35,
        "confidence_delta": None,
        "gap_count": 4,
        "section_readiness": {
            "problem_statement": {"readiness": "low"},
            "users_and_personas": {"readiness": "low"},
            "requirements": {"readiness": "low"},
            "acceptance_criteria": {"readiness": "low"},
        },
        "readiness_changes": {},
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "## Exploration" in result
    assert "### Round 0 — Initial Assessment" in result
    assert "Confidence 35%" in result
    assert "4 gaps remaining" in result
    assert "problem_statement: LOW" in result


def test_render_assessment_negative_delta():
    """Assessment with negative delta renders the drop clearly."""
    entries = [{
        "event": "assessment",
        "round": 3,
        "confidence": 45,
        "confidence_delta": -5,
        "gap_count": 3,
        "section_readiness": {},
        "readiness_changes": {"technical_constraints": {"from": "medium", "to": "low"}},
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "(-5)" in result
    assert "45%" in result
    assert "MEDIUM → LOW" in result


def test_render_question_answered():
    """Entry renders question text, answer, and target section."""
    entries = [{
        "event": "question_answered",
        "round": 1,
        "confidence": 40,
        "confidence_delta": None,
        "question_text": "What is the core problem?",
        "answer_text": "Planning blindness",
        "options": ["A", "B"],
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "What is the core problem?" in result
    assert "Planning blindness" in result


def test_render_auto_continue():
    """Auto-continue entry renders distinctly from a normal assessment."""
    entries = [{
        "event": "auto_continue",
        "round": 2,
        "confidence": 40,
        "confidence_delta": None,
        "gap_count": 5,
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "Auto-continued" in result
    assert "40%" in result
    assert "5 gaps" in result


def test_render_stall_exit():
    """Stall exit renders the choice and remaining gaps."""
    entries = [{
        "event": "stall_exit",
        "round": 4,
        "confidence": 62,
        "confidence_delta": None,
        "choice": "proceed",
        "gaps": [{"section": "acceptance_criteria", "description": "No error paths"}],
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "Stall exit" in result
    assert "proceed" in result
    assert "1 gaps remaining" in result


def test_render_approach_selected():
    """Renders selected approach name and alternatives offered."""
    entries = [{
        "event": "approach_selected",
        "round": None,
        "confidence": None,
        "confidence_delta": None,
        "approach_name": "Event-driven pipeline",
        "approaches_offered": ["Event-driven pipeline", "Batch processor", "Hybrid"],
    }]
    result = render_narrative_markdown(entries, "Test idea")
    assert "## Design" in result
    assert "Event-driven pipeline" in result
    assert "Batch processor" in result
    assert "Hybrid" in result


def test_render_section_approved_and_revised():
    """Mix of approved and revised sections renders with correct markers."""
    entries = [
        {"event": "section_approved", "round": None, "confidence": None, "confidence_delta": None, "section_title": "Problem Statement & Goals"},
        {"event": "section_revised", "round": None, "confidence": None, "confidence_delta": None, "section_title": "Technical Constraints"},
        {"event": "section_approved", "round": None, "confidence": None, "confidence_delta": None, "section_title": "Requirements"},
    ]
    result = render_narrative_markdown(entries, "Test idea")
    assert "✓ Problem Statement & Goals — approved" in result
    assert "✎ Technical Constraints — revised" in result
    assert "✓ Requirements — approved" in result


def test_render_full_journey():
    """Multi-entry list covering full brainstorm journey."""
    entries = [
        {"event": "assessment", "round": 0, "confidence": 35, "confidence_delta": None, "gap_count": 4,
         "section_readiness": {"problem_statement": {"readiness": "low"}, "users_and_personas": {"readiness": "low"}},
         "readiness_changes": {}},
        {"event": "question_answered", "round": 1, "confidence": 35, "confidence_delta": None,
         "question_text": "What is the core problem?", "answer_text": "Planning blindness", "options": None},
        {"event": "assessment", "round": 1, "confidence": 45, "confidence_delta": 10, "gap_count": 3,
         "section_readiness": {}, "readiness_changes": {"problem_statement": {"from": "low", "to": "medium"}}},
        {"event": "auto_continue", "round": 2, "confidence": 48, "confidence_delta": None, "gap_count": 3},
        {"event": "approach_selected", "round": None, "confidence": None, "confidence_delta": None,
         "approach_name": "Simple", "approaches_offered": ["Simple", "Complex"]},
        {"event": "section_approved", "round": None, "confidence": None, "confidence_delta": None,
         "section_title": "Problem Statement & Goals"},
        {"event": "section_revised", "round": None, "confidence": None, "confidence_delta": None,
         "section_title": "Technical Constraints"},
        {"event": "brief_approved", "round": None, "confidence": None, "confidence_delta": None},
    ]
    result = render_narrative_markdown(entries, "Add dark mode")
    assert "# Brainstorm Narrative: Add dark mode" in result
    assert "## Exploration" in result
    assert "## Design" in result
    assert "## Brief" in result
    exploration_pos = result.index("## Exploration")
    design_pos = result.index("## Design")
    brief_pos = result.index("## Brief")
    assert exploration_pos < design_pos < brief_pos
    assert "Round 0 — Initial Assessment" in result
    assert "Round 1" in result
    assert "Planning blindness" in result
    assert "(+10)" in result
    assert "Auto-continued" in result
    assert "Simple" in result
    assert "Problem Statement & Goals — approved" in result
    assert "Technical Constraints — revised" in result
    assert "Brief approved" in result
