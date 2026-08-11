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
- `REL-004` is complete. Release upload now uses unique opaque R2 keys, verifies
  object metadata before persistence, treats identical retries idempotently,
  rejects conflicting retries without storage changes, and compensates only
  after a fresh ownership check proves an attempt object is unowned.
- Uncertain ownership or cleanup failure returns an opaque operation reference
  and retains the object for founder-operated reconciliation. The reconciliation
  command is read-only by default and its explicit delete mode is age-gated,
  current-key-only, and protected by an immediate database ownership recheck.
- `REL-005` is complete. The administrative Publish control delegates to a
  service-owned transaction that locks the owning product row, verifies the
  persisted R2 object's size and SHA-256, deactivates the previous release, and
  activates the selected release. Re-publishing the active release safely
  re-verifies storage and preserves its original release timestamp.
- The normal administrative release path has now been validated against live
  Cloudflare R2 for `smartbudget-int-standard`: the test artifact
  `SmartBudget_UserGuide.zip` was persisted as `ProductRelease` version `0.1`,
  published, and shown as active/current with a release timestamp and
  `cloudflare_r2` storage. This is integration-validation evidence only; the
  artifact and version are not the final commercial SmartBudget release.
- `DownloadEntitlement` provides backend-controlled, tokenized access with a
  configurable expiry and retry limit.
- Payment preparation is provider-independent and creates pending records. The
  first bounded Lava.top checkout slice now adds provider-independent
  `PaymentProviderOffer` mappings, resolves the product/provider offer, calls
  the hosted invoice API, persists the returned invoice ID on the still-pending
  `Sale`, and returns the hosted payment URL. Provider failures preserve and
  mark the sale failed without creating entitlements.
- Lava.top Price-by-request mappings may share one external Offer ID across
  multiple internal SmartBudget products while remaining explicit per-product
  mappings. SmartBudgetSite remains authoritative for SKU identity, catalog
  currency and amount, Sale/SaleItem snapshots, releases, entitlements, and
  fulfillment. Provider offer identity is not sufficient by itself for payment
  fulfillment or reconciliation.
- The protected product Admin edit page now shows the Product's Lava.top mapping
  or a clear unconfigured state and supports creating or updating the external
  Offer ID through a service-owned transaction. It also reports informational
  checkout readiness and names any missing `in_sale` status, active price,
  active release, or Lava.top mapping prerequisite. Mapping changes do not call
  Lava.top, validate an Offer ID remotely, or mutate Product lifecycle state;
  the CLI mapping script remains available as fallback tooling.
- A manual live Lava.top smoke run through the existing SmartBudgetSite services
  validated the path from the current EUR catalog price and active
  `ProductRelease` through pending `Sale`/`SaleItem` preparation,
  `PaymentProviderOffer` resolution, real invoice creation, and persistence of
  the provider invoice ID in `Sale.external_payment_id`. The sale remained
  `pending`, and the hosted payment URL was deliberately not printed. This
  validates invoice creation, not payment confirmation or fulfillment; the
  current catalog amount is not asserted as final commercial pricing.
- Public product checkout now requires an explicit currency query parameter and
  resolves the active catalog price strictly by exact product slug and currency;
  buy-page links carry the currency of their displayed catalog price.
- Public checkout POST initiation now re-resolves the exact product, normalized
  currency, active catalog price, active release, provider offer, and optional
  consultation add-on server-side. Product and service snapshots are persisted
  as separate `SaleItem` rows, the `Sale` total is derived from those snapshots,
  and successful Lava.top invoice creation returns an HTTP 303 redirect to the
  hosted checkout URL.
- `/payment/result` now provides a neutral browser-return state and controlled
  initiation-error state. It does not treat browser return as payment proof,
  mark sales paid, create entitlements, expose delivery or booking access, or
  send purchase email.
- Authoritative Lava.top payment confirmation is implemented through a
  dedicated inbound `X-Api-Key` webhook for `payment.success` and
  `payment.failed`, plus an explicit server-to-server invoice lookup/manual
  reconciliation command. Both normalize provider data and reuse the same
  locked Sale reconciliation path keyed by provider invoice identity.
- A successful result now atomically changes a pending Sale to paid and creates
  one exact-release download entitlement per product item plus one consultation
  entitlement per consultation service item. Failed results change pending to
  failed without fulfillment. Same-result replay is idempotent; terminal
  conflicts and reconciliation mismatches do not rewrite history.
- Sales Admin keeps stale records in the authoritative `pending` status and
  distinguishes operational follow-up without introducing another payment
  status. Pending Sales at least 24 hours old show `Check needed` until an
  explicit provider lookup records a provider-independent `non_terminal`
  observation, after which they show `Checked — waiting`. The observation
  stores only the last-check time and generic result; it creates no fulfillment
  or email delivery state.
- A real 50 RUB hosted Lava.top payment succeeded provider-side. On 2026-08-10,
  Sale #6 was manually reconciled through the server-to-server invoice lookup:
  authoritative confirmation changed it from pending to paid and created
  exactly one `DownloadEntitlement` for its product `SaleItem`. It created no
  `ConsultationEntitlement` because the Sale contained no consultation item.
  Repeating the same reconciliation returned idempotent and did not duplicate
  fulfillment.
