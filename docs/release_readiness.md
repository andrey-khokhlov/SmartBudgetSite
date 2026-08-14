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

**Official Release Backlog status: all items completed.**

| Order | Group | Identifier | Short title | Status |
|---:|---|---|---|---|
| 1 | Security configuration | `SEC-004` | Fail-closed production secrets | `Completed` |
| 2 | Security configuration | `SEC-006` | Secure production admin cookie | `Completed` |
| 3 | Feedback security | `SEC-001` | Protect private feedback listing | `Completed` |
| 4 | Feedback security | `SEC-002` | Protect feedback status mutation | `Completed` |
| 5 | Webhook operations | `OPS-002` | Preserve structured webhook audit fields | `Completed` |
| 6 | Calendly security | `SEC-005` | Enforce webhook timestamp tolerance | `Completed` |
| 7 | Release upload | `REL-003` | Bound release-upload resource use | `Completed` |
| 8 | Accessibility | `A11Y-001` | Declare the active document language | `Completed` |
| 9 | Database | `DB-001` | Restore model and migration parity | `Completed` |
| 10 | Consultations | `CODE-003` | Require paid consultation ownership | `Completed` |
| 11 | Calendly persistence | `CONS-001` | Persist webhook lifecycle transitions | `Completed` |
| 12 | Public purchase API | `SEC-003` | Limit public purchase lookup disclosure | `Completed` |
| 13 | Feedback integrity | `CODE-002` | Verify ownership of the reviewed product | `Completed` |
| 14 | Feedback integrity | `CODE-001` | Persist the verified product association | `Completed` |
| 15 | Feedback transactions | `ARCH-003` | Make feedback submission atomic | `Completed` |
| 16 | Feedback layering | `ARCH-001` | Establish a feedback application boundary | `Completed` |
| 17 | Feedback storage | `SEC-011` | Define the attachment lifecycle | `Completed` |
| 18 | Accessibility | `A11Y-002` | Expose dynamic form status accessibly | `Completed` |
| 19 | Download security | `SEC-009` | Protect capability URLs across boundaries | `Completed` |
| 20 | Abuse protection | `SEC-007` | Establish coherent rate limits | `Completed` |
| 21 | Release storage | `REL-004` | Reconcile R2 and database side effects | `Completed` |
| 22 | Release workflow | `REL-005` | Complete administrative publication | `Completed` |
| 23 | Documentation | `DOC-002` | Define the port configuration contract | `Completed` |
| 24 | Documentation | `DOC-003` | Align Calendly lifecycle claims | `Completed` |

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
- **Completed behavior:** Consultation entitlement creation requires an owning
  sale whose payment status is `PaymentStatus.PAID`.
- **Regression validation:** Paid consultation creation succeeds, while pending,
  failed, refunded, missing-sale, product-item, non-consultation-service, and
  duplicate cases are covered by rejection tests.
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
- **Completed behavior:** The Calendly webhook HTTP route owns the successful
  request transaction. It commits only after webhook processing succeeds and
  returns HTTP 204 only after the commit completes. Lower-level lifecycle
  services continue to flush without owning the commit.
- **Regression validation:** The focused webhook route suite passes 8 tests. Its
  durability regression sends a signed request through the actual HTTP endpoint
  and confirms the booked lifecycle state through a fresh independent SQLAlchemy
  session after the request session closes. The full suite passes 252 tests.
- **Dependencies:** `DB-001` and `CODE-003`; final validation also depends on
  `OPS-002` and `SEC-005`.
