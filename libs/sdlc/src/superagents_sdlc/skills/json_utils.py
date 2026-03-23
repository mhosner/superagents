"""JSON extraction from LLM responses that may contain fences, prose, or errors."""

from __future__ import annotations

import json
import re
from typing import Any

# Matches trailing commas before } or ] with optional whitespace
_TRAILING_COMMA = re.compile(r",\s*([}\]])")

_DECODER = json.JSONDecoder()


def extract_json(raw: str) -> Any:
    """Extract JSON from an LLM response that may contain markdown fences or prose.

    Tries multiple strategies in order:
    1. Strip markdown code fences and parse directly
    2. Repair trailing commas and parse directly
    3. Find first ``{`` or ``[`` and raw_decode (on both original and repaired)

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If no valid JSON found after all strategies.
    """
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()

    # Build candidate texts: original, then repaired (if different)
    repaired = _TRAILING_COMMA.sub(r"\1", text)
    candidates = [text] if repaired == text else [text, repaired]

    # Strategy 1: direct json.loads on each candidate
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Strategy 2: raw_decode from each { or [ on each candidate
    for candidate in candidates:
        for i, ch in enumerate(candidate):
            if ch in ("{", "["):
                try:
                    obj, _ = _DECODER.raw_decode(candidate, i)
                    return obj
                except json.JSONDecodeError:
                    continue

    msg = f"No valid JSON found in LLM response: {raw[:200]}"
    raise ValueError(msg)
