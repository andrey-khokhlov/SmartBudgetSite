# Release Readiness

## 1. Purpose

This document defines the criteria for declaring SmartBudgetSite ready for its
first public commercial release. It is the authoritative release-governance
source for the required architectural properties, the official remediation
backlog, the expected release gaps, and the final completion boundary.

This document does not replace the domain rules under `docs/architecture/`, the
implementation snapshot in `current_state.md`, or the operational procedures in
`operations.md`. Audit reports and remediation reviews remain working artifacts;
only their accepted architectural decisions are recorded here.

## 2. Release Philosophy

SmartBudgetSite is product infrastructure for SmartBudget. It supports product
presentation, commerce, delivery, consultation access, and customer support, but
it is not the primary financial-planning product. SmartBudget Excel remains the
primary product platform and preserves the local-first, forecasting-first
experience defined in `product_positioning.md`.

After the first public release, SmartBudgetSite should move predominantly into a
maintenance and targeted-improvement mode so that the main development focus can
return to SmartBudget Excel. The site must therefore enter release with stable
security boundaries, explicit transaction ownership, reliable product delivery,
and sustainable operational behavior. The quality threshold is higher than for
an MVP that is expected to undergo continuous architectural redevelopment after
launch.

Release preparation should strengthen the existing architecture rather than
replace it. Broad rewrites, speculative abstractions, and enterprise features
are not release-readiness requirements.

## 3. Release Readiness Criteria

### Security

- Public, customer, and administrative boundaries are explicit and fail closed.
- Private feedback, purchase data, credentials, and capability URLs are exposed
  only within their intended access context.
- Production secrets and administrative session transport are validated and
  protected.
- Public entry points have coherent replay, abuse, logging, and cache-safety
  boundaries.

### Persistence

- Each multi-step workflow has one explicit transaction owner.
- Failed workflows do not leave unintended partial database state.
- SQLAlchemy models, Alembic history, and the PostgreSQL schema express the same
  domain invariants.
- Entitlements originate only from valid paid ownership and remain tied to the
  correct purchased item.

### Release workflow

- Release upload has defined resource, conflict, failure, and recovery
  boundaries.
- Database state and external object-storage side effects cannot silently
  diverge or overwrite an existing release.
- Publication is an explicit domain action that preserves the one-active-release
  invariant and is available through the administrative workflow.

### Operations

- Critical webhook, storage, payment, delivery, and support outcomes are
  observable without exposing secrets or customer capability URLs.
- Backup and recovery procedures are implementable and validated in the release
  environment.
- Supported customer journeys can be diagnosed and completed operationally from
  their public entry point through the required administrative follow-up.

### Documentation

- Active documentation describes actual persistent behavior and approved domain
  rules.
- Configuration values have explicit ownership, environment scope, and
  precedence.
- Volatile implementation observations are not presented as permanent
  architectural properties.

### Accessibility

- Public pages declare the correct language.
- Essential form state, validation errors, and completion messages are available
  to assistive technologies.

### Deployment

- The public environment uses an approved production startup path, PostgreSQL
  migrations, HTTPS, trusted-host policy, private object storage, and secure
  server-owned configuration.
- External integrations are validated using real provider behavior in the
  release environment before the product is made public.

## 4. Official Release Backlog

The backlog below records the accepted release-critical architecture decisions.
It defines required outcomes, not their current implementation status. Detailed
implementation work and progress should be tracked separately.

### Security and public boundaries

Goal: establish fail-closed public, customer, administrative, capability-URL,
and abuse-protection boundaries.

- `SEC-001`
- `SEC-002`
- `SEC-003`
- `SEC-004`
- `SEC-005`
- `SEC-006`
- `SEC-007`
- `SEC-009`
- `SEC-011`

### Persistence and domain integrity

Goal: ensure that ownership, transaction completion, schema constraints, and
feedback associations remain consistent across requests and failures.

- `DB-001`
- `CONS-001`
- `CODE-001`
- `CODE-002`
- `CODE-003`
- `ARCH-001`
- `ARCH-003`

### Release and storage safety

Goal: make release upload, object storage, recovery, and publication one
coherent and operable domain workflow.

- `REL-003`
- `REL-004`
- `REL-005`

### Operations and public quality

Goal: provide reliable diagnostics, accessible customer interactions, and
documentation that matches the release behavior and configuration contract.

- `OPS-002`
- `A11Y-001`
- `A11Y-002`
- `DOC-002`
- `DOC-003`

## 5. Expected Release Gaps

The following work is mandatory before the first public commercial release, but
it is planned release completion rather than remediation of existing backend
defects.

### Commerce and fulfillment (`REL-001`)

- real Stripe Checkout Session creation;
- payment webhook processing;
- payment-success entitlement creation;
- customer purchase email and delivery links.

### Production deployment (`REL-002`)

- production application and VPS deployment definition;
- reverse proxy and process lifecycle;
- public DNS and HTTPS;
- production startup, migration, persistence, and health validation.

### Backup and recovery (`OPS-001`)

- PostgreSQL backup and off-host retention;
- restore validation;
- object-storage and configuration recovery procedures.

### Public deployment perimeter (`SEC-012`)

- trusted-host and proxy policy;
- production security headers;
- HTTPS and HSTS behavior appropriate to the deployed environment.

### Public discoverability (`SEO-001`)

- canonical URLs and page metadata;
- robots and sitemap behavior;
- social metadata and no-index rules for protected or administrative pages.

## 6. Completion Definition

SmartBudgetSite is ready for its first public commercial release only when all
of the following are true:

1. Every item in the Official Release Backlog has reached its accepted end
   state.
2. Every Expected Release Gap has been completed and validated in the release
   environment.
3. The ordinary regression suite and the separate browser regression suite pass
   using the project-configured environment.
4. The complete Alembic chain and model/schema parity have been validated
   against PostgreSQL.
5. Every supported end-to-end customer journey in `operations.md` has been
   completed in the release environment, including its applicable admin
   follow-up.
6. External payment, storage, email, and Calendly behavior required by the
   release has been validated with real provider integrations.
7. Active documentation matches the released behavior, configuration, and
   operational procedures.
8. No unresolved release-critical architecture decision, security boundary, or
   data-recovery blocker remains.
9. A final Release Readiness Review defined in `operations.md` has been
   completed.

Passing tests alone does not satisfy this definition. Release readiness requires
the architectural, operational, provider, documentation, and end-to-end
conditions to hold together in the intended public environment.

## 7. Maintenance Philosophy

After the first public release:

- SmartBudgetSite changes should normally be small, focused, and independently
  reviewable;
- local improvements should be preferred over broad architectural rewrites;
- the existing route, service, repository, entitlement, and provider boundaries
  should be extended rather than replaced without an approved architecture
  decision;
- security updates, dependency maintenance, provider compatibility, recovery
  validation, and critical customer journeys remain ongoing responsibilities;
- deferred improvements should be driven by observed operational evidence or a
  concrete product need rather than speculative scale;
- the main product-development focus should return to SmartBudget Excel and its
  forecasting-first financial decision-support value.

Maintenance mode does not mean that SmartBudgetSite becomes static or
unimportant. It means that the site provides stable product infrastructure while
receiving bounded security, operational, compatibility, and customer-workflow
improvements.
