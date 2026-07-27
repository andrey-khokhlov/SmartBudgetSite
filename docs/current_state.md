# Current State

## Purpose

This document is the authoritative snapshot of current implementation state,
external constraints, deferred work, and immediate priorities. Architectural
rules belong in the documents under `docs/architecture/`; chronological details
belong in `docs/history/sprint_checkpoints.md`.

## Current project state

Operational:

- Admin Dashboard
- Products admin
- Product Releases admin foundation and upload flow
- Feedback admin
- Consultation Entitlements admin
- Sales admin
- admin filtering and pagination
- protected consultation booking page
- protected product download page

Commerce and delivery:

- `Sale` is the order header and `SaleItem` is the purchased-item snapshot.
- New product sale items are fixed to the active `ProductRelease` during payment
  preparation.
- Product release archives are uploaded through the admin flow to private
  Cloudflare R2 storage.
- Release archives have an inclusive application-level limit of 50 MiB. Size
  and SHA-256 metadata are calculated in bounded 1 MiB chunks without buffering
  the complete archive in route memory; larger archives receive HTTP 413 before
  R2 upload or `ProductRelease` persistence.
- `DownloadEntitlement` provides backend-controlled, tokenized access with a
  configurable expiry and retry limit.
- Payment preparation is provider-independent and creates pending records, but
  real Stripe Checkout Session creation and payment webhook processing are not
  implemented.
- Payment-success orchestration does not yet create download entitlements or
  send purchase emails containing download links.

Consultations:

- Add-on and standalone consultation offers are distinguished by `usage_type`.
- Consultation ownership is represented by a backend-owned
  `ConsultationEntitlement` tied to a service `SaleItem`.
- `CODE-003` is complete: consultation entitlement creation requires a
  consultation service item owned by a `PaymentStatus.PAID` sale.
- The protected booking page validates the entitlement before exposing the
  configured Calendly URL.
- Booking lifecycle, normalized webhook handling, real HMAC verification,
  reconciliation orchestration, replay-safe transitions, and admin visibility
  are implemented.
- Calendly webhook signatures enforce a symmetric, inclusive 180-second
  timestamp tolerance at the HTTP transport boundary. This is separate from the
  idempotent consultation lifecycle transitions applied after verification.
- `CONS-001` is complete: the Calendly webhook HTTP route owns the successful
  request transaction, commits only after webhook processing succeeds, and
  returns HTTP 204 only after the commit completes. Lower-level consultation
  lifecycle services continue to flush without owning the commit.
- Manual Calendly booking, Google Meet, email, cancellation, Google Calendar,
  API, and PAT validation are complete.
- No Calendly webhook subscription exists yet. A public HTTPS endpoint and real
  webhook capture are still required to validate first-booking reconciliation.
  `provider_event_uri` is confirmed for replay/idempotency, not for initially
  finding an entitlement.

Feedback:

- Feedback administration is consolidated behind protected admin routes.
- `SEC-003`, `CODE-002`, and `CODE-001` are complete. A zero-purchase response
  from `POST /v1/check-purchase` remains exactly `{"verified": false}`. A
  qualifying email receives only opaque `purchase_reference` values plus public
  product name and edition; internal sale, sale-item, product, payment, and
  provider identifiers remain backend-only.
- One paid product purchase is selected automatically without displaying a
  selector. Multiple paid product purchases display a product selector. False,
  malformed, and request-error responses fail closed.
- Product-feedback submission sends the normalized email and opaque
  `purchase_reference`. The service resolves the reference only against paid
  product `SaleItem` ownership for that email, rejects forged or cross-email
  references, and persists the verified `product_id` on the feedback record.
  Email remains a practical lookup key, not proof of identity or mailbox
  ownership.
- The current implementation still publishes approved product feedback from
  `feedback_messages` via `is_published`.
- The intended separation into private feedback and distinct curated public
  review/Q&A entities remains future work.
- Protected download pages link to Feedback with `purchase_or_download_issue`;
  an existing `DL-*` reference is resolved server-side through the service and
  repository layers before any customer context is shown.
- Successful download-context lookup prefills the customer email, readonly
  support reference, public product name and edition, release version, purchase
  date, subject, and initial message in English or Russian. Customer-editable
  fields remain editable and submission always requires an explicit Send.
- Unknown, malformed, or `PAY-*` references expose no customer context and are
  not displayed. A separately supplied safe
  `message_type=purchase_or_download_issue` may remain selected.
- Download entitlements own unique random `DL-XXXXXXXX` support references;
  feedback stores an optional generic copy without a foreign key. Download
  tokens and provider/storage details are not exposed through this workflow.
- The generic field is compatible with future `PAY-*` references, but payment
  support-reference generation is not implemented.
- `ARCH-003` and `ARCH-001` are complete. The Feedback HTTP route now translates
  the multipart request and delegates the full submission workflow to the
  feedback application service.
- The feedback submission service is the explicit transaction owner.
  Repositories flush feedback and attachment rows without committing. The
  service commits only after all accepted local attachment files and rows are
  ready; validation, persistence, file-write, or commit failure rolls back the
  database transaction and removes files written by that submission.
- `SEC-011` is complete. Feedback attachments use private local storage under
  `UPLOAD_DIR/feedback` and persist only validated relative
  `feedback/<random-name>.<extension>` keys. Submissions allow at most five
  files, 20 MiB per file, and 25 MiB combined.
