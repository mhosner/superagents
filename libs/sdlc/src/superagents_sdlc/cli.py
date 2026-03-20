"""Standalone CLI for superagents-sdlc pipelines."""

from __future__ import annotations

from pathlib import Path

# Named context files recognized by the loader.
_CONTEXT_FILES: dict[str, str] = {
    "product_context.md": "product_context",
    "goals_context.md": "goals_context",
    "personas_context.md": "personas_context",
}


def _load_context(context_dir: str | None) -> dict[str, str]:
    """Load context from named markdown files in a directory.

    Args:
        context_dir: Path to the context directory, or None for empty context.

    Returns:
        Dict mapping context keys to file contents.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if context_dir is None:
        return {}

    directory = Path(context_dir)
    if not directory.is_dir():
        msg = f"Context directory not found: {context_dir}"
        raise FileNotFoundError(msg)

    context: dict[str, str] = {}
    for filename, key in _CONTEXT_FILES.items():
        filepath = directory / filename
        if filepath.exists():
            context[key] = filepath.read_text()
    return context
