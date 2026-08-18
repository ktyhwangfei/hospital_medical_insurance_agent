# Skill Capability Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the `/skills` governance queue with a compact, card-based capability and scenario overview while keeping governance status secondary.

**Architecture:** Preserve the draft execution contract in the materialized manifest, project it through the existing version catalog and workbench API, then render all Skill dossiers from one request with client-side search and filters. Keep the former governance workbench untouched.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, Next.js 16, React, TypeScript, Tailwind CSS, Vitest, Testing Library

---

### Task 1: Preserve capability and scenarios in the formal artifact

**Files:**
- Modify: `src/runtime/skill_management/package_generator.py`
- Test: `src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py`

1. Add a failing package-generation test asserting that `description` and the complete `execution_contract` appear in generated `skill_manifest.yaml`.
2. Run the focused test and confirm the missing manifest fields cause the failure.
3. Add only those two fields in `_render_manifest`, omitting empty optional values.
4. Re-run the focused test and the package-generator unit module.

### Task 2: Project overview data through the existing workbench endpoint

**Files:**
- Modify: `src/runtime/skill_management/version_service.py`
- Modify: `src/runtime/skill_management/workbench_service.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/apps/portal/src/lib/types.ts`
- Test: `src/tests/unit/runtime/skill_management/test_workbench_service.py`
- Test: relevant infra Skill API integration test

1. Add failing unit and API assertions for capability description and execution contract.
2. Extend `SkillCatalogEntry` and `SkillWorkbenchItem` with backward-compatible defaults.
3. Parse `execution_contract` using the existing `SkillExecutionContract` domain model; invalid or absent historical data becomes an empty contract instead of breaking the catalog.
4. Expose the typed fields through the response schema and matching TypeScript interface.
5. Run the focused unit and API tests.

### Task 3: Build the compact Skill overview

**Files:**
- Create: `src/apps/portal/src/components/skills/skill-capability-overview.tsx`
- Create: `src/apps/portal/src/tests/skill-capability-overview.test.tsx`
- Modify: `src/apps/portal/app/skills/page.tsx`

1. Add failing component tests for multiple Skill cards, three-column scenario layout, common and scenario metrics, search matching a metric, combined filters, empty execution contract, error retry, and filtered empty state.
2. Implement one client component that calls `getSkillGovernanceWorkbench({ page: 1, page_size: 50 })` once.
3. Render a compact full-width dossier card per Skill, with responsive scenario grid and inline metric text.
4. Implement local search/filter derivation using `useMemo`; add no new state library or dependency.
5. Switch `/skills` to the new component and re-run its focused Vitest suite.

### Task 4: Rename navigation and document the domain vocabulary

**Files:**
- Modify: `src/apps/portal/app/skills/layout.tsx`
- Modify: `src/apps/portal/src/tests/skill-layout-tabs.test.tsx`
- Modify: `src/domain/AGENTS.md`

1. Change the first Skill navigation label and accessible name from “治理待办” to “概览”.
2. Update the layout test expectation.
3. Record execution contract, execution profile/scenario, and metric input in the domain glossary using existing names.

### Task 5: Verify the complete user story

1. Run Skill-management unit tests, including artifact generation and workbench projection.
2. Run infra Skill API tests.
3. Run the relevant Flow test after unit and API stages pass.
4. Run focused frontend tests, TypeScript checking, lint, and production build.
5. Inspect the served `/skills` page at its workspace URL and confirm 4–5 full-width cards remain compact with one/two/three-column scenario grids.
6. Review `git diff` to ensure unrelated dirty worktree changes were preserved.

