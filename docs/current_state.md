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

Infrastructure and quality:

- Serverspace account and Netherlands region availability are verified.
- Cloudflare Registrar ownership and DNS operation for `neocitrix.com` are
  verified; SmartBudgetSite has not yet been publicly deployed.
- Cloudflare R2 integration is implemented, but live R2 upload validation is
  deferred to the future VPS because the current local network cannot complete
  the TLS connection to the R2 S3 API.
- The latest recorded full automated test result is 143 passing tests at Sprint
  40. This is a historical test count, not a substitute for rerunning tests after
  code changes.

## Current launch constraint

The primary deployment blocker is international payment infrastructure. Hosting
availability, domain ownership, DNS infrastructure, Calendly account setup, and
backend implementation readiness are not the current blockers.

The project decision remains to continue development while banking and payment
infrastructure are arranged rather than block product work on that external
timeline.

## Immediate priorities

1. Implement real payment-provider checkout and webhook processing.
2. Orchestrate paid-sale transitions, entitlement creation, and customer delivery
   email.
3. Validate PostgreSQL migrations and SMTP behavior outside mocked tests.
4. Deploy to a public HTTPS environment and validate existing Calendly webhook
   processing with real payloads before changing reconciliation architecture.
5. Validate R2 connectivity, authenticated upload, stored metadata, and release
   persistence from the VPS.
6. Wire the Product Release publish action into the admin UI.
7. Add explicit, auditable download-entitlement reissue/reset support.
8. Integrate download support with the feedback flow, including a purchase or
   download issue type, preselection, and a masked support reference.

## Intentionally deferred

- strict one-time download completion and automatic completion detection
- richer download-attempt audit data and backend file proxying
- consultation cancellation synchronization
- persisted webhook audit storage, delivery correlation, metrics, and replay
  diagnostics
- advanced admin authentication beyond the accepted MVP token/cookie approach
- advanced BI, cohort, attribution, retention, CRM, helpdesk, and enterprise
  administration features

