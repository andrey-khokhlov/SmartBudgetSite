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
- The protected booking page validates the entitlement before exposing the
  configured Calendly URL.
- Booking lifecycle, normalized webhook handling, real HMAC verification,
  reconciliation orchestration, replay-safe transitions, and admin visibility
  are implemented.
- Calendly webhook signatures enforce a symmetric, inclusive 180-second
  timestamp tolerance at the HTTP transport boundary. This is separate from the
  idempotent consultation lifecycle transitions applied after verification.
- Manual Calendly booking, Google Meet, email, cancellation, Google Calendar,
  API, and PAT validation are complete.
- No Calendly webhook subscription exists yet. A public HTTPS endpoint and real
  webhook capture are still required to validate first-booking reconciliation.
  `provider_event_uri` is confirmed for replay/idempotency, not for initially
  finding an entitlement.

Feedback:

- Feedback administration is consolidated behind protected admin routes.
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

Infrastructure and quality:

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
- The latest confirmed full automated test result is 242 passing tests after
  completion of `A11Y-001`.

## Current launch constraint

The primary deployment blocker is international payment infrastructure. Hosting
availability, domain ownership, DNS infrastructure, Calendly account setup, and
backend implementation readiness are not the current blockers.

The project decision remains to continue development while banking and payment
infrastructure are arranged rather than block product work on that external
timeline.

## Next sprint priorities

### 1. Smart Feedback support flow

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

### 2. Continue release-readiness validation

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
- consultation cancellation synchronization
- persisted webhook audit storage, delivery correlation, metrics, and replay
  diagnostics
- advanced admin authentication beyond the accepted MVP token/cookie approach
- advanced BI, cohort, attribution, retention, CRM, helpdesk, and enterprise
  administration features
