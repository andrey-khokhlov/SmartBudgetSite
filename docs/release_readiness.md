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

This section is the authoritative remediation tracker for the accepted
release-critical findings. Each identifier has exactly one authoritative
description below. Audit, verification, and planning reports provide historical
context but do not override the accepted end states recorded here.

### Status model and task selection

Use only these statuses:

- `Not started` — no implementation with the required regression validation has
  been confirmed;
- `In progress` — implementation work has started but the accepted end state has
  not been fully validated;
- `Completed` — the accepted end state, required regression tests, and applicable
  documentation updates have all been confirmed;
- `Blocked` — work cannot proceed until a recorded dependency or approved
  external decision is resolved.

Items are ordered by the accepted remediation sequence. The next implementation
task is the first row whose status is not `Completed`. When related consecutive
items are marked as one task below, they should be delivered and validated
together even though each finding retains its own identifier.

**Current first incomplete item: `SEC-005` — Enforce webhook timestamp tolerance.**

| Order | Group | Identifier | Short title | Status |
|---:|---|---|---|---|
| 1 | Security configuration | `SEC-004` | Fail-closed production secrets | `Completed` |
| 2 | Security configuration | `SEC-006` | Secure production admin cookie | `Completed` |
| 3 | Feedback security | `SEC-001` | Protect private feedback listing | `Completed` |
| 4 | Feedback security | `SEC-002` | Protect feedback status mutation | `Completed` |
| 5 | Webhook operations | `OPS-002` | Preserve structured webhook audit fields | `Completed` |
| 6 | Calendly security | `SEC-005` | Enforce webhook timestamp tolerance | `Not started` |
| 7 | Release upload | `REL-003` | Bound release-upload resource use | `Not started` |
| 8 | Accessibility | `A11Y-001` | Declare the active document language | `Not started` |
| 9 | Database | `DB-001` | Restore model and migration parity | `Not started` |
| 10 | Consultations | `CODE-003` | Require paid consultation ownership | `Not started` |
| 11 | Calendly persistence | `CONS-001` | Persist webhook lifecycle transitions | `Not started` |
| 12 | Public purchase API | `SEC-003` | Require proof for purchase lookup | `Not started` |
| 13 | Feedback integrity | `CODE-002` | Verify ownership of the reviewed product | `Not started` |
| 14 | Feedback integrity | `CODE-001` | Persist the verified product association | `Not started` |
| 15 | Feedback transactions | `ARCH-003` | Make feedback submission atomic | `Not started` |
| 16 | Feedback layering | `ARCH-001` | Establish a feedback application boundary | `Not started` |
| 17 | Feedback storage | `SEC-011` | Define the attachment lifecycle | `Not started` |
| 18 | Accessibility | `A11Y-002` | Expose dynamic form status accessibly | `Not started` |
| 19 | Download security | `SEC-009` | Protect capability URLs across boundaries | `Not started` |
| 20 | Abuse protection | `SEC-007` | Establish coherent rate limits | `Not started` |
| 21 | Release storage | `REL-004` | Reconcile R2 and database side effects | `Not started` |
| 22 | Release workflow | `REL-005` | Complete administrative publication | `Not started` |
| 23 | Documentation | `DOC-002` | Define the port configuration contract | `Not started` |
| 24 | Documentation | `DOC-003` | Align Calendly lifecycle claims | `Not started` |

### Authoritative item descriptions

#### 1. `SEC-004` — Fail-closed production secrets

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Production settings accept empty `ADMIN_TOKEN` and `SECRET_KEY`,
  allowing the application to start without a valid administrative security
  boundary.
- **Accepted end state:** Production startup is impossible when required
  security secrets are absent or empty.
