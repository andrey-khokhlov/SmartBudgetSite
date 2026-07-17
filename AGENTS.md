# AGENTS.md

## Purpose

This file gives coding agents operational instructions for working on SmartBudgetSite.

SmartBudgetSite is the FastAPI backend and website for SmartBudget. SmartBudget itself is a forecasting-first personal financial decision-support product. Do not treat it as a generic expense tracker, a SaaS-first fintech product, or a disposable spreadsheet template.

## Source-of-truth documents

Before starting non-trivial work, review:

- `docs/product_positioning.md` — product vision, positioning, product philosophy, and strategic feature fit.
- `docs/README.md` — documentation map and source-of-truth boundaries.
- `docs/current_state.md` — current implementation state, constraints, and priorities.
- `docs/architecture/backend.md` — backend layers, responsibility boundaries, and implementation patterns.
- `docs/architecture/commerce_and_delivery.md` — commerce, payment, release, entitlement, and delivery rules when working in those domains.
- `docs/architecture/consultations.md` — consultation purchase, entitlement, booking, and webhook rules when working on consultation features.
- `docs/architecture/feedback.md` — feedback, reviews, Q&A, publication, and operational workflow rules when working on feedback features.
- `docs/operations.md` — development, configuration, deployment, and validation procedures.

`docs/history/sprint_checkpoints.md` is a historical record only. It preserves
implementation continuity and rationale but is not an active source of truth.

If these documents conflict with the requested implementation, stop and report the conflict before making changes.

## Current architecture

Follow the existing layered architecture:

```text
Web/API route
    -> Service
        -> Repository
            -> Database
```

Use the existing package roles:

- `app/web` — HTML/Jinja routes and browser flows.
- `app/api/v1` — JSON API endpoints and webhooks.
- `app/services` — business logic, workflow rules, lifecycle transitions, provider orchestration.
- `app/repositories` — database access and reusable queries.
- `app/models` — SQLAlchemy models.
- `app/schemas` — Pydantic schemas.
- `app/core` — configuration, logging, i18n, infrastructure.
- `app/dependencies` — dependency injection such as `get_db`.

Do not duplicate dependency providers. Use `get_db` from `app/dependencies`.

## Implementation rules

- Keep routes thin.
- Do not put business logic, lifecycle rules, or multi-step DB updates directly in routes.
- Move business logic to services.
- Use repository methods for reusable DB queries.
- Keep repositories focused on data access, not lifecycle decisions.
- Keep services independent from template rendering.
- Do not mix HTML rendering rules with business rules.
- Add or update tests for behavior changes.
- Prefer testing services for business logic and route tests for critical HTTP behavior.
- Preserve existing naming, style, and project structure unless explicitly asked to refactor.
- Code comments must be in English.
- Do not introduce broad abstractions “for the future” unless the current task requires them.
- Do not introduce cloud/SaaS assumptions unless explicitly approved.
- Do not change product positioning or architecture documentation unless the task explicitly asks for documentation updates.

## Architecture decision rule

Do not make new architecture decisions silently.

If implementation reveals a design ambiguity, stop and report:

1. the ambiguity;
2. affected files and concepts;
3. realistic options;
4. the recommended option;
5. what will change if the recommendation is accepted.

Do not implement the recommendation until it is approved.

Examples of architecture decisions that require escalation:

- new domain model boundaries;
- new persistence model or migration strategy;
- changing service/repository responsibilities;
- new payment, booking, licensing, or entitlement lifecycle rules;
- new cloud storage, SaaS, or external-provider assumptions;
- changes to SmartBudget product positioning;
- changes that affect privacy, local-first assumptions, or user financial-data handling;
- replacing existing workflow patterns rather than extending them.

## Product principles to preserve

SmartBudget is forecasting-first. It should help users understand future financial consequences before money is spent.

Prioritize:

- clarity over feature count;
- decisions over dashboards;
- future consequences over historical categorization;
- practical financial control over financial entertainment;
- explainable logic over opaque automation.

The product should not become:

- a generic expense tracker;
- a banking-app spending analytics clone;
- an opaque AI financial adviser;
- a trading, investment speculation, tax, or accounting system;
- a feature-heavy dashboard without decision value;
- a full SaaS ecosystem before product-market validation.

## Excel product boundary

The Excel product is not just a temporary technical artifact. It intentionally preserves familiar Excel interaction patterns and strengthens them with financial logic, automation, and explainable calculations.

Do not assume that every product direction should move toward web/SaaS. Web interfaces are optional future directions, not the default destination.

When a backend change touches product delivery, licensing, downloads, product variants, consultations, or customer workflows, preserve this local-first and privacy-aware product positioning unless a new architecture decision has been approved.

## GPT and AI boundaries

GPT may be used as an interpretation and decision-support layer, but deterministic product logic must remain responsible for calculations, validations, balances, plans, actuals, deviations, and timelines.

Do not implement logic that asks GPT to invent financial calculations or business rules from raw financial data.

## Environment and configuration

Settings are defined in `app/core/config.py` using Pydantic settings and environment files.

Do not hardcode secrets, tokens, credentials, provider signing secrets, or environment-specific URLs.

Do not read provider secrets from request headers or user input. Provider secrets must be server-owned configuration.

## Testing and validation

Run the relevant tests after changes.

Always execute tests through the project's configured Python interpreter.

Preferred command:

```bash
python -m pytest
```

Do not assume that a standalone `pytest` executable is available on the system PATH.

When running focused or full test suites, use the project's configured virtual environment or interpreter rather than a globally installed Python.

If formatting, type-checking, or lint tools are present in the current branch or environment, run the project-standard checks as well. Do not invent new tooling configuration without approval.

When a task adds a migration, model, repository, service, or route, add focused regression coverage.

## Git behavior

Prefer small, focused diffs.

Do not commit directly unless explicitly asked.

If preparing work for review, summarize:

- files changed;
- behavior changed;
- tests run;
- risks or unresolved questions.

## Escalation template

When stopping for an architecture decision, use this format:

```text
Architecture decision needed

Ambiguity:
...

Affected files/concepts:
...

Options:
1. ...
2. ...

Recommendation:
...

Why this matters:
...

Waiting for approval before implementation.
```
