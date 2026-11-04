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
- `/payment/result` now provides a neutral verification state and controlled
  initiation-error state. No Lava.top browser return is currently integrated,
  and the buyer may remain on Lava.top after payment. The route does not treat
  browser navigation as payment proof,
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
- Sales Admin now provides a founder-operated, full-refund-only workflow. One
  provider-independent `RefundOperation` snapshots the paid Sale amount,
  currency, provider, and external payment identity in `pending`; a database
  uniqueness invariant prevents a second operation for the Sale. SmartBudgetSite
  does not call a Lava.top refund API. After the founder manually completes and
  verifies the exact refund in Lava.top Sales, a second explicit acknowledgement
  atomically confirms the operation, changes the Sale to `refunded`, cancels
  available product/consultation entitlements, and preserves completed, booked,
  expired, cancelled, provider-event, and attempt history. Protected download
  and booking validation also fails closed unless the owning Sale remains paid.
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
- On 2026-08-14, real Sale #8 validated a 100 RUB bundle payment (50 RUB
  product plus 50 RUB consultation). Lava.top reported the invoice as
  `COMPLETED`; manual reconciliation changed the Sale to paid and made exactly
  one product entitlement and one consultation entitlement available. The
  purchase email was sent and both protected access pages opened. The founder
  then issued the full 100 RUB refund manually; Lava.top showed `SENT` and a
  refund date, and explicit SmartBudgetSite confirmation changed Sale #8 to
  refunded. Both old product and consultation capabilities were denied after
  refund. The money was later returned to the customer's bank card while
  Lava.top continued to display `SENT`; no later provider UI state was observed.
  `SENT` is provider refund evidence, not proof of final bank/card settlement.
  This did not validate live webhook delivery or a browser return from Lava.top.
- Live automatic webhook delivery/resend and end-to-end RUB/EUR payment and
  payout validation remain incomplete. Live Lava.top webhook delivery cannot be
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
  public base URL. Automated coverage uses fake transports. Sales #7 and #8
  confirm live product-only and bundle Resend delivery plus protected access;
  provider click-tracking behavior for capability links and the remaining
  customer journeys remain unvalidated.
- The approved MVP checkout uses hosted Lava.top checkout. No Lava.top browser
  return is currently integrated, so the buyer may remain on Lava.top after
  payment; `/payment/result` remains a neutral verification route. Paid state,
  entitlements, customer content, and purchase emails require the authenticated
  webhook or founder-operated explicit server-to-server verification.
- The catalog-defined selected price determines currency: RUB for Russian
  customers and EUR for international customers. Payout routing remains
  operational rather than application business logic. The planned foreign EUR
  destination is Solo Bank, whose compatibility still requires production
  validation.

Consultations:

- Add-on and standalone consultation offers are distinguished by `usage_type`.
- Protected founder-operated Consultation Offers Admin now lists, creates, and
  maintains consultation `ServiceAddon` catalog records separately from
  purchased entitlements. New records use server-generated UUID technical
  codes; routing identity fields are immutable after creation; deactivation is
  the removal mechanism and no physical delete path is exposed.
- Active consultation-offer identity and resolution include `family_slug`,
  `package_code`, `service_type`, `usage_type`, and `currency_code`. Creating or
  activating a version atomically deactivates the other active offer with the
  same full identity, while different currencies and usage types remain
  independent. Product-plus-consultation checkout selects the offer in the
  exact product currency.
- Consultation ownership is represented by a backend-owned
  `ConsultationEntitlement` tied to a service `SaleItem`.
- Elapsed available consultation entitlements are lazily reconciled to the
  persisted `expired` status when Consultation Entitlements Admin is opened,
  before filtering and pagination. Booked and cancelled history is preserved;
  MVP requires no scheduler or background expiration worker.
- Consultation Entitlements Admin continues to manage purchased booking rights,
  not catalog offers.
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
- The latest confirmed full ordinary suite result is 615 passing tests after
  the founder-operated full-refund implementation. The focused refund service,
  Admin, locking, capability-boundary, and schema-parity suite passes 54 tests. The
  earlier PaymentProviderOffer Admin and checkout-readiness focused suite
  remains at 62 tests. The focused `REL-004` upload, storage,
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

## Approved SmartBudget 1.0 commercial position

On 2026-10-26, the project owner approved launch pricing and perpetual use of
the purchased SmartBudget 1.0 release: one-time purchase, no subscription,
including budgeting for future years. Consultation remains an optional paid
service. The authoritative launch price table is in
`architecture/commerce_and_delivery.md`, with consultation pricing and sales
modes in `architecture/consultations.md`; durable positioning is in
`product_positioning.md`.

