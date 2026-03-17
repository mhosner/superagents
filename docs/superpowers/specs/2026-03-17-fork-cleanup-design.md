# Fork Cleanup: Remove Upstream-Specific Files

## Purpose

Clean up the forked repository by removing files that are specific to the original project's (LangChain AI) infrastructure, release automation, and org-specific CI — while retaining useful CI workflows and development tooling.

## Files to Delete

### Root-level files

- `action.yml` — GitHub Action for running Deep Agents in workflows (LangChain-authored)
- `release-please-config.json` — automated release/PyPI publishing config
- `.release-please-manifest.json` — release-please version tracking
- `pr-labeler-consolidation.md` — internal design doc about upstream CI race condition

### `.github/` org-specific files

- `.github/CODEOWNERS` — references original maintainer (`@mdrxy`)
- `.github/dependabot.yml` — upstream dependency bot config
- `.github/RELEASING.md` — upstream release process documentation
- `.github/images/` — upstream GitHub profile/branding images
- `.github/PULL_REQUEST_TEMPLATE.md` — upstream PR template
- `.github/ISSUE_TEMPLATE/` — upstream issue templates

### `.github/workflows/` org-specific workflows

- `release-please.yml` — release automation
- `release.yml` — PyPI publishing
- `pr_labeler.yml` — auto-labeling PRs
- `tag-external-issues.yml` — org-specific issue tagging
- `require_issue_link.yml` — org-specific PR requirement
- `evals.yml` — upstream eval pipeline
- `deepagents-example.yml` — upstream example workflow
- `check_versions.yml` — cross-package version checks
- `check_sdk_pin.yml` — SDK pin enforcement
- `check_extras_sync.yml` — extras sync validation
- `check_lockfiles.yml` — lockfile consistency checks

### `.github/scripts/` (supporting scripts for deleted workflows)

- `aggregate_evals.py`
- `check_extras_sync.py`
- `check_version_equality.py`
- `get_eval_models.py`

## Files to Keep

### Useful CI workflows

- `.github/workflows/ci.yml` — CI orchestrator
- `.github/workflows/_lint.yml` — lint workflow
- `.github/workflows/_test.yml` — test workflow
- `.github/workflows/pr_lint.yml` — PR title linting (conventional commits)
- `.github/actions/uv_setup/` — composite action required by kept workflows

### Development tooling

- `.mcp.json` — LangChain docs/API reference MCP servers (kept for documentation access)
- `.gitignore`, `.pre-commit-config.yaml`, `.markdownlint.json` — dev tooling
- `.vscode/` — editor config
- `Makefile` — task runner

### Core code and docs

- `libs/` — all source code
- `examples/` — reference examples
- `CLAUDE.md`, `AGENTS.md` — development guidance
- `LICENSE`, `README.md` — project docs

## Implementation

Single task: delete all files listed in "Files to Delete" section. No code changes required — purely file removal.

## Verification

- Confirm no deleted file is referenced by a kept workflow
- Run `make lint` to ensure nothing breaks
