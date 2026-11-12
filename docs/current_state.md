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
- The existing Vultr VPS in Amsterdam remains dedicated to VPN
  connectivity and is separate from the SmartBudgetSite production host.
- On 2026-11-12, a dedicated SmartBudgetSite production VPS was
  provisioned on Vultr in Amsterdam (Ubuntu 24.04 LTS, 2 vCPU,
  4 GB RAM, 80 GB SSD). Initial cloud-init checks, SSH key
  authentication, administrative sudo access, SSH hardening, and
  restricted Vultr Firewall access were verified. Automatic instance
  backups are enabled, but recovery has not been tested.
  Ubuntu security and system updates were installed on 2026-11-12.
  Kernel 6.8.0-149-generic is running after a verified reboot.
  SSH access and package dependency checks succeeded.
  Three Ubuntu phased updates remain deferred.
  Docker, application deployment, PostgreSQL, public HTTPS,
  monitoring, and production integration validation have not been
  completed. Deployment remains deferred under the approved
  pre-deployment release gates. See `operations.md` for details.
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
separate execution work. D6 settles the update and support terms. Align the
EULA/licence and customer-facing copy before publication under `REL-001`.

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

### 1. Rebuilt review releases verified

As of the 2026-11-04 owner update, the SmartBudget workbook has been revised for
ActiveX onboarding and blocked-state guidance. The RU Walkthrough and EN
Walkthrough have each been revised, and both RU and EN customer ZIP archives
have been rebuilt. These content/rebuild steps are owner-confirmed complete;
they were not independently inspected in this documentation sprint.

Excel 2021 detection, blocked-state detection, opening Trust Center and required
configuration are owner-verified. New owner evidence also confirms installed
desktop Microsoft 365 for Windows: Excel 2608, Click-to-Run, Current Channel.
Codex did not independently reproduce these external product tests. The final
R47 flow requires the user to change ActiveX settings manually, restart Excel,
then relaunch for a fresh availability check; SmartBudget does not change Office
security automatically. Safe Mode stays enabled; corporate policy may prevent
full functionality. Final RU/EN FAQ guidance now reflects this behavior.
Experimental SendKeys navigation is abandoned and is not public guidance.
32-bit Excel was not separately practically reproduced. This evidence boundary
remains internal; the supported product matrix includes both 32-bit and 64-bit
Excel and does not claim independent reproduction of every supported combination.

**R48 is complete in the dedicated review environment.** On 2026-11-06, final
independent read-only verification passed against `smartbudget_review` and
`product-releases-review-20261026`. Both rebuilt archives are published as
version **1.0**, with exactly one release and one active release per SKU.

| SKU | Product / ProductRelease ID | Archive | Size (bytes) | SHA-256 |
| --- | --- | --- | ---: | --- |
| `smartbudget-ru-standard` | 2 / 3 | `SmartBudget_v1.0_RU.zip` | 7,787,741 | `f51c7caccb66361bedf30e2954ce6695afd70d3e0a3b40407e11ee250e456bbf` |
| `smartbudget-int-standard` | 1 / 4 | `SmartBudget_v1.0_EN.zip` | 7,519,274 | `04a73ae37b3a002be7982b292f4cd58e3f9707ae9f62366f6a7095573ac41a45` |