- **References:** [Backend transaction boundaries](architecture/backend.md#transaction-boundaries),
  [Calendly webhook boundary](architecture/consultations.md#webhook-boundary).

#### 12. `SEC-003` — Limit public purchase lookup disclosure

- **Source:** Confirmed Defect; architecture decision: Accepted with Design
  Change.
- **Finding:** Customer email alone can retrieve purchase existence and detailed
  sale context through the public API.
- **Accepted end state:** The public lookup treats the entered customer email as
  a practical purchase lookup key, not as strong identity or mailbox proof. Its
  SEC-003 baseline returns only whether a qualifying paid product purchase
  exists. The later paired `CODE-002` and `CODE-001` work may add only the safe
  product context required to select the reviewed SKU. Purchase dates, internal
  sale, sale-item, or product identifiers, provider identifiers, and payment
  metadata remain excluded. Product-feedback ownership verification remains
  server-side, and internal identifiers never become part of the public browser
  contract.
- **Accepted residual risk:** Someone who knows a purchaser's email may submit
  feedback as that purchaser. This MVP risk is accepted because the flow exposes
  no downloadable product, payment information, or internal purchase record;
  permits no purchase modification; and remains subject to feedback moderation.
  Email confirmation, magic links, one-time codes, and an additional browser
  verification roundtrip are not required for MVP.
- **Implemented boundary:** At SEC-003 completion,
  `POST /v1/check-purchase` returned only `{"verified": true}` or
  `{"verified": false}`. The paired `CODE-002` and `CODE-001` implementation
  subsequently extended verified responses with an opaque purchase reference
  and public product name and edition so the exact reviewed SKU can be selected.
  Zero-purchase responses remain unchanged. The browser receives and submits no
  internal purchase identifier, and the public product-feedback contract does
  not accept `sale_id` or `product_id`. False, malformed, and error responses
  fail closed.
- **Regression validation:** The focused API suites pass 26 tests, the Feedback
  browser suite passes 7 tests, and the full ordinary suite passes 253 tests.
  `git diff --check` also passes.
- **Dependencies:** The public feedback boundaries in `SEC-001` and `SEC-002`
  should be stable first.
- **References:** [Commerce public purchase lookup](architecture/commerce_and_delivery.md#public-purchase-lookup),
  [feedback product-purchase lookup](architecture/feedback.md#product-feedback-purchase-lookup).

#### 13. `CODE-002` — Verify ownership of the reviewed product

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Product-feedback verification checks a paid sale and email but
  does not prove that the reviewed product is one of that sale's items.
- **Accepted end state:** Product feedback is accepted only when the exact
  reviewed product belongs to the verified paid purchase.
- **Completed behavior:** Paid product `SaleItem` rows for the normalized email
  are represented publicly by an opaque `purchase_reference` plus product name
  and edition. Submission resolves the reference only within paid product
  purchases owned by the supplied email, so forged, unpaid, missing, and
  cross-email references cannot select a product.
- **Regression validation:** Zero-, one-, and multiple-purchase lookup cases,
  forged-reference rejection, and wrong-email rejection are covered. The
  focused purchase-check and feedback API suites pass 29 tests, the Feedback
  browser suite passes 8 tests, and the full ordinary suite passes 256 tests.
- **Dependencies:** `SEC-003` establishes the public purchase-lookup boundary;
  delivered together with `CODE-001`.
- **References:** [Feedback authoritative rules](architecture/feedback.md#authoritative-business-rules),
  [SaleItem ownership](architecture/commerce_and_delivery.md#sales-and-sale-items).

#### 14. `CODE-001` — Persist the verified product association

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** Accepted product feedback does not persist the product association
  established by purchase verification, preventing reliable product-scoped
  publication.
- **Accepted end state:** Every accepted product feedback record retains its
  verified product association, consistent with any stored sale context.
- **Completed behavior:** After ownership validation, feedback creation receives
  only the internally resolved `product_id` and persists it on
  `FeedbackMessage`. The browser never receives or submits that identifier.
- **Regression validation:** The accepted product-feedback regression confirms
  that the exact resolved product ID is stored. The paired focused API suites
  pass 29 tests, the Feedback browser suite passes 8 tests, and the full
  ordinary suite passes 256 tests.
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
- **Completed behavior:** The feedback application service is the explicit
  transaction owner. Feedback and attachment repositories flush without
  committing. The service commits only after every accepted attachment file and
  database row is ready; failure rolls back the database session and removes
  every local file written by the submission.
- **Regression validation:** The focused feedback API and service suites pass 45
  tests, including validation, persistence, later-file, commit-failure,
  compensation, ownership, support-reference, and route-delegation cases. The
  Feedback browser suite passes 8 tests and the full ordinary suite passes 264
  tests.
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
- **Completed behavior:** The route translates the multipart HTTP request,
  normalizes the browser empty-file sentinel, and serializes the response. The
  application service owns business validation, ownership resolution, local
  file workflow, persistence orchestration, compensation, and transaction
  completion; repositories remain persistence-only.
- **Regression validation:** Route delegation is covered directly, and the
  focused feedback API and service suites pass 45 tests. The Feedback browser
  suite passes 8 tests and the full ordinary suite passes 264 tests.
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
- **Completed behavior:** Attachments remain in private local storage under
  `UPLOAD_DIR/feedback` and persist validated relative keys only. They share the
  owning feedback lifetime, support admin-authenticated downloads, enforce five
  files, 20 MiB per file, and 25 MiB combined, and log cleanup failures without
  replacing the original error. Reconciliation is read-only by default; its
  explicit deletion flag removes only validated generated orphan files below
  the feedback root.
- **Existing-data and schema validation:** The active PostgreSQL database was at
  Alembic head `2f6a9d7c4e10` with zero attachment rows before implementation,
  and the site has not yet been publicly deployed. No legacy key conversion or
  schema migration was required. PostgreSQL `alembic check` reported no new
  upgrade operations.
- **Regression validation:** The focused attachment, service, API, admin-route,
  and reconciliation suites pass 71 tests, the Feedback browser suite passes 8
  tests, and the full ordinary suite passes 290 tests.
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
- **Completed behavior:** Submission, purchase-verification, and attachment
  changes have separate localized atomic live regions. Progress and success use
  polite status semantics; failures use assertive alert semantics. Purchase
  outcomes are associated with the email and, when required, the
  multiple-purchase selector. Hidden controls are disabled and lose stale
  required or invalid state, while visible required controls continue to use
  native browser validation. A single verified purchase does not move focus;
  an Enter-triggered multiple-purchase check focuses the required selector once.
- **Regression validation:** The focused rendered Feedback contract and API
  suites pass 33 tests, including English and Russian markup. The Chromium
  Feedback suite passes 12 tests covering progress, success, repeated failure,
  purchase outcomes, error cleanup, required selection, hidden controls,
  attachment announcements, keyboard operation, focus, and successful reset.
  The full ordinary suite passes 292 tests.
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
- **Completed behavior:** Download and consultation booking path families apply
  private no-store cache headers and `Referrer-Policy: no-referrer` to successful
  pages, handled errors, unsupported methods, POST responses, and signed-R2
  redirects. Uvicorn access logging remains enabled but removes query strings
  and redacts literal or percent-encoded capability paths. SQLAlchemy hides
  bound parameters globally. Signed R2 responses carry private no-store and
  expired-date overrides without changing their TTL or attachment disposition.
  The development consultation helper masks its output unless the sensitive
  full-capability flag is explicitly supplied.
- **Regression validation:** The focused capability, access-log, SQL,
  signed-R2, helper-script, and support-isolation suite passes 50 tests. The
  full ordinary suite passes 312 tests. Changed-file Ruff and Black checks pass.
  Browser behavior and the not-yet-created production reverse-proxy/CDN
  configuration were not claimed as validated; the release environment must
  confirm access-log suppression, cache bypass, and provider telemetry behavior.
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
- **Completed behavior:** A project-owned, thread-safe process-local
  rolling-window limiter protects feedback before multipart parsing, purchase
  lookup by IP and normalized-email HMAC, public checkout initiation at 8
  attempts per 10 minutes per client IP before commerce or provider work,
  download and consultation route families by IP and capability HMAC, shared
  admin authentication failures, and Calendly before and after signature
  verification. Responses use deterministic HTTP 429, integer `Retry-After`,
  stable JSON or localized HTML, while capability responses retain SEC-009
  headers. Bounded state fails closed, rejection logging is coalesced and
  privacy-safe, and direct development disables proxy-header interpretation.
- **Production boundary:** Initial production supports exactly one application
  worker. Restart counter reset is an accepted bounded residual risk because
  the documented production perimeter is mandatory. Multi-worker production is
  prohibited until a shared atomic backend is approved. No proxy technology is
  selected or configured here; trusted-proxy and perimeter behavior remain
  release-environment validation obligations.
- **Regression validation:** The focused SEC-007 and affected-boundary suites
  pass 115 tests, the full ordinary suite passes 343 tests, and the Chromium
  Feedback suite passes 14 tests. Changed-file Ruff and Black checks and
  `git diff --check` pass.
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
- **Completed behavior:** Uploads use unique opaque managed keys, verify R2
  metadata before persistence, return an existing verified release for exact
  retries, reject material conflicts without storage changes, and classify
  concurrent constraint races. Compensation deletes only a proven-unowned
  attempt object after a fresh database ownership check; uncertainty or cleanup
  failure retains the object with an opaque operation reference.
- **Recovery:** The founder-operated reconciliation command reports missing,
  mismatched, unexpected, and orphaned objects without mutation by default.
  Explicit deletion is restricted to sufficiently old current-format orphan
  keys and repeats the database ownership check immediately before deletion.
- **Regression validation:** The focused REL-004 suite passes 77 tests and the
  full ordinary suite passes 398 tests. Changed-file Ruff and Black checks and
  `git diff --check` pass. A normal admin upload has now been validated against
  live R2 through `ProductRelease` persistence using a test artifact; live
  failure, retry, compensation, and reconciliation behavior remains
  release-environment validation.
- **Dependencies:** `REL-003`.
- **References:** [Release administration](architecture/commerce_and_delivery.md#release-administration),
  [file storage](architecture/commerce_and_delivery.md#file-storage).

#### 22. `REL-005` — Complete administrative publication

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Finding:** The visible administrative Publish control is a placeholder and
  does not execute the existing release publication lifecycle.
- **Accepted end state:** The administrative control performs the approved
  publication domain action and preserves the one-active-release invariant.
- **Required implementation boundary:** Acquire per-product database locking
  inside the publication transaction, verify storage before activation, and
  retain the existing unique active-release index as the final invariant.
- **Completed behavior:** The protected administrative Publish form invokes a
  thin route that delegates publication to `ProductReleaseService`. One
  service-owned transaction locks the release's owning `Product` row with
  PostgreSQL `SELECT ... FOR UPDATE`, loads the product's releases, verifies
  persisted R2 size and SHA-256 metadata, deactivates the prior active release,
  activates the selected release, and initializes `released_at` only when it is
  absent. Re-publishing the current release re-verifies storage and preserves
  the existing timestamp. Expected failures render safe administrative
  messages and leave publication state unchanged.
- **Regression validation:** The focused release publication and upload suites
  pass 55 tests, the broader release/admin regression set passes 64 tests, and
  the full ordinary suite passes 412 tests. PostgreSQL SQL compilation confirms
  `FOR UPDATE OF products`; the partial unique active-release index remains the
  final invariant. Changed-file Ruff and Black checks and `git diff --check`
  pass. The normal admin Publish action has now been manually validated for the
  live-R2 test release, including its active/current UI state and release
  timestamp. Live PostgreSQL blocking and failure-path behavior remain
  release-environment validation.
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
- **Completed behavior:** Operations documentation defines process environment,
  selected environment file, and `Settings` default precedence. It distinguishes
  the `8000` fallback application port, normal local `8800` application port,
  production-internal `4000` application port, PostgreSQL `5433 -> 5432`
  host/container mapping, and frontend development origin `5173`. The example
  environment and README commands now use the normal local workflow without
  changing Python defaults or deployment architecture.
- **Validation:** Active repository port references were reviewed against the
  contract, README commands use the configured local listener, and
  `git diff --check` passes.
- **Dependencies:** `SEC-004` and `SEC-006` should stabilize the production
  configuration boundary first.
- **References:** [Operations development commands](operations.md#development-commands),
  [configuration completion rule](operations.md#configuration-completion-rule).

#### 24. `DOC-003` — Align Calendly lifecycle claims

- **Source:** Confirmed Defect; architecture decision: Accepted.
- **Historical finding:** Active documentation described Calendly lifecycle
  synchronization as implemented before the HTTP webhook transition had
  request-level durability validation.
- **Accepted end state:** Active documentation describes only the Calendly
  lifecycle behavior that has been confirmed through persistent request-level
  validation.
- **Completed behavior:** The Calendly webhook HTTP route owns the successful
  request transaction, commits after processing succeeds, and returns HTTP 204
  only after the commit. Lower-level lifecycle services remain flush-only. A
  request-level regression confirms the booked entitlement through a fresh
  independent database session after the request session closes.
- **Remaining external validation:** No real Calendly webhook subscription
  exists yet. A real provider payload and the initial entitlement
  reconciliation strategy remain unvalidated release-environment work.
- **Dependencies:** `CONS-001` and `SEC-005`.
- **References:** [Current consultation state](current_state.md#current-project-state),
  [Calendly webhook architecture](architecture/consultations.md#webhook-boundary).

## 5. Expected Release Gaps

The following work is mandatory before the first public commercial release, but
it is planned release completion rather than remediation of existing backend
defects.

### Commerce and fulfillment (`REL-001`)

Partial integration validation is complete: the normal admin upload and Publish
path reached live R2, persisted a test `ProductRelease`, and activated it. A
manual live Lava.top smoke run through SmartBudgetSite services then resolved
the current catalog price, active release, and provider offer; created a pending
`Sale`/`SaleItem`; called the real invoice API; and persisted the returned
invoice ID in `Sale.external_payment_id`. The hosted payment URL was not printed.
The test release and current catalog amount are not final commercial release or
pricing claims.

The public checkout now posts customer email, explicit currency, and the
selected consultation state to SmartBudgetSite. Server-side orchestration
re-resolves every authoritative commerce value, persists separate product and
optional consultation snapshots, derives the sale total from those items, and
returns HTTP 303 to the hosted Lava.top checkout. `/payment/result` provides
only a neutral pending state, and expected initiation failures render an opaque
customer-facing result without creating paid or fulfillment state.
No Lava.top browser return to SmartBudgetSite is currently integrated, so a
buyer may remain on Lava.top after payment; browser navigation is not payment
proof.

The first authoritative confirmation and fulfillment slice is implemented:
authenticated Lava.top Payment-result events and explicit invoice lookup share
one provider-independent reconciliation path, and success atomically creates
all product/consultation entitlements. Conflicts remain operator-visible and do
not rewrite terminal history.

Server-to-server reconciliation has now been validated against a real 50 RUB
payment: Sale #6 moved from pending to paid, received exactly one product
download entitlement and no consultation entitlement, and repeated
reconciliation was idempotent. The earlier Sale #5 correctly remained pending
when Lava.top reported a non-terminal invoice; its status was not forced.
On 2026-08-11, real Sale #7 was also authoritatively reconciled through the
manual path; its purchase email was sent through Resend, protected product
access opened, and the protected download completed successfully.
On 2026-08-14, real Sale #8 validated a 100 RUB bundle payment (50 RUB product
plus 50 RUB consultation). Lava.top reported the invoice as `COMPLETED`; manual
reconciliation changed the Sale to paid and made exactly one product entitlement
and one consultation entitlement available. The purchase email was sent and
both protected access pages opened. This did not exercise live webhook delivery
or a browser return from Lava.top.

The founder-operated Lava.top full-refund workflow is implemented without an
undocumented provider API. A unique provider-independent `RefundOperation`
records pending intent and immutable Sale/provider snapshots; only an explicit
post-provider verification acknowledgement atomically confirms the refund,
marks the Sale refunded, and revokes future product and consultation access
while preserving historical entitlement and provider metadata. Lava.top UI
evidence from a real 50 RUB refund confirms the displayed amount, `SENT` marker,
and refund date, but does not establish bank settlement or an API/lookup/webhook
contract. The complete SmartBudgetSite Admin refund journey still requires live
release-environment validation.

The focused refund service, Admin, locking, protected-access, and schema-parity
suite passes 54 tests, and the full ordinary suite passes 612 tests.

`REL-001` remains incomplete. The manual product-only and bundle reconciliation
and delivery evidence is not live webhook or deployed-environment validation.
The purchase-email workflow, Resend adapter, stable-key retry
behavior, and
protected Admin retry controls are implemented with automated fake-transport
coverage, but still require deployed-environment validation. Remaining work is:

- configure and validate live webhook delivery, history, resend, and conflict
  operations when a public HTTPS deployment or approved temporary endpoint is
  available;
- deployed customer purchase-email delivery validation, provider
  tracking/link-rewriting configuration, and the
  reconciliation-required operator path;
- production validation of the RUB and EUR payment flow, including Solo Bank
  compatibility for the currently planned foreign EUR payout destination.
- live founder execution of the protected pending-to-confirmed full-refund Admin
  journey against a disposable paid Sale, including post-refund download and
  consultation access denial; do not interpret Lava.top `SENT` as bank/card
  settlement confirmation.

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

### Public contact and social-link boundary (`UX-001`)

Before the first public commercial release, the final public-site and
release-polish phase must include an explicit architecture and UX review of the
footer and every other public contact or social link. The resulting policy must
be approved, implemented, and validated across public pages before this release
gap is complete. It must define:

- how founder identity and informational professional-profile links are
  presented;
- whether official product social accounts exist and what role they serve;
- the official customer-support and paid-consultation entry points;
- whether any personal messaging account may be exposed by the product;
- how inactive, empty, or abandoned product social channels are excluded;
- ownership, configuration, localization, and future replacement of every
  public link.

The current direction for that review is provisional rather than final
architecture:

- customer support continues through the official Feedback/support process;
- paid consultation requests continue through the approved Consultation →
  Checkout → Calendly journey;
- personal Telegram and WhatsApp links should not remain public product contact
  channels unless a later explicit architecture decision justifies them;
- LinkedIn may remain as an informational founder professional-profile link only
  if the architecture and page wording make clear that it is not a support
  channel;
- Facebook requires review because a personal profile may provide insufficient
  trust value relative to the weaker professional boundary it creates;
- a Telegram product channel must not be created or linked merely to fill a
  social-media slot; an empty or abandoned channel is worse than no channel;
- the final link set is intentionally minimal and does not imply real-time
  personal support.

SmartBudgetSite is not release-ready while personal contact channels remain
public without this explicit approved architecture and its corresponding
implementation. This gap is final public-site and release-polish work; it does
not change the order or current first incomplete item in the Official Release
Backlog.

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