- **Dependencies:** None.
- **References:** [Backend configuration boundary](architecture/backend.md#configuration-boundary),
  [operations configuration rule](operations.md#configuration-completion-rule).

#### 2. `SEC-006` — Secure production admin cookie

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** The accepted MVP token/cookie administration model does not
  protect the admin cookie for production transport.
- **Accepted end state:** The MVP authentication model remains in place, while
  the admin cookie is protected in the production environment and remains usable
  in its intended development environment.
- **Dependencies:** `SEC-004`.
- **References:** [Consultation administration boundary](architecture/consultations.md#administration-and-operations),
  [deployment validation](operations.md#deployment-and-external-integration-validation).

#### 3. `SEC-001` — Protect private feedback listing

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** A public API endpoint can return recent private feedback,
  including customer and request metadata, without an administrative boundary.
- **Accepted end state:** No public endpoint exposes private feedback or its
  personally identifying data; operational feedback listing remains available
  only in the protected administrative context.
- **Dependencies:** None; delivered together with `SEC-002`.
- **References:** [Feedback protected admin workflow](architecture/feedback.md#protected-admin-workflow),
  [feedback authoritative rules](architecture/feedback.md#authoritative-business-rules).

#### 4. `SEC-002` — Protect feedback status mutation

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** A public API endpoint can change the resolved state of feedback
  without administrative authorization.
- **Accepted end state:** Feedback lifecycle mutations are available only within
  the protected administrative context.
- **Dependencies:** Delivered together with `SEC-001`.
- **References:** [Feedback protected admin workflow](architecture/feedback.md#protected-admin-workflow),
  [backend request flow](architecture/backend.md#request-flow).

#### 5. `OPS-002` — Preserve structured webhook audit fields

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Webhook processing supplies provider, event, and status fields to
  logging, but the active output contract does not preserve those fields for
  operations.
- **Accepted end state:** Operational webhook records contain the provider,
  event, and processing status needed to diagnose supported, rejected, ignored,
  and mismatched deliveries.
- **Dependencies:** None.
- **References:** [Calendly webhook boundary](architecture/consultations.md#webhook-boundary),
  [Release Readiness Review](operations.md#release-readiness-review).

#### 6. `SEC-005` — Enforce webhook timestamp tolerance

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** A correctly signed Calendly payload remains acceptable regardless
  of the age of its signed timestamp.
- **Accepted end state:** Webhook authenticity includes an explicit, tested
  tolerance window, and correctly signed events outside that window are rejected
  safely.
- **Dependencies:** `OPS-002` should precede final validation so rejection is
  observable.
- **References:** [Calendly webhook boundary](architecture/consultations.md#webhook-boundary),
  [reconciliation and idempotency](architecture/consultations.md#reconciliation-and-idempotency).

#### 7. `REL-003` — Bound release-upload resource use

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Administrative release upload can read an archive into process
  memory without an established size boundary.
- **Accepted end state:** Release upload has an enforced resource boundary and
  cannot consume unbounded application memory.
- **Dependencies:** None; must precede `REL-004`.
- **References:** [Release administration](architecture/commerce_and_delivery.md#release-administration),
  [file storage](architecture/commerce_and_delivery.md#file-storage).

#### 8. `A11Y-001` — Declare the active document language

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** The base document declares English even when the rendered page is
  Russian.
- **Accepted end state:** Every localized public page declares its actual active
  language consistently.
- **Dependencies:** None.
- **References:** [Operations validation policy](operations.md#validation-policy).

#### 9. `DB-001` — Restore model and migration parity

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** SQLAlchemy metadata and the PostgreSQL migration result disagree
  on consultation timestamp types and the active product-price uniqueness index.
- **Accepted end state:** Models, Alembic history, and PostgreSQL agree on
  timezone semantics while preserving the approved one-active-price domain
  invariant; a clean PostgreSQL parity check confirms the result.
- **Dependencies:** None; must precede final consultation persistence work.
- **References:** [Backend database schema parity](architecture/backend.md#database-schema-parity),
  [commerce ownership rules](architecture/commerce_and_delivery.md#sales-and-sale-items).

#### 10. `CODE-003` — Require paid consultation ownership

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Consultation entitlement creation does not enforce that the
  owning sale is paid.
- **Accepted end state:** A consultation entitlement can exist only for a valid
  paid consultation service item.
- **Dependencies:** `DB-001`.
- **References:** [Consultation entitlement](architecture/consultations.md#consultation-entitlement),
  [commerce sales and sale items](architecture/commerce_and_delivery.md#sales-and-sale-items).

#### 11. `CONS-001` — Persist webhook lifecycle transitions

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Calendly webhook processing mutates and flushes an entitlement,
  but the HTTP workflow does not complete the transaction, so the change is
  rolled back when the request session closes.
- **Accepted end state:** Successful supported Calendly webhook processing leaves
  the entitlement in the intended durable committed lifecycle state.
- **Dependencies:** `DB-001` and `CODE-003`; final validation also depends on
  `OPS-002` and `SEC-005`.
- **References:** [Backend transaction boundaries](architecture/backend.md#transaction-boundaries),
  [Calendly webhook boundary](architecture/consultations.md#webhook-boundary).

#### 12. `SEC-003` — Require proof for purchase lookup

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Customer email alone can retrieve purchase existence and detailed
  sale context through the public API.
- **Accepted end state:** A customer receives only the minimum purchase context
  belonging to them after sufficient proof of possession; the legitimate
  customer-facing flow remains available without exposing unnecessary internal
  identifiers.
- **Dependencies:** The public feedback boundaries in `SEC-001` and `SEC-002`
  should be stable first.
- **References:** [Commerce sales and sale items](architecture/commerce_and_delivery.md#sales-and-sale-items),
  [feedback support references](architecture/feedback.md#support-references).

#### 13. `CODE-002` — Verify ownership of the reviewed product

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Product-feedback verification checks a paid sale and email but
  does not prove that the reviewed product is one of that sale's items.
- **Accepted end state:** Product feedback is accepted only when the exact
  reviewed product belongs to the verified paid purchase.
- **Dependencies:** `SEC-003` establishes the purchase-proof boundary; delivered
  together with `CODE-001`.
- **References:** [Feedback authoritative rules](architecture/feedback.md#authoritative-business-rules),
  [SaleItem ownership](architecture/commerce_and_delivery.md#sales-and-sale-items).

#### 14. `CODE-001` — Persist the verified product association

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Accepted product feedback does not persist the product association
  established by purchase verification, preventing reliable product-scoped
  publication.
- **Accepted end state:** Every accepted product feedback record retains its
  verified product association, consistent with any stored sale context.
- **Dependencies:** Delivered together with and after the ownership rule in
  `CODE-002`.
- **References:** [Feedback publication and product reviews](architecture/feedback.md#publication-and-product-reviews),
  [feedback authoritative rules](architecture/feedback.md#authoritative-business-rules).

#### 15. `ARCH-003` — Make feedback submission atomic

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Feedback is committed before attachment persistence completes, so
  an attachment failure can return an error while leaving partial feedback state.
- **Accepted end state:** Feedback submission has one explicit transaction owner
  and completes with either the full accepted persistent result or no unintended
  partial state.
- **Dependencies:** `CODE-001` and `CODE-002`; delivered together with
  `ARCH-001`.
- **References:** [Backend transaction boundaries](architecture/backend.md#transaction-boundaries),
  [feedback browser and multipart validation](architecture/feedback.md#browser-and-multipart-validation).

#### 16. `ARCH-001` — Establish a feedback application boundary

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Feedback request handling owns validation, purchase decisions,
  filesystem work, persistence, and transaction behavior directly in the route.
- **Accepted end state:** The route owns only the HTTP boundary, while the
  existing service and repository layers own the feedback workflow according to
  their approved responsibilities.
- **Dependencies:** `CODE-001`, `CODE-002`, and `ARCH-003`; delivered together
  with `ARCH-003` after business behavior is stable.
- **References:** [Backend request flow](architecture/backend.md#request-flow),
  [backend feature pattern](architecture/backend.md#feature-implementation-pattern).

#### 17. `SEC-011` — Define the attachment lifecycle

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Per-file validation exists, but feedback attachments have no
  complete aggregate-capacity, cleanup, failure, retention, and operational
  access contract.
- **Accepted end state:** Attachments have explicit ownership, capacity,
  retention, failure, cleanup, and operational handling semantics consistent
  with an atomic feedback submission.
- **Dependencies:** `ARCH-003` and `ARCH-001`.
- **References:** [Feedback browser and multipart validation](architecture/feedback.md#browser-and-multipart-validation),
  [operations validation policy](operations.md#validation-policy).

#### 18. `A11Y-002` — Expose dynamic form status accessibly

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Dynamic feedback errors and status changes are not reliably
  announced or associated with their controls for assistive technologies.
- **Accepted end state:** Essential validation errors, state changes, and
  completion messages are available through the semantic accessibility contract
  of the form.
- **Dependencies:** The feedback response and error behavior from `ARCH-003` and
  `ARCH-001` should be stable first.
- **References:** [Feedback browser validation](architecture/feedback.md#browser-and-multipart-validation),
  [operations validation policy](operations.md#validation-policy).

#### 19. `SEC-009` — Protect capability URLs across boundaries

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Download and booking capability URLs can cross access-log and
  cache boundaries without a complete protection policy.
- **Accepted end state:** Capability URLs are not retained in unsafe caches or
  operational logs and do not propagate beyond the request contexts that require
  them.
- **Dependencies:** `SEC-003` should establish the related public data-access
  boundary first.
- **References:** [Commerce download entitlement](architecture/commerce_and_delivery.md#download-entitlement),
  [consultation booking token](architecture/consultations.md#booking-token-and-lifecycle).

#### 20. `SEC-007` — Establish coherent rate limits

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Public forms, purchase lookup, booking, downloads, and admin login
  have no coherent application-and-perimeter abuse policy.
- **Accepted end state:** Every abuse-sensitive entry point has an explicit,
  consistent limit and predictable failure behavior across the application and
  production perimeter.
- **Dependencies:** `SEC-001`, `SEC-002`, `SEC-003`, and `SEC-009` must establish
  the final protected endpoint contracts first.
- **References:** [Operations validation policy](operations.md#validation-policy),
  [Release Readiness Review](operations.md#release-readiness-review).

#### 21. `REL-004` — Reconcile R2 and database side effects

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Release upload performs an external storage side effect before the
  database workflow is guaranteed to succeed, allowing overwrite or orphaned
  object states.
- **Accepted end state:** Release upload has explicit conflict, retry, cleanup,
  and recovery semantics; a failed database operation cannot silently damage an
  existing object or leave an unowned object without a recoverable outcome.
- **Dependencies:** `REL-003`.
- **References:** [Release administration](architecture/commerce_and_delivery.md#release-administration),
  [file storage](architecture/commerce_and_delivery.md#file-storage).

#### 22. `REL-005` — Complete administrative publication

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** The visible administrative Publish control is a placeholder and
  does not execute the existing release publication lifecycle.
- **Accepted end state:** The administrative control performs the approved
  publication domain action and preserves the one-active-release invariant.
- **Dependencies:** `REL-004`.
- **References:** [Release administration](architecture/commerce_and_delivery.md#release-administration).

#### 23. `DOC-002` — Define the port configuration contract

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Active configuration and documentation use several port values
  without consistently defining whether they are application, host, development,
  or production bindings.
- **Accepted end state:** Every documented port has an explicit purpose,
  environment scope, and precedence, and startup instructions agree with that
  contract rather than forcing all environments to use one value.
- **Dependencies:** `SEC-004` and `SEC-006` should stabilize the production
  configuration boundary first.
- **References:** [Operations development commands](operations.md#development-commands),
  [configuration completion rule](operations.md#configuration-completion-rule).

#### 24. `DOC-003` — Align Calendly lifecycle claims

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Active documentation describes Calendly lifecycle synchronization
  as implemented even though the HTTP webhook transition is not durably
  committed.
- **Accepted end state:** Active documentation describes only the Calendly
  lifecycle behavior that has been confirmed through persistent request-level
  validation.
- **Dependencies:** `CONS-001` and `SEC-005`.
- **References:** [Current consultation state](current_state.md#current-project-state),
  [Calendly webhook architecture](architecture/consultations.md#webhook-boundary).

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