- The earlier 50 RUB Sale #5 remains pending because Lava.top reported its
  invoice as non-terminal (`NEW`/`IN_PROGRESS` equivalent). No payment status
  was forced manually for that Sale.
- On 2026-08-11, real Sale #7 was confirmed through the explicit authoritative
  server-to-server reconciliation path. Its purchase email was sent through
  Resend, the protected product access page opened, and the protected download
  completed successfully. This validates the manually reconciled product-only
  delivery journey, not automatic Lava.top webhook delivery.
- Live automatic webhook delivery/resend, product-plus-consultation live
  payment, result-page delivery UX, and end-to-end RUB/EUR payment and payout
  validation remain incomplete. Live Lava.top webhook delivery cannot be
  validated until SmartBudgetSite has a public HTTPS deployment or approved
  temporary public endpoint.
- Lava.top is the approved first production payment provider within the
  provider-independent architecture. Stripe remains the strategic long-term
  target after legitimate long-term Stripe infrastructure becomes available;
  it is not the next MVP implementation target.
- A real Lava.top creator account and SmartBudget creator profile now exist at
  the public slug `smartbudget`. `contact@neocitrix.com` is the Lava.top account
  contact, while `support@neocitrix.com` is the public customer-support address.
  The account UI confirms support for digital products, configurable pricing
  options including price by request through API, a payment-widget configuration
  flow, and provider-hosted file attachments. These observations remain
  account/UI evidence only; they are distinct from the separately confirmed
  invoice API contract and do not establish complete payment workflows or
  production validation.
- The Lava.top invoice contract is now confirmed: `POST /api/v3/invoice` uses
  server-owned `X-Api-Key` authentication and the `email`, `offerId`, `currency`,
  and `amount` fields; the response invoice `id` is the external payment identity
  and `paymentUrl` is the hosted checkout destination. RUB, USD, and EUR are
  supported for this flow, and the observed RUB minimum is 50 RUB. The provider
  Product ID and Offer ID are distinct; invoice creation uses the Offer ID.
- End-to-end production behavior remains unvalidated, and Lava.top attachments
  are intentionally not the SmartBudget delivery path; SmartBudgetSite-owned
  entitlements, protected access, purchase emails, and private R2 delivery
  remain required.
- Payment-success orchestration creates item-owned entitlements atomically.
  The same authoritative transaction creates exactly one
  `PurchaseEmailDelivery` per Sale, then commits before any email transport.
  Post-commit orchestration renders one product, consultation, or bundle email
  with SmartBudgetSite-protected access and sends it through the
  provider-independent transport boundary backed by Resend.
- Purchase-email states are `pending`, `sending`, `sent`, `failed`, and
  `reconciliation_required`. Claiming commits `sending`, attempt count, and
  attempt time before the external call. Normal Admin retry covers pending,
  failed, and ambiguous sending attempts younger than 23 hours using the stable
  `purchase-email/{delivery_id}` Resend idempotency key. A separate persisted
  sending-start timestamp prevents later retries from extending that window.
  Older ambiguous sends are lazily persisted as reconciliation-required and
  cannot use normal retry;
  a separate protected action requires the operator to confirm in Resend that
  the message was not sent before authorizing another attempt.
- Purchase-email delivery is disabled unless explicitly enabled. Enabled
  configuration requires the Resend key, sender identity, and server-owned
  public base URL. Automated coverage uses fake transports. Sale #7 confirms
  one live product-only Resend delivery and protected download journey;
  provider click-tracking behavior for capability links and the remaining
  customer journeys remain unvalidated.
- The approved MVP checkout uses hosted Lava.top checkout and returns to a
  SmartBudgetSite payment result page. Browser return is not proof of payment;
  paid state, entitlements, customer content, and purchase emails require an
  authenticated webhook or explicit server-to-server verification.
- The catalog-defined selected price determines currency: RUB for Russian
  customers and EUR for international customers. Payout routing remains
  operational rather than application business logic. The planned foreign EUR
  destination is Solo Bank, whose compatibility still requires production
  validation.

Consultations:

- Add-on and standalone consultation offers are distinguished by `usage_type`.
- Consultation ownership is represented by a backend-owned
  `ConsultationEntitlement` tied to a service `SaleItem`.
- Consultation Entitlements Admin manages purchased booking rights, but
  founder-operated consultation catalog management for `ServiceAddon` offers is
  not implemented. The next bounded sprint should add an Admin path to inspect
  and edit the existing offer fields needed for testing and operations,
  including price, currency, activation, and the existing catalog identity and
  usage fields. It must support configuring a temporary 50 RUB consultation
  offer for live validation without direct SQL while keeping catalog offers
  separate from entitlement administration.
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
- Public review navigation now renders a localized semantic HTML page at
  `/reviews/{slug}`, with complete empty and populated states. A service-level
  public projection limits template data to approved review content and excludes
  customer, purchase, support, moderation, and administrative metadata.
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