For each language, local rebuilt ZIP size and SHA-256 matched persisted
`ProductRelease` metadata, R2 HEAD metadata, and downloaded R2 bytes. After
independent verification of zero `ProductRelease` references, the owner
confirmed manual removal of both old review objects through the Cloudflare R2
Dashboard without using `--delete-orphans`.
See [Gate 2 closeout](release_readiness.md#gate-2--review-productrelease-artifact-replacement)
for the reset and publication evidence.

A separate Product Description remains intentionally excluded: the bilingual
Walkthrough is the accepted detailed customer guide. Gate 3 remains open for
UI/UX implementation and repeat review.

### 2. G1, G2A, G5 presentation and scoped Landing G7/G8 implemented

The R01–R55 mapping was completed against local HEAD `cd5190b` and independently
reviewed and accepted. The [implementation-state snapshot below](#release-uiux-implementation-mapping)
records accepted statuses, decision outcomes, implementation groups and
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
removed. **G9 is implemented and locally validated** under approved D1. The
practical conditions and compatibility disclosure precede the concluding offer,
which links to Buy and contains the short optional consultation add-on note.
The Hero remains price-free. Landing reads the active catalog price and currency
for the exact locale SKU and omits the price when no single usable active price
can be established. Focused web and RU/EN Chromium checks covered the seven-block
Landing, price changes, compatibility disclosure, Buy navigation, language
switching and desktop/mobile fit using isolated catalog data.
G12 adds the Consultations entry and completes the public navigation portion of
R03.

**G2B/R04 is implemented and locally validated** under approved D2. The shared
public footer links to FAQ, Feedback and `mailto:support@neocitrix.com`.
The personal contact links were removed, and a repository search found no other
public rendering of those destinations. RU/EN web tests verified the footer
links, and Chromium verified footer navigation, locale persistence and fit at
1280 px and 375 px. UX-001 release-environment validation remains open.

**G5 About/Products presentation is implemented and validated** against
`9aec0b7`. R17 and R19 are implemented; R18 has the approved catalog content and
Windows conditions line. G6 now completes R18 with a localized link to the actual
FAQ compatibility section; G5 About/Products presentation is preserved.

`release_uiux_requirements.md` remains the durable source of what is required.
The public UI/UX implementation/review gate remains open; repeat desktop/mobile/
accessibility review must assess the actually updated interface.

D4 settles the refund, consent, request and seller-information model. The
recovered Refund Policy remains source material for a new owner-approved
publication revision. Actual refund operations, checkout, FAQ and purchase
email must match the revised policy before paid sales. R42 item-level refund
capability, R50 applicable consent and R53 request intake still need bounded
implementation. R55 keeps activation and DRM outside the first release.
These are owner-approved product and architecture decisions.

The owner-reported clean review environment uses `smartbudget_review` and
`.env.review.local` (see `operations.md`). It contains the two intended Standard
SKUs, `smartbudget-ru-standard` at 2,990 RUB and `smartbudget-int-standard` at
49 EUR. RU and EN `ProductRelease` 1.0 archives were successfully uploaded and
published through the existing Admin/R2 workflow under the isolated
`product-releases-review-20261026` prefix. Review consultation offers are RU
`addon` 3,900 RUB / `standalone` 5,900 RUB and EN `addon` 69 EUR / `standalone`
99 EUR; bundle checkout totals were verified as 6,890 RUB and 118 EUR.
The current rebuilt review archives are the verified R48 releases recorded
above.

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

### Pre-release operational readiness

G13D Purchase Delivery Monitoring is the next implementation priority. Follow
it with bounded refund operations and consultation capacity work. These
capabilities must be ready before the first public commercial release. After
launch, SmartBudgetSite moves to maintenance and the primary development focus
returns to SmartBudget Excel.

Operational readiness means minimizing routine manual administration, alerting
the operator in time to act, providing safe recovery procedures, and reliably
meeting customer obligations. Use the approved
[R42 and R53 refund and request rules](architecture/commerce_and_delivery.md#approved-refund-rules-and-customer-requests-d4),
the [operator workflow](operations.md#pre-release-refund-operations), and the
[consultation capacity boundary](architecture/consultations.md#operational-capacity).
Lava.top refund initiation requires manual provider action. Routine preparation,
tracking and follow-up can be supported within the approved workflow.

Keep optional enhancements outside the release gate unless they address a
demonstrated release-critical gap.

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
database inspection, release operation, or architecture/business/legal decision.
Later implementation and validation evidence is recorded separately.
Workbook and Walkthrough completion is
owner-reported. The independent R48 archive checks above establish review
artifact integrity.

Statuses distinguish existing behavior (`Implemented`), incomplete behavior
(`Partial`), missing approved implementation (`Required`), pending runtime or
provider proof (`Requires validation`), completed operational verification
(`Validated`), unresolved approval (`Requires decision`), and work outside
first release (`Deferred`). None was established as `Not applicable`.
The owner-approved D1–D6 outcomes below guide the remaining work.

| ID | Current status | Current state / remaining gap | Decision or validation dependency |
| --- | --- | --- | --- |
| R01 | Implemented | Shared RU/EN segments expose the active language as a non-link current state; inactive link supports keyboard/focus. | G1 focused/browser validation complete |
| R02 | Implemented | Shared query-relative switch replaces only lang and retains path, exact product/currency and add-on state. Unsent email is intentionally not persisted. | Both directions, editions/currencies and absent/off/on add-on tested |
| R03 | Implemented | About, Products and Consultations use the shared active-state navigation. Locale continuity and the segmented switch are locally validated. | Final R45 review remains open |
| R04 | Implemented | The shared RU/EN footer has FAQ, Feedback and the official support email. Personal contact links are removed. | G2B locally validated. UX-001 release-environment validation remains open |
| R05 | Implemented | Obsolete Landing consultation heading, text and Telegram CTA are completely removed in RU/EN; no replacement consultation block. | G2A complete |
| R06 | Implemented | G12 adds public Consultations navigation, catalog and standalone Checkout on the G11 payment boundary. | Real payment and booking validation remain open |
| R07 | Implemented | All seven Landing sections render in the approved RU/EN order. The Hero CTA opens the on-page demonstrations. | G7–G9 locally validated |
| R08 | Implemented | Hero is price-free. The concluding offer displays the exact locale SKU's usable active catalog price and currency and links to Buy. | G9 locally validated with isolated catalog data |
| R09 | Implemented | Landing uses a shared screenshot macro, consistent semantic sections, localized copy keys and locale-specific asset paths; maintenance convention recorded below. | G7 foundation complete |
| R10 | Implemented | The obsolete consultation block is gone. The concluding offer contains only the approved optional add-on note. | G9 locally validated |
| R11 | Implemented | All ten owner-supplied final assets are used by locale without byte changes; linked originals, meaningful localized alt text and keyboard-pannable viewports are implemented. | Scoped G7/G8 browser checks complete; independent release/workbook validation and R45 remain open |
| R12 | Implemented | First five Landing sections use text-led hierarchy, wide readable demonstrations and a responsive reconciliation pair instead of uniform feature cards. | Scoped G7/G8 desktop/mobile checks complete; repeat R45 review remains open |
| R13 | Implemented | Approved future-expense copy/caption and exact supplied warning screenshot render in RU/EN. | Supplied numerical data unchanged; G8 browser checks complete |
| R14 | Implemented | Approved preserved-PLAN/updated-ACTUAL explanation and exact supplied transition image render in RU/EN. | Supplied example unchanged; G8 browser checks complete |
| R15 | Implemented | Approved reconciliation explanation/caption and labelled before/after supplied screenshots render as a responsive pair. | Supplied example unchanged; G8 browser checks complete |
| R16 | Implemented | Landing renders the four approved practical benefits and the visible compatibility disclosure. | G9 locally validated |
| R17 | Implemented | Complete approved 5.2 RU/EN intro, SmartBudget origin, three activity areas and approach; exact ACCA/FCCA and two-year GeekBrains wording. Existing photo capped at 320 px; left-aligned narrative replaces old bullets/cards. | G5 focused web/browser and render checks complete; final R45 review remains open |
| R18 | Implemented | Approved catalog content and restrained G5 card retained; localized Full System Requirements link now targets `/faq#system-requirements`. | G6 link/anchor validated in RU/EN desktop/mobile; no price or Buy CTA |
| R19 | Implemented | Products uses one restrained bordered card without nested gradient framing or oversized shadow; CTA is a navigation link. | G5 RU/EN desktop/mobile browser and render checks complete; final R45 review remains open |
| R20 | Implemented | Buy uses equal cards with localized product-language labels, the same-features explanation and catalog-owned prices. | G10 locally validated |
| R21 | Implemented | Buy describes the optional 60-minute online setup session and booking instructions after payment. The add-on price and availability come from the catalog. | G10 locally validated. Booking platform validation remains separate |
| R22 | Implemented | Checkout shows the selected product, language and item prices under Your order, emphasizes Total, and preserves email and hosted payment initiation. | G10 locally validated |
| R23 | Partial | Product Checkout explains download delivery and bundle booking. Standalone Checkout explains only booking instructions and the protected booking link. | Release-environment delivery validation remains open |
| R24 | Implemented | Full-width primary submit and contained native file picker with visible focus. | Attachment types, limits and retry retention preserved |
| R25 | Implemented | Approved RU/EN post-submit guidance and prominent localized confirmation with message ID. | Existing status and alert announcements retained |
| R26 | Implemented | Customers-only review label and pre-purchase General question available. | Verified purchase remains required for reviews, with optional email for general enquiries |
| R27 | Implemented | Fresh form and successful reset select the required empty topic. | Download-support preselection and prefill retained |
| R28 | Implemented | Landing shows Reviews when the exact public-language SKU has published product feedback. | Shares SKU routing with /reviews and publication filters with the public list |
| R29 | Implemented | Direct Reviews pages for existing products show one approved RU/EN empty message and a link back to SmartBudget. | Unknown product slugs return 404 |
| R30 | Partial | Localized title and data-driven grouped native accordions implemented; only ready About SmartBudget (4) and Before You Buy (7) groups render, with no empty placeholders. | Remaining FAQ groups belong to G12/G14/G15 |
| R31 | Implemented | Exact approved 5.6.1 RU/EN four-question overview, including final expanded audience answer, replaces legacy FAQ. | G6 focused web/browser validation complete |
| R32 | Implemented | Landing, Buy and Checkout display the compatibility disclosure. Products, Buy and Checkout link to the FAQ requirements, which include Microsoft links and manual/restart guidance. | Pre-purchase presentation locally validated |
| R33 | Required | The approved purchase/delivery FAQ copy specifies 24 hours after payment confirmation. | Publish the purchase/delivery FAQ under G14 |
| R34 | Partial | Landing, Buy, Checkout and Consultations use catalog prices. Consultations shows matching add-on pricing for information. | Remaining applicable FAQ disclosures and release-environment catalog validation |
| R35 | Implemented | New download entitlements default to 24 hours. RU/EN product and bundle emails show the 24-hour notice. Delivery blocks known-expired download links. | Verify the release configuration and validate delivery in the release environment |
| R36 | Partial | Download expiry has date/minute and Moscow conversion; visible timezone label is missing. | Keep stored UTC/conversion semantics; G14 |
| R37 | Partial | Download errors retain support reference/Feedback prefill; indefinite-use expiry explanation and real interrupted/repeat-download proof are missing. | Editorial expired-page copy and validation; G14 |
| R38 | Partial | G12 presents standalone and add-on options distinctly with catalog prices and neutral online format wording. | Real booking and meeting platform validation remain open |
| R39 | Requires validation | Booking/token/webhook lifecycle exists; tests pre-link provider event URI and do not establish first-booking end-to-end behavior. | Real integration evidence first; no speculative architecture change |
| R40 | Partial | G13 renders the approved subjects and copy for all three order compositions in RU/EN from the stored Sale language. | Real purchase email and Calendly confirmation validation remain open |
| R41 | Required | The recovered policy is preserved. A synchronized public policy page and pre-payment links are absent. | G15 new owner-approved publication revision under D4 |
| R42 | Partial | Founder full-Sale refunds exist. D4 requires pending `Sale.paid_at` persistence for the [voluntary refund clock](architecture/commerce_and_delivery.md#voluntary-smartbudget-refund-eligibility-clock), add-on-only item accounting, handling later required refunds, and customer confirmation. | Separate bounded capability and operational validation. Preserve unaffected product access |
| R43 | Required | Seller information is not published. D4 approves the full geographical address in the policy seller section. | G15 finalize seller details/status and publish identical factual address in RU/EN |
| R44 | Partial | Support and founder refund operations exist. Public 2/5/10-business-day response, review and bank-settlement distinctions are incomplete. | G15 synchronized publication and separate support-capacity validation |
| R45 | Requires validation | Gate 3 remains open; prior audit/browser tests do not establish repeat review of the updated interface. | Applicable implementation complete, then desktop/mobile/accessibility review |
| R46 | Implemented | Active R01–R55 source, documentation map and versioned supporting advisory are preserved by the documentation freeze. | None |
| R47 | Implemented | Owner confirms desktop Microsoft 365 Excel 2608 Click-to-Run Current Channel on Windows; final manual ActiveX setting/restart/recheck flow and corporate-policy boundary are reflected in RU/EN FAQ. | External product evidence is owner-verified, not independently reproduced by Codex; both bitnesses not claimed validated |
| R48 | Validated | Rebuilt RU/EN review releases 3 and 4 are active at version 1.0. Local ZIP, DB, R2 HEAD and downloaded-byte size/SHA-256 checks passed. | Gate 2 complete in review. The owner confirmed targeted cleanup of both old objects |
| R49 | Partial | G10 product Checkout displays composition-sensitive delivery information. The no-universal-waiver boundary remains in force. | G15 synchronized policy disclosure and link under D4 |
| R50 | Required | No immediate-supply consent mechanism exists. D4 approves separate express consent where legally applicable and durable order evidence. | Bounded implementation and applicable supply, no-consent and confirmation validation |
| R51 | Partial | Public product, bundle and standalone checkout use composition-specific delivery and item-owned access. Current refunds remain full-Sale. | R42 capability, applicable early-start consent and G15 composition-specific wording |
| R52 | Required | The recovered policy needs a new owner-approved publication revision synchronized with actual behavior. | G15 publication and validation before paid sales |
| R53 | Required | Dedicated persisted cancellation/refund request and customer confirmation are absent. | Separate bounded D4 implementation with request evidence and operator-controlled money movement |
| R54 | Required | Full refunds revoke future protected access. Downloaded local copies remain under customer control. | G15 stop-use/delete wording subject to law and licence. R55 excludes DRM |
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
R45 UI/UX review remain open. G7/G8 completion is scoped to the first five blocks.

### G5 About / Products implementation and validation

Implemented against `9aec0b7`. About uses the complete approved 5.2 RU/EN copy
without shortening, semantic headings and left-aligned readable paragraphs. The
existing `/static/img/me.jpg` remains unchanged and is capped at 320 px. Old
biography/bullets/cards are no longer rendered. ACCA qualification versus former
FCCA status and the two-year GeekBrains Full-Stack Developer training wording
are preserved exactly.

Products retains its catalog-driven presentation, with explicit description,
capabilities-heading and conditions translation keys. The approved 5.3 copy,
exactly three capabilities and localized details CTA link to the existing
Landing. The conditions line explicitly names Microsoft Excel for Windows,
local data storage and one-time purchase without subscription. A single modest
bordered card replaces nested gradient/shadow framing; no price or purchase CTA.

Validation: **37 passed** through `.venv` with external pytest temp/cache paths
(`g5-about-products`): 5 About/Products web/catalog checks, 28 existing public
navigation checks and 4 Chromium cases covering both pages in RU/EN at 1280/375 px.
All eight page screenshots were visually inspected. Browser checks cover photo
size, left alignment/paragraph widths, no document overflow, simplified card
styling and keyboard CTA navigation with locale continuity. Focused Ruff and
Black checks (catalog/new tests) and `git diff --check` pass.

R17/R19 are implemented. At the G5 baseline, R18 card/content was implemented
while its final requirements link remained pending. G6 now completes that link
to the actual compatibility section (see G6 below). G5 itself did not add FAQ,
G3/G4, G9, checkout, consultation, footer/contact or backend behavior work. Full-suite,
live-customer and screen-reader validation were not run; final R45 review remains
open. Requirement definitions were not modified. No commit or push was made.

### G6 Compatibility / FAQ foundation implementation and validation

Implemented against clean `main` at `55cc6f2`. `app/faq_content.py` contains only
presentation data with explicit translation keys and paragraph/link blocks;
`faq.html` loops ordinary semantic group headings and native details/summary
questions. There is no CMS, persistence or accordion JavaScript. Only the ready
About SmartBudget (4 questions) and Before You Buy (7 questions) groups render.
Future approved groups can use the same shape under G12/G14/G15, without empty
placeholder groups now. The approved 5.6.1/5.6.2 copy remains intact.

The owner update supersedes the older R47 restriction against final public copy
and the older restart-free behavior. Narrow factual additions disclose the
confirmed manual Office-security boundary, localized Trust Center path, safer
prompt setting with Safe Mode enabled, required Excel restart and next-launch
recheck, plus the supported Microsoft 365 and 32/64-bit product matrix. Exact
validation configuration and reproduction limits remain internal. No unsafe
setting, automatic security change or experimental SendKeys recommendation is
published. Official Microsoft link targets are exactly those supplied in 5.6.2,
with new-tab/noopener behavior; RU retains official English targets.

Products adds a catalog-driven localized requirements link beside its conditions
to `/faq#system-requirements`, with sticky-header scroll clearance. G5 layout,
price-free content and product-details CTA are retained. R18/R31/R47 are
Implemented. R30 stays Partial for G12/G14/G15 content. G10 completes the
remaining Buy and Checkout disclosures under R32. The owner-verified Microsoft 365
environment is Excel 2608 Click-to-Run Current Channel on Windows, not an
independent Codex product test. 32-bit Excel was not separately practically
reproduced. These details stay internal: the public FAQ states support for both
32-bit and 64-bit Excel as a product compatibility commitment, not a claim that
every supported combination was reproduced during G6. The public future-release
boundary is retained; R47 is not reopened.

Validation through `.venv`, with required external temp/cache paths:
**57 passed** (`g6-faq-final`): 49 web checks (6 G6, 5 G5, 28 public navigation,
10 document-language) and 8 browser cases (4 G6, 4 existing G5), RU/EN at
1280/375 px. Native keyboard toggle/focus, Microsoft link reachability, long
answers, no nested scrolling/document overflow, locale continuity, actual Products
anchor positioning and card stability were checked. FAQ collapsed/expanded,
ActiveX guidance and Products screenshots were captured and visually reviewed.
Focused Ruff passes. Black passes for the FAQ data, catalog, route and changed
tests; the whole-file `i18n.py` check fails at baseline too, so unrelated
formatting is preserved. `git diff --check` passes. Initial new-test assertion and
changing-selector issues were corrected before the passing final run.

No full suite, screen-reader audit, live Microsoft-link availability test or
independent workbook/VBA test was performed. G6 validation did not cover
final R45 review or R48 artifact replacement. No G9/G10/G12/G14/G15
implementation, workbook/VBA,
Working Queue, deployment, commit or push work was performed. Requirement
definitions remain unchanged.

### G3 Feedback polish and validation

Implemented against `bce2a5e`. Fresh visits and successful submissions use the
required empty topic. Download-support visits retain intentional preselection
and prefill. The customers-only review label keeps the existing purchase
verification, and General question remains available before purchase with
optional email. The full-width submit, contained native picker, and approved
post-submit guidance retain the existing response ID and status announcements.

Focused validation passed **79 cases**: 11 Feedback prefill/render, 24 Feedback
API, 27 rate-limit, and 17 Feedback Chromium cases. The browser cases covered
RU/EN at 1280 px and 375 px, with eight form and confirmation screenshots
inspected. They exercised native keyboard and pointer file selection, purchase
verification, support prefill and reset, and file retention on 429 and 500
responses. Browser API responses were stubbed for those flows. The existing
Reviews case in the browser module was deselected. Final R45 review remains open.

In a separate manual check after implementation, the owner submitted a real
`general_question` with an empty email against local PostgreSQL. The response
returned a real message ID and the form reset to the neutral topic. The owner
accepted the desktop and 375 px mobile layouts, with no horizontal overflow
observed at 375 px.

The owner traced the initial HTTP 500 to PostgreSQL and Docker being stopped.
After starting the database, the same local submission succeeded.

### G4 Reviews visibility and validation

Implemented against `9cbed53`. Landing and the `/reviews` redirect resolve the
same exact RU/EN SmartBudget SKU. Landing uses one database existence query
with the public list's publication and feedback-type filters. The first
eligible review reveals the link on the next page load. The direct Reviews
page shows one approved empty-state message and a link back to SmartBudget.
Published reviews retain their existing public field projection and layout.

Focused validation passed **77 cases**: 18 Reviews, 14 Landing, 28 public
navigation, and 1 repository test, plus 16 Chromium cases across Reviews,
Landing, About/Products and checkout navigation. The four Reviews Chromium
cases used isolated SQLite fixtures and covered RU/EN at 1280 px and 375 px.
Empty and populated Reviews screenshots and representative empty Landing
screenshots were inspected. Final R45 review remains open.

### G10 Product Buy / Checkout implementation and validation

Buy presents the two language editions equally, describes the optional setup
session and shows catalog-owned prices. Checkout displays the selected product
and language, emphasizes Total and shows protected-download delivery with
booking instructions for bundles. Both screens include the approved compact
compatibility disclosure. When a requested add-on is unavailable, Checkout
withholds payment and offers an explicit product-only continuation for the
same SKU and currency.

Local validation used isolated catalog data and covered SKU/currency/add-on
preservation across RU/EN switches, unavailable selections and server-owned
totals. Chromium Buy and Checkout renders were inspected at 1280 px and 375 px.
Real hosted payments, email delivery and booking remain release-validation work.

### G11 standalone payment boundary implementation and validation

The separate service/provider mapping and operator CLI configure Lava.top
routing for an exact standalone consultation. Initiation resolves catalog
currency and amount, snapshots one service SaleItem and persists the provider
invoice identity on a pending Sale without a Product. Paid reconciliation uses
the existing item-owned entitlement workflow.

Local regression coverage uses stubbed Lava.top calls and verifies exact RUB/EUR
resolution, no discounted add-on fallback, recoverable invoice failure,
reconciliation-required commit failure and idempotent consultation-only
fulfillment. Migration `4b1e9d62c730` was upgraded, downgraded and re-upgraded
on isolated PostgreSQL 16, and `alembic check` reported no schema drift.
G12 now connects this boundary to public Checkout. Real provider validation
remains open.

### G12 public Consultations and standalone Checkout

The public catalog selects the active offer for the current language's package
and displays its catalog currency. A matching add-on price is informational.
When the standalone offer is missing, ambiguous or unmapped, the catalog
withholds its purchase link. Checkout preserves the exact service and currency
on language switches and shares the product Checkout per-IP POST rate limit.

Local tests use isolated catalog data and stubbed Lava.top invoices. They cover
RU/EN catalog and Checkout, service-only Sale snapshots, rejected selections,
provider and reconciliation failures, and unchanged product and bundle checkout
behavior. Chromium covers RU/EN navigation and both purchase pages at 1280 px
and 375 px. External validation still covers hosted payment, purchase-email
receipt with the protected booking link, first Calendly booking, confirmation
and meeting link, rescheduling, cancellation, guest access, screen sharing and
the meeting-platform fallback. R39 remains open for booking validation.

### Decision dependencies

The owner has completed D1–D6 at the product and architecture level.
Implementation, publication and external validation remain separately tracked.

| Decision | Owner-approved outcome | Remaining work |
| --- | --- | --- |
| D1 — Landing prices | **Decision complete.** Price-free Hero. The concluding section may show the current database-owned price and link to Buy. The approved 2,990 RUB / 49 EUR launch values are recorded in [commerce architecture](architecture/commerce_and_delivery.md#smartbudget-10-launch-pricing-and-product-use-rights). | G9 offer locally validated. Release-environment catalog validation remains open |
| D2 — Public contact boundary | **Decision complete.** Feedback and `support@neocitrix.com` where applicable are the official support path. Personal Telegram, WhatsApp, Facebook, VK, LinkedIn and email are excluded as public contact channels. Paid consultation remains separate. | G2B locally validated. UX-001 release-environment validation remains open |
| D3 — Standalone consultation checkout | **Architecture decision complete.** Standalone `ServiceAddon` and separate service provider mapping under [commerce architecture](architecture/commerce_and_delivery.md#standalone-service-routing-d3). | G11 and G12 implemented locally. Real provider validation remains open |
| D4 — Refund, withdrawal and seller information | **Product and architecture decision complete.** [Approved refund rules](architecture/commerce_and_delivery.md#approved-refund-rules-and-customer-requests-d4) and [consent and seller boundary](architecture/commerce_and_delivery.md#public-refund-policy-and-supply-consent-boundary) define the target. | Separate R42/R50/R53 capabilities, G15 synchronized publication, final seller details and operational validation |
| D5 — Purchase-email language | **Implemented locally.** Both public Checkout flows persist the order language on Sale at creation. Rendering and retries use the stored language. | Release-environment delivery validation remains open |
| D6 — Updates and support | **Decision complete.** Indefinite use of the purchased release, separately purchased new releases, possible corrected file as a defect remedy, and separate ordinary support and paid consultation. See [commerce terms](architecture/commerce_and_delivery.md#release-updates-and-support-d6). | G14 and synchronized customer-facing terms |

The current refund implementation remains founder-operated and full-Sale only.
It cannot yet preserve unaffected item access after an add-on-only refund.
Provider execution limits and pending machine-readable refund verification are
operational dependencies. The approved model does not establish independent
legal certification or authorize publication of the recovered policy.

### Accepted implementation groups

This is the accepted execution grouping for the mapped state, not a second
backlog or authorization to implement every group. Each sprint still needs a
separate bounded end state and verification commands. Shared R-IDs denote
surface-specific slices, not duplicate requirements.

| Group | R-IDs | Scope and dependencies |
| --- | --- | --- |
| G1 — Language/navigation | R01–R03 | **Accepted G1 scope implemented and validated**. G12 adds Consultations navigation. |
| G2A — Remove obsolete Telegram Landing block | R05 | **Implemented and validated**; complete heading/text/CTA removal, independently of D2; footer untouched. |
| G2B — Final public contact boundary | R04 | **Implemented and locally validated** in RU/EN on desktop and mobile. UX-001 release-environment validation remains open. |
| G3 — Feedback polish | R24–R27 | **Implemented and focused-validated.** See [G3 validation](#g3-feedback-polish-and-validation). |
| G4 — Reviews visibility | R28–R29 | **Implemented and focused-validated.** See [G4 validation](#g4-reviews-visibility-and-validation). |
| G5 — About / Products | R17–R19 | **Implemented and validated**; R17/R19 presentation retained, R18 final compatibility link completed by G6. |
| G6 — Compatibility / FAQ foundation | R30–R32, R47 | **Foundation implemented and validated**: grouped structure, R31, FAQ/Products R32 portion and R47. R30 later groups remain with G12/G14/G15. |
| G7 — Landing foundation | R07, R09, R11–R12 | **Accepted first-five-block scope implemented and validated**; approved Hero/reserves, shared image macro and supplied assets; G9 separate. |
| G8 — Landing demonstrations | R11, R13–R15 | **Implemented and validated** with exact supplied future-expense, PLAN/ACTUAL and reconciliation images/copy; R45 review remains open. |
| G9 — Practical/commercial Landing | R07, R08, R10, R16, Landing portions of R32/R34 | **Implemented and locally validated**: approved practical conditions, visible compatibility disclosure, database-priced concluding offer, Buy CTA and optional add-on note. |
| G10 — Product Buy / Checkout | R20–R23, applicable R32/R34/R49 | **Implemented and locally validated**: equal language cards, add-on terms, order summary, composition-sensitive delivery and compact compatibility disclosures. Policy publication remains with G15. |
| G11 — Standalone payment boundary | R06, R38 | **Implemented and locally validated**: separate provider mapping, operator configuration, service-only initiation and existing paid reconciliation. |
| G12 — Public Consultations | R03, R06, R23, R34, R38, applicable R51 | **Public catalog, navigation and standalone Checkout implemented and locally validated**. Real provider, email, booking and meeting validation remain open. |
| G13 — Purchase email | R35, R40 | **Implemented and locally validated.** Stores `Sale.purchase_language`, uses `en` for historical orders, renders the approved HTML/plain-text emails and blocks expired download links. Migration checks unresolved sends before switching templates. Release-environment delivery validation remains open. |
| G13B — Customer Email Correction | REL-001 | [Open pre-release Admin operation](release_readiness.md#g13b--customer-email-correction). |
| G13C — Reissue Download Access | REL-001 | [Open pre-release Admin operation](release_readiness.md#g13c--reissue-download-access). |
| G13D — Purchase Delivery Monitoring | REL-001 | G13D-1 is complete with local detection and PostgreSQL incident history. G13D-2a implements [one-pass Lava.top recovery](operations.md#g13d-2a-lavatop-payment-recovery). Scheduling, email recovery and subsequent operational integration remain open under the [release gate](release_readiness.md#g13d--purchase-delivery-monitoring). |
| G14 — Delivery presentation / FAQ | R33, R36–R37 | Implement delivery FAQ, timezone and expired-link guidance using approved D6 terms. |
| G15 — Policy publication | R41, R43–R44, R49, R51–R52, R54 | Publish the new owner-approved policy and seller section. Synchronize summaries with implemented Checkout, FAQ, email and refund operations. |

R42 remains a separate refund capability and operational implementation topic.
R50 applicable consent and R53 persisted request intake need their own bounded
scopes. G15 owns synchronized publication. R39 and R45 remain validation
work. R46 is complete, R48 is validated, and R55 remains deferred.

G1, G2A, G5 presentation/content and the accepted G7/G8 scope are implemented.
G6 foundation and the R18 requirements link are also implemented. G10 completes
R32, while R30 remains Partial for later FAQ groups. Further bounded tasks must
be explicitly scoped from the accepted groups; independent work need not wait
for unrelated decisions. G9 completes the seven-block Landing. G11 precedes
G12. Gate 2 is complete. Continue with Gate 3 implementation
and repeat review against the updated interface before the deployment and
live-validation gates.

### Validation-only and operational dependencies

Keep these separate from implementation; their existence does not authorize
speculative code changes or provider operations:

- Owner-verified Microsoft 365 validation is recorded above for Excel 2608,
  Click-to-Run, Current Channel on Windows; it is not a pending R47 requirement.
  Both Excel bitnesses are not independently established by that evidence, and
  no future-release guarantee is inferred.
- Calendly first-booking, confirmation, reschedule/cancellation and post-window
  end-to-end validation. Existing pre-linked-event tests do not prove this;
  collect integration evidence before deciding whether architecture must change.
- Actual meeting-platform/guest/screen-sharing and fallback validation before
  publishing conditional platform claims.
- Actual purchase-email receipt/content and capability-link validation after
  implementation, plus download expiry/interruption/repeat-download/support flow.
- Later live payment/provider validation under the deployment gates.
- Refund/provider/customer-communication validation after the approved D4
  capabilities are implemented. Keep partial refunds outside the current
  full-Sale workflow.
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
- Landing consultation CTA refresh: replace the outdated direct Telegram contact
  flow with the finalized consultation journey and rewrite the section headline,
  supporting copy, CTA label, and destination to reflect the approved
  Consultation → Checkout → Calendly flow; complete this during the final landing
  page and release-polish pass
- Public contact and social-link boundary: implementation under approved D2 is
  complete. Verify RU/EN destinations, ownership and configuration in the
  release environment under
  [UX-001](release_readiness.md#public-contact-and-social-link-boundary-ux-001).
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
