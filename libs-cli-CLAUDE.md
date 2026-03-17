# Deep Agents CLI — Development Guide

This is the package-specific CLAUDE.md for `libs/cli/`. It supplements the root `CLAUDE.md` with detailed Textual UI patterns, model provider setup, slash command conventions, and CLI-specific workflows.

> **Root rules still apply**: TDD workflow, code quality standards, commit format, and public API stability from the root CLAUDE.md are mandatory here too.

## Textual framework

The CLI uses [Textual](https://textual.textualize.io/) for its terminal UI.

**Key resources:**
- [Guide](https://textual.textualize.io/guide/) · [Widget gallery](https://textual.textualize.io/widget_gallery/) · [CSS reference](https://textual.textualize.io/styles/) · [API reference](https://textual.textualize.io/api/)
- [Anatomy of a Textual User Interface](https://textual.textualize.io/blog/2024/09/15/anatomy-of-a-textual-user-interface/) — chat interface with streaming

### Styled text: Content vs Rich Text

Prefer Textual's `Content` (`textual.content`) over Rich's `Text` for widget rendering. `Content` is immutable and integrates natively with Textual's rendering pipeline. Rich `Text` is still correct for code that renders via `Console.print()` (e.g., `non_interactive.py`, `main.py`).

**Critical**: `Content` requires Textual's `Style` (`textual.style.Style`), not Rich's `Style`. Mixing them causes `TypeError` during widget rendering.

#### Decision rule

If the value could come from outside the codebase (user input, tool output, API responses, file contents), use `from_markup` with `$var`. If it's hardcoded, a glyph, or a computed int, `styled` is fine.

#### Methods

- `Content.from_markup("[bold]$var[/bold]", var=value)` — Inline markup with auto-escaped substitution. **Use for external/user-controlled values.**
- `Content.styled(text, "bold")` — Single style on plain text, no markup parsing. **Use for internal/trusted strings.** Avoid `Content.styled(f"..{var}..", style)` when `var` is user-controlled.
- `Content.assemble("prefix: ", (text, "bold"), " ", other_content)` — Compose `Content` objects, `(text, style)` tuples, and plain strings. Use for structural composition, especially with `TStyle(link=url)`.
- `content.join(parts)` — Like `str.join()` for `Content` objects.

**Never use f-string interpolation in Rich markup** (e.g., `f"[bold]{var}[/bold]"`). If `var` contains square brackets, the markup breaks.

### Textual patterns used in this codebase

- **Workers** (`@work` decorator) for async operations — [Workers guide](https://textual.textualize.io/guide/workers/)
- **Message passing** for widget communication — [Events guide](https://textual.textualize.io/guide/events/)
- **Reactive attributes** for state management — [Reactivity guide](https://textual.textualize.io/guide/reactivity/)

### Testing Textual apps

- Use `textual.pilot` for async UI testing — [Testing guide](https://textual.textualize.io/guide/testing/)
- Snapshot testing for visual regression — see repo `notes/snapshot_testing.md`

---

## Startup performance

The CLI must stay fast to launch. Never import heavy packages (`deepagents`, LangChain, LangGraph) at module level or in the argument-parsing path.

- Keep top-level imports in `main.py` and entry-point modules minimal.
- Defer heavy imports inside functions/methods.
- Use `importlib.metadata.version("package-name")` to read versions without importing.

---

## SDK dependency pin

The CLI pins exact `deepagents==X.Y.Z` in `libs/cli/pyproject.toml`. When developing CLI features that depend on new SDK functionality, bump this pin in the same PR. CI verifies the pin matches at release time (bypass with `dangerous-skip-sdk-pin-check`).

---

## Slash commands

Defined in `SLASH_COMMANDS` in `libs/cli/deepagents_cli/widgets/autocomplete.py` as `(name, description, hidden_keywords)` tuples.

- Hidden keywords are space-separated terms for fuzzy matching (never displayed).
- To add an alias for an existing command, append to `hidden_keywords` — do not create a duplicate entry.
- Example: `/threads` has `sessions` as a hidden keyword so typing "sessions" surfaces it.

---

## CLI help screen

Hand-maintained in `ui.show_help()`, separate from argparse in `main.parse_args()`. When adding a new flag, update **both**. A drift-detection test (`test_args.TestHelpScreenDrift`) catches mismatches.

---

## Splash screen tips

When adding a user-facing CLI feature (slash command, keybinding, workflow), add a tip to `_TIPS` in `libs/cli/deepagents_cli/widgets/welcome.py`. Tips show randomly on startup. Keep them short and action-oriented (e.g., `"Press ctrl+x to compose prompts in your external editor"`).

---

## Adding a new model provider

The CLI supports LangChain-based chat model providers as optional dependencies. To add one, update these files (alphabetically sorted entries):

1. `libs/cli/deepagents_cli/model_config.py` — add `"provider_name": "ENV_VAR_NAME"` to `PROVIDER_API_KEY_ENV`
2. `libs/cli/pyproject.toml` — add `provider = ["langchain-provider>=X.Y.Z,<N.0.0"]` to `[project.optional-dependencies]` and include in `all-providers`
3. `libs/cli/tests/unit_tests/test_model_config.py` — add assertion to `TestProviderApiKeyEnv.test_contains_major_providers`

**Only needed if the provider's models have a distinctive name prefix** (like `gpt-*`, `claude*`, `gemini*`):
- `detect_provider()` in `config.py` — for auto-detection from bare model names
- `Settings.has_*` property in `config.py` — only if referenced by `detect_provider()` fallback

Model discovery, credential checking, and UI integration are automatic once `PROVIDER_API_KEY_ENV` is populated and the `langchain-*` package is installed.