- `SEC-007` is complete at the application boundary. Abuse-sensitive feedback,
  purchase lookup, public checkout initiation, download, consultation,
  admin-authentication, and Calendly webhook requests use a thread-safe
  process-local rolling-window limiter with bounded HMAC identities,
  deterministic 429/`Retry-After` behavior, localized browser handling,
  privacy-safe coalesced logs, and fail-closed capacity behavior. Checkout
  initiation uses an IP-based limit of 8 attempts per 10 minutes before any
  catalog, sale, release, provider-offer, or Lava.top work.
- Initial production is restricted to one application worker. Counter reset on
  restart is an accepted bounded residual risk because the documented
  production perimeter is mandatory. Multi-worker production remains
  unsupported until a shared atomic backend is approved.
- The production perimeter and trusted-proxy behavior are not configured in
  this repository and remain release-environment validation obligations.
- `DOC-002` and `DOC-003` are complete, closing the Official Release Backlog.
  The port contract now distinguishes fallback, local, production-internal,
  Docker host/container, frontend-origin, and external-provider ports while
  preserving environment precedence. Active Calendly documentation reflects
  the confirmed request-level durable webhook commit and separately retains
  real-provider reconciliation as release-environment validation.
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
- A Vultr VPS in Amsterdam is provisioned and operational for secure external
  connectivity and future production-like integration validation.
- The Windows workstation uses Hiddify with XRay/VLESS Reality as the primary
  censorship-resistant connection and AmneziaVPN with AmneziaWG2 as the
  fallback. The XRay server configuration was independently validated through
  Hiddify; the XRay mode of the AmneziaVPN Windows client is not used because
  its TUN/tun2socks path produced incomplete browser traffic. Russian and
  international sites, ChatGPT voice mode, and localhost access were manually
  validated through Hiddify.
- Cloudflare Registrar ownership and DNS operation for `neocitrix.com` are
  verified; SmartBudgetSite has not yet been publicly deployed.
- Cloudflare R2 integration is implemented, and the normal live administrative
  upload, `ProductRelease` persistence, and publication path has been validated
  with a test artifact. Final commercial-release validation and live
  failure/retry/reconciliation exercises remain separate release-environment
  work.
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
  upgrade operations. The `PaymentProviderOffer` foundation migration was
  subsequently upgraded, downgraded, and re-upgraded against PostgreSQL at
  revision `7b91c5e2a4f0`, where `alembic check` again reported no new
  operations. Revision `3e91b7c2a6d4` removes only the provider/external Offer
  ID uniqueness constraint for shared Price-by-request mappings and has been
  applied successfully to the configured PostgreSQL development database. Its
  downgrade remains separate environment validation.
- The latest confirmed full ordinary suite result is 480 passing tests after
  the PaymentProviderOffer Admin and checkout-readiness implementation. The
  focused Admin, provider repository/script, payment, and checkout suite passes
  62 tests. The focused `REL-004` upload, storage,
  logging, repository, reconciliation, route, and download suite passes 77
  tests. The focused SEC-009 capability, logging, SQL, storage, helper-script,
  and support-isolation suite passes 50 tests. The focused Feedback
  rendered-contract and API suites pass 33 tests, and the browser suite passes
  15 tests. The focused Lava.top checkout, provider-offer repository, client,
  and configuration suite passes 38 tests. The public checkout initiation and
  result-page regression suite passes 13 tests; the focused checkout and
  SEC-007 rate-limit run passes 40 tests. The focused public review route and
  repository suite passes 9
  tests. The focused Calendly webhook route suite remains at 8 passing tests,
  including request-level durability validation through a fresh independent
  SQLAlchemy session.

## Current launch constraint

The payment release blocker is completing live validation of the approved
Lava.top integration and customer delivery: configure and validate webhook
delivery/resend after a public HTTPS endpoint exists, validate the EUR and live
product-plus-consultation paths, and validate the implemented purchase-email
workflow and protected delivery links in the deployed environment. The browser
result page remains neutral until a separately approved result-page redesign.
Availability of Stripe is not an MVP release dependency. Hosting availability,
domain ownership, DNS infrastructure, and Calendly account setup are not the
current blockers.

RUB payout routing is intended for a Russian destination. EUR payout routing is
intended for a foreign EUR destination, currently planned as Solo Bank, and
requires production compatibility validation before release. The project
decision remains to continue development while the approved payment and payout
operations are validated rather than block product work on future Stripe
infrastructure.

## Next sprint priorities

### 1. Complete the Expected Release Gaps

The Official Release Backlog is complete. Continue release preparation through
the authoritative Expected Release Gaps in `release_readiness.md`; select each
bounded implementation scope through the established architecture discussion
and review workflow rather than creating a parallel backlog.

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
- Public contact and social-link boundary: the current footer still exposes
  personal contact and profile links, and no final public-link architecture has
  been approved or implemented. Complete the mandatory architecture and UX
  review during the final public-site and release-polish phase without changing
  the current Official Release Backlog order; the authoritative release
  requirement is in
  [release readiness](release_readiness.md#public-contact-and-social-link-boundary-ux-001).
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