These are the intended release catalog/UI values, not a claim that the database,
Lava.top mappings/offers, or public website have been updated. Applying them is
separate execution work. The update/support/EULA policy remains unresolved and
required before publication under `REL-001` in `release_readiness.md`.

## Current launch constraint

The remaining live validation of the approved Lava.top integration and customer
delivery requires the real deployed HTTPS environment. Production deployment
and that validation are intentionally deferred until the approved
pre-deployment release gates below are complete. No Lava.top browser return is
currently integrated; `/payment/result` remains neutral unless a supported
return flow is separately approved and implemented.
Availability of Stripe is not an MVP release dependency. Hosting availability,
domain ownership, DNS infrastructure, and Calendly account setup are not the
current blockers.

RUB payout routing is intended for a Russian destination. EUR payout routing is
intended for a foreign EUR destination, currently planned as Solo Bank, and
requires production compatibility validation before release. The project
decision remains to continue development while the approved payment and payout
operations are validated rather than block product work on future Stripe
infrastructure.

## Next active phase and release sequence

### 1. Updated release materials ready; review releases stale

As of the 2026-11-04 owner update, the SmartBudget workbook has been revised for
ActiveX onboarding and blocked-state guidance. The RU Walkthrough and EN
Walkthrough have each been revised, and both RU and EN customer ZIP archives
have been rebuilt. These content/rebuild steps are owner-confirmed complete;
they were not independently inspected in this documentation sprint.

Excel 2021 detection, blocked-state detection, opening Trust Center, required
configuration and continuing startup after correction are owner-verified.
Complete Microsoft 365 ActiveX validation still requires confirmation; automatic
`{UP}` navigation remains unverified. Final public RU/EN guidance is pending
editorial approval under R47. SmartBudget does not change security settings.

The previously uploaded review-environment RU/EN `ProductRelease 1.0` archives
contain earlier bytes and are now stale. Safely replacing them and verifying the
new bytes remain pending under R48. The commercial version stays **1.0**.
Customer-visible ZIP filenames may remain unchanged and are not replacement
proof. Required proof for each language is local SHA-256 and size matched to
persisted release metadata, verified R2 object metadata and the served object,
plus active/current state and one active release per SKU.

A later bounded operational task must first inspect `smartbudget_review` release
references, including `SaleItem`, `DownloadEntitlement` and any other persistent
owners. Referenced releases must trigger a stop and escalation. Only if safe and
unreferenced may a minimal review-only reset/replacement procedure be defined,
followed by normal Admin upload/publication under the isolated review prefix.
Do not weaken immutable/idempotent release identity, overwrite an R2 object or
invent version 1.1. No review database or storage operation was performed here.

A separate Product Description remains intentionally excluded: the bilingual
Walkthrough is the accepted detailed customer guide. Rebuilt materials alone
do not close release-material validation or make SmartBudgetSite release-ready.

### 2. G1 and scoped Landing G2A/G7/G8 implemented

