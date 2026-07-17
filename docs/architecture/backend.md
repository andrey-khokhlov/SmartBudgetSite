# Backend Architecture

## Purpose

This is the authoritative source for backend structure, layer boundaries, and
implementation patterns. Domain-specific rules are documented in:

- `commerce_and_delivery.md`
- `consultations.md`
- `feedback.md`

See `../current_state.md` for implementation status and priorities.

## High-level layers

### Web layer (`app/web`)

- Renders HTML pages with Jinja templates.
- Handles browser-based interactions.
- Returns `TemplateResponse` or `RedirectResponse`.

### API layer (`app/api/v1`)

- Provides JSON endpoints and webhooks.
- Serves frontend, provider, or external-client integrations.
- Returns structured Pydantic data or safe provider responses.

### Service layer (`app/services`)

- Contains business logic and lifecycle transitions.
- Remains independent from HTTP request/response and template rendering.
- Is reusable across Web and API entry points.
- May raise `HTTPException` under the existing project convention.
- Uses `flush()` rather than owning commits when participating in a larger
  transaction.

### Repository layer (`app/repositories`)

- Encapsulates database access and reusable queries.
- Performs lookup and persistence work, not lifecycle decisions.

### Core layer (`app/core`)

- Owns infrastructure including database setup, settings, logging, and i18n.

### Dependencies (`app/dependencies`)

- Provides shared dependency injection.
- `get_db` from this package is the single database-session dependency and must
  not be duplicated.

## Request flow

```text
Web/API route
    -> Service
        -> Repository
            -> Database
```

Routes remain thin. Provider integrations may add translation, verification, or
orchestration services between a route and a domain lifecycle service, but the
same responsibility boundaries apply.

## Transaction boundaries

Payment preparation and low-level entitlement services may:

- validate business rules;
- create or update records;
- flush the database session.

They must not commit. Higher-level orchestration owns transaction completion.
Payment preparation services also must not communicate directly with payment
providers; provider adapters/orchestration own that integration boundary.

## Design principles

- Keep routes thin and move conditional validation or multi-step updates into
  services.
- Keep repositories focused on data access.
- Keep services independent from template rendering.
- Do not mix HTML presentation rules with business rules.
- Reuse the single dependency-injection entry point.
- Keep external-provider payloads and signature formats out of domain services.
- Keep deterministic financial and business rules in application code, not GPT.

## Feature implementation pattern

1. Define business behavior in a service.
2. Use the service from the Web or API route.
3. Use repositories inside the service for reusable queries.
4. Add service tests for business logic and route tests for critical wiring.

Service tests validate business behavior, database changes, and errors. Route
tests validate HTTP wiring. When a route accumulates multiple conditions,
validation logic, or database updates, move that work into a service.

## Configuration boundary

Settings are defined in `app/core/config.py`. Provider signing secrets and other
credentials are server-owned configuration and must never come from request
headers or user input. Operational rules for `.env`, `.env.example`, deployment
configuration, and secret handling are in `../operations.md`.