- Attachments share their owning feedback record's retained lifetime and are
  downloadable only through the protected admin feedback detail workflow.
  Cleanup failures are logged without customer content and without replacing
  the original submission error.
- The founder-operated reconciliation command reports missing files, orphan
  files, and unsafe keys without mutation by default. Its explicit deletion mode
  removes only validated generated orphan files below the feedback root.
- `A11Y-002` is complete. Submission, purchase-verification, and attachment
  changes use distinct localized live regions: progress and success are polite,
  while failures are assertive. Purchase errors are associated with the email
  control, the multiple-purchase selector is exposed as required, and hidden or
  corrected controls clear obsolete required, invalid, and error associations.
  Single-purchase verification no longer moves focus; an Enter-triggered
  multiple-purchase check moves focus once to the required selector.

Infrastructure and quality:

- `SEC-009` is complete. Download and consultation booking capability responses
  use private no-store cache headers and `Referrer-Policy: no-referrer`,
  including handled errors, unsupported methods, and the signed-R2 redirect.
  Uvicorn access records omit query strings and redact literal or percent-encoded
  capability paths while retaining ordinary request diagnostics. SQLAlchemy
  hides bound parameters globally, signed R2 responses override cache behavior,
  and the development consultation helper reveals the full capability only
  through an explicit sensitive-output flag.
- Production reverse-proxy access-log suppression, CDN cache bypass, and
  provider telemetry behavior remain release-environment validation obligations;
  no proxy technology or deployment configuration was introduced by `SEC-009`.
- Serverspace account and Netherlands region availability are verified.
- Cloudflare Registrar ownership and DNS operation for `neocitrix.com` are
  verified; SmartBudgetSite has not yet been publicly deployed.
- Cloudflare R2 integration is implemented, but live R2 upload validation is
  deferred to the future VPS because the current local network cannot complete
  the TLS connection to the R2 S3 API.
- A separate Playwright/Chromium browser regression layer protects critical
  client-side behavior without changing ordinary pytest discovery. Playwright
  remains a development/test-only dependency.
- Structured webhook audit fields preserve provider, event type, and processing
  status in operational console log output without changing ordinary log output.
- Localized public HTML documents declare the resolved English or Russian
  language, while the currently English administrative interface declares
  English independently of the selected public UI locale.
- `DB-001` is complete. A clean PostgreSQL database migrated through the full
  Alembic chain to `2f6a9d7c4e10`; the three consultation entitlement
  timestamps use `timestamp with time zone`, the existing active-price partial
  unique index matches SQLAlchemy metadata, and `alembic check` reported no new
  upgrade operations.
- The latest confirmed full ordinary suite result is 312 passing tests after
  completion of `SEC-009`; the focused SEC-009 capability, logging, SQL,
  storage, helper-script, and support-isolation suite passes 50 tests. The
  focused Feedback rendered-contract and API
  suites pass 33 tests and the Feedback browser suite passes 12 tests. The
  focused Calendly webhook route
  suite remains at 8 passing tests, including request-level durability
  validation through a fresh independent SQLAlchemy session.

## Current launch constraint

The primary deployment blocker is international payment infrastructure. Hosting
availability, domain ownership, DNS infrastructure, Calendly account setup, and
backend implementation readiness are not the current blockers.

The project decision remains to continue development while banking and payment
infrastructure are arranged rather than block product work on that external
timeline.

## Next sprint priorities

### 1. Continue the Official Release Backlog

The first incomplete Official Release Backlog item is `SEC-007` — establish
coherent rate limits. Continue in the authoritative order defined
in `release_readiness.md`; do not substitute roadmap work for the next
incomplete remediation item.

### 2. Smart Feedback support flow (later work)

Extend the fully prefilled Feedback experience to payment failures. The bounded
download-support slice is implemented; payment support-reference generation and
prefill remain future work.

The support form should automatically populate:

- message type;
- customer email;
- support reference;
- product information;
- known purchase context;
- an initial support message.

The expected user workflow is:

`Review` → optionally edit → `Send`

This remains planned support-flow work after the applicable Official Release
Backlog priorities. It is separate from the Expected Release Gaps roadmap in
`release_readiness.md`.

### 3. Continue release-readiness validation

Continue manually validating complete end-to-end user journeys as major
functionality is completed.

Each discovered issue should be evaluated for:

- browser regression coverage;
- backend regression coverage;
- documentation improvements;
- user experience improvements.

Treat release readiness as an incremental activity rather than a final project
phase.

## Intentionally deferred

- strict one-time download completion and automatic completion detection
- richer download-attempt audit data and backend file proxying
- Feedback form UI polish: apply the project's primary button style to the
  submit control and bring the file-selection control into the site design;
  these are known non-blocking release-polish items
- Landing consultation CTA refresh: replace the outdated direct Telegram contact
  flow with the finalized consultation journey and rewrite the section headline,
  supporting copy, CTA label, and destination to reflect the approved
  Consultation → Checkout → Calendly flow; complete this during the final landing
  page and release-polish pass
- Administrative feedback deletion workflow: implement a protected admin-only
  workflow for permanently deleting Feedback messages together with their
  attachments. The implementation should preserve the approved attachment
  lifecycle, safely clean up filesystem objects, and remain independently
  reviewable after completion of the Official Release Backlog.
- consultation cancellation synchronization
- persisted webhook audit storage, delivery correlation, metrics, and replay
  diagnostics
- advanced admin authentication beyond the accepted MVP token/cookie approach
- advanced BI, cohort, attribution, retention, CRM, helpdesk, and enterprise
  administration features