The R01–R55 mapping was completed against local HEAD `cd5190b` and independently
reviewed and accepted. The [implementation-state snapshot below](#release-uiux-implementation-mapping)
records all accepted statuses, unresolved decisions, corrected groups and
validation/operational dependencies. It is static repository analysis, not
runtime/provider validation or implementation completion.

**G1's accepted implementation end state is complete** against baseline
`df8ab87`: both language segments are visible, only the inactive segment links,
checkout path/currency/add-on state survives switching, and About/Products have
semantic active states. Successful booking rendering now shares locale-cookie
persistence. Unsent checkout email is not persisted; activating the current
language does not navigate or clear typed input. No R04+ functionality was added.

**G2A and the accepted G7/G8 Landing scope are implemented** against `7034dcb`:
Hero, resilience levels, future expense, PLAN/ACTUAL and reconciliation use the
approved RU/EN copy and supplied final assets. The obsolete Telegram block is
removed. Only the existing temporary Buy tail remains; G9 practical/commercial
content and Landing pricing were not implemented. G9 remains separate and
partly blocked by D1/destination dependencies. G2B/R04 remains blocked by D2. The future Consultations entry is
owned by R06/G12; full-register R03 remains Partial only for that integration,
while all R03 behavior explicitly accepted for G1 is implemented.

`release_uiux_requirements.md` remains the durable source of what is required.
The public UI/UX implementation/review gate remains open; repeat desktop/mobile/
accessibility review must assess the actually updated interface.

The recovered Refund Policy remains agreed commercial content, but is no longer
final publication-ready legal wording. R49–R54 require a new owner-approved
publication revision and resolution of refund-consent/legal applicability before
paid sales. No legal compliance conclusion is claimed. Conditional consent,
service/product/bundle separation and any online withdrawal path remain subject
to the decisions in the requirements and release gates. R54 records accepted
post-refund stop-use/delete-copies policy direction subject to law/licence and
review; R55 explicitly defers activation/DRM from the first release.

The owner-reported clean review environment uses `smartbudget_review` and
`.env.review.local` (see `operations.md`). It contains the two intended Standard
SKUs, `smartbudget-ru-standard` at 2,990 RUB and `smartbudget-int-standard` at
49 EUR. RU and EN `ProductRelease` 1.0 archives were successfully uploaded and
published through the existing Admin/R2 workflow under the isolated
`product-releases-review-20261026` prefix. Review consultation offers are RU
`addon` 3,900 RUB / `standalone` 5,900 RUB and EN `addon` 69 EUR / `standalone`
99 EUR; bundle checkout totals were verified as 6,890 RUB and 118 EUR.
Those earlier R2 uploads/publications remain integration evidence for upload,
private storage and publication; they do not establish that the currently
uploaded archive bytes are the rebuilt customer release artifacts.

Four defects discovered during this review are corrected with focused
regression coverage: default reviews navigation selects the resolved UI
language's exact SKU and uses a valid family back link; buy-page language
persists into checkout through the shared rendering contract; checkout reserves
strong emphasis for Total; and Product Releases Admin displays Moscow-local
release timestamps without changing stored UTC values. These corrections do
not close the overall UI/UX gate or establish production validation.

The temporary HTTPS endpoint `https://smartbudget-review.neocitrix.com` is now
externally reachable and perimeter-validated: approved public GET review routes
work, while privileged, API, capability, and POST surfaces are blocked at the
Cloudflare edge. Operational details and validation evidence are in the
temporary review environment section of `operations.md`. The overall public
UI/UX review gate remains open; this is neither production deployment nor
production security validation.

### 3. Production deployment and live validation after prior gates

Only after those gates should SmartBudgetSite proceed to production deployment,
public DNS and HTTPS, then resume the still-open Expected Release Gaps and live
validation in `release_readiness.md`. This sequencing defers those obligations;
it does not close or abandon them.

### Post-release priority: Consultation Capacity & Refund Operations

This initiative is deferred until after the first public commercial release and
is not a current release blocker. It is deliberately the first planned
post-release SmartBudgetSite enhancement, with this sequence:

`Public release -> short production stabilization -> Consultation Capacity &
Refund Operations -> SmartBudgetSite becomes maintenance-first -> primary
development focus returns to SmartBudget Excel`.

The objective is to make refunds, criticism/support handling, and consultation
workload operationally predictable before development focus returns to Excel.

Current provider research, confirmed directly by Lava.top support: refund API
initiation is unavailable; only one refund is possible per provider transaction;
Lava.top processes its side immediately, while bank/card settlement may take up
to 10 business days. Authoritative machine-readable refund
verification/reconciliation remains pending a provider-support response.

Detailed deferred rules and unresolved decisions belong in
[refund architecture](architecture/commerce_and_delivery.md#deferred-customer-refund-requests-and-item-targeted-refunds),
[consultation capacity](architecture/consultations.md#deferred-operational-capacity),
and [assisted refund operations](operations.md#deferred-assisted-refund-operations).

### Later application work: Smart Feedback support flow

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

### Ongoing release-readiness validation

Continue manually validating complete end-to-end user journeys as major
functionality is completed.

Each discovered issue should be evaluated for:

- browser regression coverage;
- backend regression coverage;
- documentation improvements;
- user experience improvements.

Treat release readiness as an incremental activity rather than a final project
phase.

## Release UI/UX implementation mapping

**Completed and accepted:** static repository analysis of R01–R55 against
`cd5190b3ed0ee109e5f4983842c89a70571f0219` (`docs: freeze pre-release UI UX
requirements`), closed out on 2026-11-04. The independently reviewed statuses
formed the accepted implementation-state snapshot. The table now includes the
G1 and scoped Landing updates recorded below; it is not a new requirements register or release backlog. Requirements/copy remain owned by
`release_uiux_requirements.md`; release gates remain owned by
`release_readiness.md`.

The original analysis inspected repository code, templates, translations, CSS/JS,
models, services, repositories, tests, migrations and existing images. It read
tests without running them and performed no runtime/browser/provider validation,
database inspection or release operation. Subsequent G1 checks are recorded below. Workbook/Walkthrough/ZIP completion is owner-reported;
repository evidence does not independently verify the workbook's VBA or current
review R2 bytes. No architecture/business/legal decision was resolved.

Statuses distinguish existing behavior (`Implemented`), incomplete behavior
(`Partial`), missing approved implementation (`Required`), runtime/provider proof
(`Requires validation`), unresolved approval (`Requires decision`), and work
outside first release (`Deferred`). None was established as `Not applicable`.
D1–D6 below are dependencies, not decisions made by this mapping.

| ID | Current status | Current state / remaining gap | Decision or validation dependency |
| --- | --- | --- | --- |
| R01 | Implemented | Shared RU/EN segments expose the active language as a non-link current state; inactive link supports keyboard/focus. | G1 focused/browser validation complete |
| R02 | Implemented | Shared query-relative switch replaces only lang and retains path, exact product/currency and add-on state. Unsent email is intentionally not persisted. | Both directions, editions/currencies and absent/off/on add-on tested |
| R03 | Partial | G1 active About/Products semantics, locale continuity and booking-success cookie persistence are implemented; only the future Consultations entry remains outside G1. | R06/G12; G1 accepted end state complete |
| R04 | Requires decision | Footer exposes personal Telegram, WhatsApp, Facebook, VK, LinkedIn and email. Recovered removal conflicts with unresolved UX-001 treatment, including possible informational LinkedIn retention. | D2; do not choose silently |
| R05 | Implemented | Obsolete Landing consultation heading, text and Telegram CTA are completely removed in RU/EN; no replacement consultation block. | G2A complete; R04/footer remains untouched |
| R06 | Requires decision | Consultation catalog/standalone identity, service SaleItem and entitlement support exist; public consultation purchase/provider orchestration do not. | D3; G11 then G12 |
| R07 | Partial | Approved first five sections and on-page Hero CTA are implemented; the full seven-block requirement still awaits G9 practical/commercial sections. | G7/G8 accepted scope complete; G9/D1 remains separate |
| R08 | Requires decision | Hero is price-free and purchase reaches Buy; concluding priced offer is absent. | D1; G9 |
| R09 | Implemented | Landing uses a shared screenshot macro, consistent semantic sections, localized copy keys and locale-specific asset paths; maintenance convention recorded below. | G7 foundation complete; future G9 content remains separate |
| R10 | Partial | Obsolete large consultation block removed under G2A; no new consultation marketing or optional add-on wording was introduced. | Remaining purchase-side mention belongs to G9 |
| R11 | Implemented | All ten owner-supplied final assets are used by locale without byte changes; linked originals, meaningful localized alt text and keyboard-pannable viewports are implemented. | Scoped G7/G8 browser checks complete; independent release/workbook validation and R45 remain open |
| R12 | Implemented | First five Landing sections use text-led hierarchy, wide readable demonstrations and a responsive reconciliation pair instead of uniform feature cards. | Scoped G7/G8 desktop/mobile checks complete; repeat R45 review remains open |
| R13 | Implemented | Approved future-expense copy/caption and exact supplied warning screenshot render in RU/EN. | Supplied numerical data unchanged; G8 browser checks complete |
| R14 | Implemented | Approved preserved-PLAN/updated-ACTUAL explanation and exact supplied transition image render in RU/EN. | Supplied example unchanged; G8 browser checks complete |
| R15 | Implemented | Approved reconciliation explanation/caption and labelled before/after supplied screenshots render as a responsive pair. | Supplied example unchanged; G8 browser checks complete |
| R16 | Partial | Local Excel/no-subscription note exists; four practical benefits, guide, indefinite-use wording and compatibility disclosure are incomplete. | G6/G9; no unapproved update/support promises |
| R17 | Partial | Photograph and three activity areas exist; approved biography/training/story, ACCA/FCCA distinction and left alignment are missing. | Approved copy and responsive verification; G5 |
| R18 | Partial | Price-free product card links to Landing; six old highlights/CTA remain instead of three approved outcomes and Windows note. | None; G5 |
| R19 | Partial | Card exists with extra section/container framing and prominent shadow; visual simplification remains. | Rendered verification; G5 |
| R20 | Partial | Priced Buy options/add-ons exist; Package RU/INT and locale-dependent Recommended badge remain. | Preserve catalog/payment routing; G10 |
| R21 | Partial | Setup add-on selection and database amount exist; 60-minute/online/booking-after-payment explanation is missing. | Named platform needs validation; neutral copy can proceed; G10 |
| R22 | Partial | Selected items, Total emphasis and email/payment form exist; Your order heading, language terminology and remaining hierarchy polish are missing. | None; G10 |
| R23 | Required | Checkout email hint lacks approved protected-download and conditional booking explanation; standalone variant is absent. | G10 product copy; D3/G12 for standalone |
| R24 | Partial | Attachment/drop behavior and form width exist; Feedback's loaded CSS does not supply its primary button treatment and file-picker styling is incomplete. | Preserve limits, keyboard and native file access; G3 |
| R25 | Partial | Localized live success/error and optional private-enquiry email exist; approved post-submit guidance/success copy are incomplete. | Editorial success wording; G3 |
| R26 | Partial | Paid product ownership verification and pre-purchase General question work; customers-only review category label is missing. | Preserve verified-purchase boundary; G3 |
| R27 | Required | First topic and JS reset select `site_issue`; required empty initial topic is absent. | Preserve intentional support preselection; G3 |
| R28 | Required | Landing review link is unconditional; product detail does not load publication counts. | Exact-SKU 0/1+ publication behavior; G4 |
| R29 | Partial | Direct localized empty review page/family back link exist; repeated intro/heading/body need the approved single neutral message. | None; G4 |
| R30 | Partial | Five native accordion questions exist; five approved groups, full question set and localized page titles are absent. | G6 structure; conditional content follows G12/G14/G15 |
| R31 | Partial | FAQ uses older product/irregular-income answers; approved four-question overview and expanded audience answer are absent. | None; G6 |
| R32 | Required | Generic Excel/macro wording omits the cross-surface Windows/Excel/VBA/ActiveX standard and unsupported/corporate restrictions. | R47 editorial/device limits; G6 |
| R33 | Required | Purchase/delivery FAQ group is absent; configured default download lifetime is 12 hours. | G14; D6 blocks only affected update/commercial wording |
| R34 | Partial | Buy/Checkout use ProductPrice/ServiceAddon dynamically; Landing/FAQ have no price context and public Consultations is absent. Actual DB amounts were not checked. | D1 Landing; D3 standalone; dynamic sourcing on all applicable surfaces |
| R35 | Required | `purchase_email_renderer.py` supplies product links without the RU/EN 12-hour notice. | D5 durable email language; actual entitlement expiry; G13 |
| R36 | Partial | Download expiry has date/minute and Moscow conversion; visible timezone label is missing. | Keep stored UTC/conversion semantics; G14 |
| R37 | Partial | Download errors retain support reference/Feedback prefill; indefinite-use expiry explanation and real interrupted/repeat-download proof are missing. | Editorial expired-page copy and validation; G14 |
| R38 | Requires decision | Add-on/standalone catalog/Admin and service-only Sale helper exist; public checkout/provider mapping remain product-bound. | D3, then G11/G12; platform validation |
| R39 | Requires validation | Booking/token/webhook lifecycle exists; tests pre-link provider event URI and do not establish first-booking end-to-end behavior. | Real integration evidence first; no speculative architecture change |
| R40 | Partial | Item-specific email links and durable retries exist; renderer is English-only and omits approved 60-minute/14-day/next-step content. | D5, editorial subjects, Calendly confirmation validation; G13 |
| R41 | Requires decision | Policy is preserved in requirements; public policy page/pre-payment links are absent and recovered wording is not publication-final. | D4/new approved revision; G15 |
| R42 | Requires decision | Founder `start_full_refund`/`confirm_full_refund` snapshot the full Sale; partial/item refunds and customer confirmation are unsupported. | D4 and later operational validation; not automatically G15 implementation |
| R43 | Requires decision | Seller block is preserved but not published; legal sufficiency remains open. | D4; do not publish home address without explicit owner reconsideration; G15 |
| R44 | Partial | Support and founder refund operations exist; public 2/5/10-day distinctions and operational readiness are incomplete. | Policy approval and support-capacity validation; G15 |
| R45 | Requires validation | Gate 3 remains open; prior audit/browser tests do not establish repeat review of the updated interface. | Applicable implementation complete, then desktop/mobile/accessibility review |
| R46 | Implemented | Active R01–R55 source, documentation map and versioned supporting advisory are preserved by the documentation freeze. | None |
| R47 | Partial | Owner reports workbook/Walkthrough ActiveX changes complete with Excel 2021 evidence; website guidance and complete Microsoft 365 validation remain open. | Editorial approval and device validation; G6; VBA not independently verified |
| R48 | Requires validation | Rebuilt RU/EN ZIPs are owner-complete; review ProductRelease 1.0 bytes remain stale; immutable release/upload/publication mechanisms exist. | Reference inspection, safe replacement and hash/size/R2/active-current verification; operations only |
| R49 | Partial | No universal waiver is present; clear checkout delivery disclosure and Refund Policy access are missing. | G10/G15; D4 for policy publication, no automatic consent checkbox |
| R50 | Requires decision | No immediate-supply consent mechanism exists; applicability, supply start, no-consent path and durable evidence/confirmation are unresolved. | D4; scope implementation only if applicable |
| R51 | Requires decision | Separate product/service items/access exist, but refunds are full-Sale and public service-only checkout is absent. | D3/D4; composition-specific legal wording; G12/G15 |
| R52 | Requires decision | Policy publication/legal gate is explicitly open; a new owner-approved revision aligned with actual behavior is missing. | D4; G15 |
| R53 | Requires decision | No dedicated withdrawal path exists; ordinary support/Feedback do not establish applicability or sufficiency. | D4; bounded flow only if applicable, otherwise rationale for Not applicable |
| R54 | Requires decision | Stop-use/delete-copies direction is accepted; backend refund revokes access, not downloaded files; publication wording is not legally final. | D4/R52; law/licence/statutory safeguards; G15 |
| R55 | Deferred | Preventive activation/DRM/server-contact controls are explicitly outside first release; no corresponding site mechanism was found. | No first-release group or technical-debt obligation |

### G1 implementation and validation

Implemented on 2026-11-04 against `df8ab87`. `app/web/navigation.py` supplies shared
navigation state and server-generated query-relative language links to normal
and rate-limit templates. Links preserve repeated/blank non-language query
values without repeating capability paths or trusting Host for link destinations.
Feedback switch links retain only already-resolved support references; rejected
references remain absent. This is navigation compatibility, not a Feedback feature.

`base.html` renders a non-link current language, keyboard-reachable alternate
language and `aria-current` primary section. Shared CSS adds underline/current
and focus states; its URL is versioned for cached-asset compatibility. About is
active on `/`; Products on product/detail/Buy/Checkout pages; unrelated public
pages have neither section active. The booking success route now uses `render()`
without changing consultation validation or lifecycle. Existing query/cookie/
default locale precedence and cookie lifetime/security settings are unchanged.

Validation through `.venv/Scripts/python.exe -m pytest`, each with external
`--basetemp` under `C:\Users\Admin\AppData\Local\SmartBudgetSite\pytest-temp`
and external `cache_dir` under the same project's `pytest-cache` directory:

- Focused public navigation, document language, booking and Feedback-prefill
  regression files: **57 passed** (`g1-language-navigation`).
- `tests/web`, `tests/test_rate_limiting.py` and
  `tests/test_capability_protection.py`: **215 passed** (`g1-language-navigation-web`).
- `browser_tests/test_checkout_polish.py -m browser`: **4 passed** at 1280/375 px
  in RU/EN (`g1-language-navigation-browser`). Keyboard switching, current-segment
  inertness, exact order composition, no email storage/URL transport, ordinary
  reload and no horizontal overflow were checked; generated desktop/mobile
  screenshots were visually inspected. Two dependency deprecation warnings remain.
- Changed-Python-file Ruff passes. Black checks pass for the other five changed
  Python files; `i18n.py` has the same pre-existing Black failure at HEAD and was
  not reformatted beyond adding G1 accessibility labels. `git diff --check` passes.

The first sandboxed pytest attempt could not create the required external temp
directory; the successful runs used authorized access to those locations. The
initial broader run exposed rejected support references in switch links; this
was corrected before the passing run above. The full suite, live providers,
real customer journeys and assistive-technology review were not run. G1 does not
close the overall UI/UX gate or implement any R04+ functionality.

### G2A / G7 / G8 Landing implementation and validation

Implemented against `7034dcb`. The scoped Landing now presents Hero → three levels
of financial resilience → future-expense consequences → PLAN/ACTUAL → balance
reconciliation. Sections 5.1.1–5.1.5 copy/captions are retained verbatim in both
locales; only new image alt/link labels and before/after labels were authored.
The Hero CTA targets `#sb-capabilities`. The old Telegram consultation block is
absent. Existing FAQ/review links and the temporary Buy tail remain; no footer
contact change, price, compatibility/practical block, new commercial offer,
consultation destination/marketing or checkout behavior was introduced.

Maintenance: `app/templates/sm_landing.html` uses the local `screenshot` macro for
figure/link/accessibility presentation. Section copy stays in `app/core/i18n.py`
under the Hero/reserves/future/transition/reconciliation keys; image stems map to
`app/static/img/smartbudget/landing/<lang>/g8_*_<lang>.png`. The supplied ten PNGs
are used unchanged (SHA-256 checked before/after); legacy images are retained.
Replace imagery/copy through these explicit section inputs, not a CMS or new
backend model. Landing-only CSS is versioned as `sm_landing.css?v=3`.

Key image crops pan inside keyboard-focusable regions on narrow screens rather
than shrinking spreadsheet text; original-image anchors open the exact PNG in a
new tab. Reconciliation is labelled before/after and stacks on mobile.

Validation through the configured `.venv` interpreter with required external
pytest temp/cache paths:

- Landing, existing reviews and public navigation web regressions: **57 passed**
  (`landing-g2a-g7-g8`). Approved copy, locale asset paths, image bytes/original
  links, reconciliation pair, removed block and working temporary Buy tail checked.
- Landing plus existing checkout/navigation Chromium cases: **8 passed** at
  1280/375 px in RU/EN (`landing-g2a-g7-g8-browser`). After improving the mobile
  original-link label, the **4 Landing cases passed again**
  (`landing-g2a-g7-g8-browser-final`). Keyboard panning, on-page CTA, opening an
  original, image loading, ordinary reload and no document horizontal overflow
  checked. Generated desktop/mobile screenshots were visually inspected.
- Focused Ruff and test-file Black checks and `git diff --check` pass. The existing
  `i18n.py` whole-file Black baseline remains outside this bounded change.

No full suite, live-provider/customer journey, screen-reader audit or independent
verification of workbook financial calculations was performed. Assets were
supplied as final by the owner, not regenerated. Final owner/editorial and repeat
R45 UI/UX review remain open. G7/G8 completion is scoped to the first five blocks;
G9 and D1 remain unchanged and decision-dependent. No commit or push was made.

### Decision dependencies

These accepted unresolved dependencies block only affected work. They do not
change architecture, approve implementation or require unrelated UI tasks to
wait for every decision.

| Gate | Unresolved decision | Affected work |
| --- | --- | --- |
| D1 — Landing prices | Reconcile the concluding priced offer with architecture assigning price/package selection to Buy; define exact SKU/currency if approved. | R08 and Landing/R34 portion of G9 only |
| D2 — Public contact boundary | Approve final footer/contact/profile links under UX-001, including LinkedIn treatment, ownership and configuration. | R04/G2B only; does not block R05/G2A |
| D3 — Standalone consultation checkout | Define provider-offer identity/resolution and server-owned initiation for service-only Sales; existing catalog/SaleItem/entitlement helpers do not provide public checkout. | G11 and dependent standalone purchase in G12 |
| D4 — Refund / supply / policy publication | Resolve partial/item refunds, the one-provider-refund-per-transaction constraint, later requests and unaffected rights; digital supply start, immediate-supply consent applicability, no-consent path, evidence/durable confirmation, product/service/bundle treatment, online withdrawal applicability, seller-information sufficiency and final owner-approved policy/public wording. | Affected refund/policy/consent work; G15; R42 remains separate; R50/R53 only if applicable |
| D5 — Purchase-email language | Decide and persist the durable language source for asynchronous delivery and retries; do not infer a prior browser locale during webhook processing. | Full RU/EN R35/R40 implementation in G13 |
| D6 — Updates/support terms | Resolve 1.0 fixes, minor updates, future major releases, possible upgrade discounts, ordinary support and paid-consultation boundaries. Accepted indefinite use does not settle these terms. | Only dependent commercial/update wording, including the affected R33 answer |

Current refunds remain founder-operated full-Sale operations. Recovered
item/partial/mixed-order promises must not be published as supported behavior:
zero or one RefundOperation per Sale and paid-Sale capability checks do not
preserve unaffected access after a whole-Sale refund. Supporting research is not
an implementation decision or legal compliance conclusion. No new consent,
withdrawal, partial-refund or jurisdiction-selection architecture is selected.

### Accepted implementation groups

This is the accepted execution grouping for the mapped state, not a second
backlog or authorization to implement every group. Each sprint still needs a
separate bounded end state and verification commands. Shared R-IDs denote
surface-specific slices, not duplicate requirements.

| Group | R-IDs | Scope and dependencies |
| --- | --- | --- |
| G1 — Language/navigation | R01–R03 | **Accepted G1 scope implemented and validated**; future Consultations navigation remains with R06/G12. |
| G2A — Remove obsolete Telegram Landing block | R05 | **Implemented and validated**; complete heading/text/CTA removal, independently of D2; footer untouched. |
| G2B — Final public contact boundary | R04 | Final footer/contact links; blocked by D2. |
| G3 — Feedback polish | R24–R27 | Form styling, guidance, review label and empty initial topic; preserve verification, attachments and support prefill. |
| G4 — Reviews visibility | R28–R29 | SKU-scoped published-review visibility and concise empty state. |
| G5 — About / Products | R17–R19 | Approved biography/product presentation and simpler framing. |
| G6 — Compatibility / FAQ foundation | R30–R32, R47 | FAQ structure/overview and consistent compatibility/ActiveX guidance; retain editorial and device-validation limits. |
| G7 — Landing foundation | R07, R09, R11–R12 | **Accepted first-five-block scope implemented and validated**; approved Hero/reserves, shared image macro and supplied assets; G9 separate. |
| G8 — Landing demonstrations | R11, R13–R15 | **Implemented and validated** with exact supplied future-expense, PLAN/ACTUAL and reconciliation images/copy; R45 review remains open. |
| G9 — Practical/commercial Landing | R08, R10, R16, Landing portion of R34 | Practical benefits and concluding offer; partly blocked by D1 and standalone-destination dependencies, not every stable block. |
| G10 — Product Buy / Checkout | R20–R23, applicable R34/R49 | Equal language cards, add-on/order/delivery presentation; preserve server-authoritative commerce; final policy links follow G15. |
| G11 — Standalone payment boundary | R06, R38 | Service-only provider initiation; blocked by D3. |
| G12 — Public Consultations | R06, R23, R34, R38, applicable R51 | Public page/navigation/checkout; depends on approved G11 architecture, platform evidence and applicable policy wording. |
| G13 — Purchase email | R35, R40 | Localized composition-specific delivery copy; full localization blocked by D5. |
| G14 — Delivery presentation / FAQ | R33, R36–R37 | Delivery FAQ, explicit timezone and expired-link guidance; D6 blocks only genuinely dependent commercial/update wording. |
| G15 — Policy publication | R41, R43–R44, R49, R51–R52, R54 | Publish newly approved policy/seller information and synchronized summaries; blocked by D4. |

R42 remains a separate decision-dependent refund capability/operational topic;
do not fold it into G15 implementation automatically. R50 and R53 receive
implementation scopes only if D4 establishes applicability. R39, R45 and R48
remain validation/operational work; R46 is complete; R55 remains deferred.

G1, G2A and the accepted G7/G8 scope are implemented. Further bounded tasks must
be explicitly scoped from the accepted groups; independent work need not wait
for unrelated decisions. G9 was not implemented. G7–G9 split Landing work; G11 precedes G12. Complete required material
replacement before treating review artifacts as current, repeat review against
the updated interface, then follow the later deployment/live-validation gates.

### Validation-only and operational dependencies

Keep these separate from implementation; their existence does not authorize
speculative code changes or provider operations:

- Microsoft 365 ActiveX startup/blocked-state validation; Excel 2021 evidence is
  owner-supplied and does not establish the complete Microsoft 365 scenario.
- Review ProductRelease 1.0 reference inspection and safe replacement. Stop if
  persistently referenced; preserve version 1.0, immutable identity and isolated
  review prefix. Rebuilt RU/EN archives are ready, but current review bytes are stale.
- Separate RU/EN local/persisted SHA-256 and size, R2 object and active/current
  publication verification; filenames alone are not proof.
- Calendly first-booking, confirmation, reschedule/cancellation and post-window
  end-to-end validation. Existing pre-linked-event tests do not prove this;
  collect integration evidence before deciding whether architecture must change.
- Actual meeting-platform/guest/screen-sharing and fallback validation before
  publishing conditional platform claims.
- Actual purchase-email receipt/content and capability-link validation after
  implementation, plus download expiry/interruption/repeat-download/support flow.
- Later live payment/provider validation under the deployment gates.
- Later refund/provider/customer-communication validation; no partial-refund
  experiment against the current full-Sale implementation before D4.
- Owner confirmation of 2/5-business-day support readiness, distinct from the
  provider-reported bank settlement period.
- Final repeat desktop/mobile/accessibility review of the updated real interface;
  earlier screenshots or browser tests do not close R45.

Concrete validation findings may justify later bounded implementation tasks.
None of this validation or operational work was performed by the analysis or
its documentation closeout. SmartBudgetSite is not declared release-ready.

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
