# Commerce and Delivery Architecture

## Purpose

This is the authoritative source for products, offers, sales, payments, product
releases, download entitlements, and protected product delivery.

## First-release sales model amendment

Owner-approved on 2026-11-13. SmartBudget 1.0 and standalone consultations
are separate purchases with separate Sales and provider payment transactions.
Product checkout is product-only. The existing standalone flow remains
available subject to consultation capacity management.

`BUNDLE_CHECKOUT_ENABLED` defaults to false and gates new public bundle
purchases. With the flag off, the public UI hides bundle selection and
pricing, direct bundle checkout links show an unavailable state with an
explicit product-only link, and the payment service rejects bundle initiation
before creating a Sale or provider invoice. Preserve bundle checkout orchestration, catalog identities,
SaleItem composition, fulfillment, purchase-email rendering, tests, and
historical financial records. Existing transactions continue to reconcile,
fulfill, and receive support under their original composition.

Reactivation requires an explicit owner decision and provider, refund,
regression, and operational validation. A provider migration with better
partial-refund support may enable reconsideration. The flag alone conveys
no authorization to reactivate.

### Refund scope and analytics

Preserve the operator-controlled full-Sale refund workflow. Defer the
multiple-`RefundOperation`/`RefundAllocation` proposal and automated
alternative bank payouts unless a genuine new requirement justifies them.
Maintain a documented operator procedure for exceptional and historical cases,
including review of applicable rights, original amounts, provider evidence,
and explicit customer agreement and evidence for an alternative refund method.
Existing customer refund rights remain in force.

Product Refund Rate is required before first public release. Use authoritative
production records for confirmed product sales and confirmed product refunds.
Exclude consultation-only refunds from the product refund count. Production
starts with a fresh database, and development and review Sales stay in their
original environments. Document the commercial launch date and time in UTC.
Include only product sales with authoritative payment confirmation at or after
that cutoff, and count confirmed product refunds only for those sales. This
excludes pre-release production test payments and their later refunds.

## Product catalog and purchase path

- `family_slug` groups related SKUs into one product family.
- `slug` identifies one exact sellable SKU.
- `/products/{family_slug}/buy` bridges the product landing page and checkout.
- The Landing Hero stays price-free. Under approved D1, the concluding
  commercial section may display the current database-owned product price
  and currency and link to Buy. Buy remains responsible for package selection.
- UI language and product package are separate. Package identity is derived from
  the selected product, not the current interface language.
- Product and add-on prices come from the database, never query parameters or UI
  input.
- The product catalog is the source of truth for price and currency. Business
  logic must not hardcode currencies.
- A product may have simultaneous active prices in different currencies. Public
  checkout requires an explicit currency, normalizes it by trimming surrounding
  whitespace and uppercasing, and resolves the active price strictly by product
  and currency. Checkout does not infer currency or fall back to another price.
- The approved MVP commercial model uses RUB product prices for Russian
  customers and EUR product prices for international customers. The selected
  product price determines the checkout currency.
- Currency mixing is forbidden at runtime; locale-aware formatting belongs in
  templates.
- If bundle checkout is reactivated, show consultation add-on pricing before
  checkout. Checkout confirms selected items and the total.

`products` and `service_addons` are catalog/configuration entities. They are not
purchase history.

## SmartBudget 1.0 launch pricing and product-use rights

The project owner approved the following launch prices on 2026-10-26. RU and
EN prices are independently defined market prices, not currency conversions.

| Product / service | RU | EN |
| --- | ---: | ---: |
| SmartBudget 1.0 — perpetual-use license | 2,990 RUB | 49 EUR |
| Standalone consultation, 60 minutes | 5,900 RUB | 99 EUR |
| Consultation add-on with SmartBudget purchase, 60 minutes | 3,900 RUB | 69 EUR |
| SmartBudget + consultation total | 6,890 RUB | 118 EUR |

The product-only and standalone rows apply at launch under the 2026-11-13
amendment. The bundle rows preserve the earlier approved prices. Runtime prices remain owned
by database `ProductPrice` and `ServiceAddon` records; this approval does not
update catalog data, provider configuration, or public website copy.
Consultation sales modes remain defined in `consultations.md`.

SmartBudget 1.0 is a **one-time purchase with no subscription**. The customer
may use the purchased SmartBudget 1.0 release indefinitely, including for
budgeting in future years. The limited lifetime of a protected download link
or `DownloadEntitlement` governs download access only: download-token expiry
does not limit continued use of a legitimately purchased local workbook.

### Release updates and support (D6)

The purchase grants indefinite use of the specific purchased release. New
commercial releases are purchased separately. Do not promise free minor
updates, lifetime upgrades, automatic workbook updates, or upgrade discounts.
SmartBudget runs as a local Excel workbook with no in-place update mechanism.
A corrected file of the purchased release may be supplied to remedy a defect
in that release. This does not confer access to future releases.

Ordinary support through Feedback covers purchase, delivery and download,
opening and access, and technical problems with the purchased release.
Individual setup, review of a customer's budget or file, screen sharing, and
personalized financial or product guidance belong to paid consultation.
Apply the approved terms consistently before publication under REL-001.

## Sales and sale items

`Sale` is the order header. It owns customer identity, payment status, payment
provider and provider-specific external payment identifiers, total amount,
currency, timestamps, and payment metadata.

`SaleItem` is the immutable snapshot of each purchased business item. Initial
item types are `product` and `service`. Each item preserves item type, ownership
reference, quantity, amount, and the catalog identity needed for fulfillment.

```text
Sale
    -> SaleItem (product)
    -> SaleItem (service)
```

Item-level ownership is required because product delivery, consultation booking,
refunds, and future services can have independent lifecycle states. Catalog
prices may change; purchased amounts must remain historically accurate.

`SaleItem` is the source of truth for purchase ownership. Legacy
`sales.product_id` may remain temporarily for migration safety, but new business
logic must resolve ownership through `Sale -> SaleItems`.

## Public purchase lookup

The public lookup supports the product-feedback flow without turning the API
into a general purchase-history endpoint. The customer enters the purchase
email, which is treated as a practical lookup key rather than strong proof of
identity or mailbox ownership. No email confirmation, magic link, one-time
code, or additional browser verification roundtrip is required for MVP.

The request contains the entered email. When no qualifying paid product
purchase exists, the response remains exactly `{"verified": false}`. When one
or more qualifying purchases exist, each safe result contains only:

- an opaque `purchase_reference`;
- public product name;
- public edition.

The response does not contain purchase dates; internal `sale_id`,
`sale_item_id`, or `product_id` values; payment-provider or external transaction
identifiers; amounts, currencies, payment metadata, or other unnecessary
purchase data.

The API route delegates the lookup rule to a service, and the service uses a
repository query against paid product `SaleItem` ownership. One purchase is
selected automatically without displaying a selector. Multiple purchases
display a selector using only the safe product context. Product-feedback
submission sends the normalized email and opaque `purchase_reference`; the
service resolves it only against paid product purchases for that email and
persists the internally resolved product association. Browser state is never
treated as authorization. False, malformed, and request-error responses fail
closed.

The accepted residual risk is that a person who knows the purchaser's email may
submit feedback as that purchaser. The lookup does not expose downloadable
products, payment information, or internal purchase records and cannot modify a
purchase. Feedback moderation provides the operational mitigation for MVP.

`POST /v1/check-purchase` is limited to 12 requests per 10 minutes per client
IP and 10 requests per 60 minutes per keyed HMAC of the syntactically valid,
normalized email. The IP rule is applied before body processing; the email rule
is applied before the lookup service. Positive and negative lookup results
consume the same quota. A rejected request returns JSON HTTP 429 with an integer
`Retry-After` header.

## Payment architecture

SmartBudgetSite uses a provider-independent payment architecture. Lava.top is
the approved first production provider for MVP. It is the first provider
implementation within this architecture, not temporary code or technical debt.
Stripe remains the strategic long-term target, but migration will occur only
after legitimate long-term Stripe infrastructure has been obtained. Purchased,
rented, nominee, borrowed, or third-party-owned Stripe accounts are not an
acceptable foundation.

Provider offer identifiers do not belong to the product catalog. The mapping is
persisted separately so one internal product can resolve the offer used by each
payment provider:

```text
Product
    -> PaymentProviderOffer
        -> provider
        -> external_offer_id
```

There may be at most one mapping for a product/provider pair. Lava.top
Price-by-request offers may be explicitly shared by multiple internal products:
each product retains its own mapping even when the mappings use the same
`external_offer_id`. Internal SKU identity, catalog price, currency, purchased
item snapshots, releases, entitlements, and fulfillment remain owned by
SmartBudgetSite. A provider offer identifier is routing configuration and must
not be used as the sole identifier for payment fulfillment or reconciliation.
For the first integration the canonical provider value is `lava_top`.

Product lifecycle and payment-provider configuration remain independent. The
normal operator path creates or updates a Product's explicit Lava.top mapping
through the protected product Admin UI; the CLI mapping script remains fallback
tooling. Creating a Product does not create a provider mapping, changing a
mapping does not change Product status, and the Admin UI does not call Lava.top
or validate an Offer ID remotely. The product Admin surface reports checkout
readiness from the existing prerequisites: `in_sale` status, at least one active
`ProductPrice`, an active `ProductRelease`, and a Lava.top mapping. This status
is informational and does not replace checkout's fail-closed server-side
resolution.

Lava.ru is not part of MVP. It may be evaluated later if commercial or
operational reasons justify another provider option.

Provider-specific integrations own only:

- checkout or session creation;
- invoice creation;
- webhook verification;
- webhook payload parsing;
- normalization into internal payment events;
- provider-specific identifiers;
- provider API communication.

Business services must not depend directly on Lava.top, Stripe, or another
provider's payloads. They operate only on normalized internal payment events.
`Sale`, `SaleItem`, fulfillment, download and consultation entitlements,
purchase emails, and delivery workflows must contain no provider-specific
business logic.

Historical sales remain associated with their originating provider and must
remain supported when the active provider changes. A future Stripe migration
must preserve and continue to support historical Lava.top transactions. The
architectural goal is to isolate provider differences so migration has bounded
impact. It is not guaranteed to be an adapter-only replacement: checkout
behavior, refunds, disputes, supported currencies, webhook semantics, and
operational procedures may differ between providers.

### Standalone service routing (D3)

G11 implements separate `ServicePaymentProviderOffer` routing keyed by
`(service_addon_id, provider)`. The server-side entry point resolves the exact
active standalone consultation and selected currency. It creates a pending Sale
with no Product and one service SaleItem at the catalog amount and currency.
Existing product `PaymentProviderOffer` rules remain product-specific.

From the target environment, a founder with database operator access can use
`python -m scripts.set_service_payment_provider_offer --service-addon-id ID --external-offer-id OFFER_ID`.
This configures the mapping for that catalog record without contacting Lava.top
or modifying catalog prices. A replacement catalog record needs its own mapping.

Missing or invalid offer selection or mapping fails before invoice creation.
Once prepared, a provider failure commits a failed Sale without an invoice ID.
A successful invoice is returned only after its ID is committed to the pending
Sale. If that commit fails, the transaction rolls back and the reconciliation
error retains the provider invoice ID. Authoritative paid reconciliation
creates the consultation entitlement from the service SaleItem.

G12 exposes standalone Checkout under `/consultations/checkout/{offer_id}`.
Its POST shares the existing product Checkout per-IP rate limit. Live provider
validation remains open.

### Confirmed Lava.top account capabilities

A real Lava.top creator account and creator profile now exist for SmartBudget.
The following facts were confirmed directly through that account's UI:

- the creator profile is named SmartBudget and uses the public slug
  `smartbudget`;
- `contact@neocitrix.com` is the Lava.top account contact;
- `support@neocitrix.com` is the public customer-support address, currently
  implemented as an inbound public-domain alias forwarded through Cloudflare
  Email Routing to a verified private destination mailbox; this forwarding does
  not establish a standalone hosted mailbox or configured transactional or
  outbound sending from the public address;
- Lava.top supports a digital `Product` content type with a cover image, product
  name, rich-text description, configured price, after-payment buyer message,
  and attached files up to the limit displayed by the platform;
- the product form exposes fixed prices in other currencies, price by request
  through API, multiple plans, and sales limits;
- Lava.top exposes a website payment-widget configuration flow; and
- Lava.top provides its own attached-file delivery capability.

The invoice-creation contract has now been confirmed separately from those UI
observations. SmartBudgetSite creates an invoice with
`POST https://gate.lava.top/api/v3/invoice`, authenticates with the server-owned
`X-Api-Key` header, and sends `email`, `offerId`, `currency`, and `amount`.
Supported invoice currencies confirmed for this flow are RUB, USD, and EUR.
The response includes `id`, `status`, `amountTotal`, and `paymentUrl`; the `id`
is persisted as `Sale.external_payment_id`, while `paymentUrl` is returned to
the caller without being logged. SmartBudgetSite remains the amount and
currency source of truth. Price-by-request is enabled, and the observed minimum
RUB invoice amount is 50 RUB.

The confirmed SmartBudget Lava.top Product ID is
`1fa401ab-a8bd-4704-b591-60fc7ff8fe8a`, while its Offer ID is
`cc1137ac-f8dd-4d51-bd37-738431d6461d`. Invoice creation uses the Offer ID, not
the Product ID. The real mapping is operational data and is not hardcoded or
seeded until a repository convention for provider mapping population is
approved.

The provider client, invoice orchestration, public checkout initiation route,
and neutral payment result page are implemented with mocked provider tests.
Webhook authentication, retry semantics, payout-country compatibility, real
hosted-checkout browser behavior, and complete production payment behavior
remain unvalidated.

The account observations do not change the approved responsibility boundary.
Lava.top owns only the provider boundary, including hosted checkout, payment
collection, and provider-specific payment integration. SmartBudgetSite owns
`Sale`, `SaleItem`, payment-state orchestration, `ProductRelease`,
`DownloadEntitlement`, consultation entitlements, customer purchase emails,
protected customer access, and private Cloudflare R2 delivery. The primary
product delivery path remains:

```text
Sale
    -> SaleItem
        -> DownloadEntitlement
            -> ProductRelease
                -> private Cloudflare R2 object
```

Lava.top attached-file delivery is therefore a confirmed but intentionally
unused provider capability, not the primary SmartBudget product-delivery
mechanism. The payment-widget configuration flow is likewise confirmed as
available, but has not been approved as the final SmartBudgetSite checkout
implementation.

## Checkout and payment confirmation

Provider-hosted checkout is the approved MVP user experience. Embedded card
forms are not an MVP requirement.

The approved customer journey is:

```text
Product page
    -> Buy page
    -> Backend prepares pending Sale and SaleItems
    -> Backend creates Lava.top payment
    -> Hosted Lava.top checkout
    -> Payment
    -> Buyer may remain on Lava.top
```

No Lava.top browser return to SmartBudgetSite is currently integrated; after
payment, the buyer may remain on Lava.top. `/payment/result` provides only a
neutral verification state if opened directly or used by a future supported
redirect. Browser navigation is never proof of payment. Payment completion is
currently confirmed automatically by the authenticated provider webhook.
Explicit server-to-server payment verification is available to the founder for
known invoices and live validation. G13D-2a implements an
[automatic recovery pass](#purchase-delivery-monitoring-g13d) for unresolved
invoices. Scheduled execution remains open.

While backend confirmation is pending, the payment result page may display a
payment-confirmation state. Only confirmed payment may:

- mark a `Sale` as paid;
- create download entitlements;
- create consultation entitlements;
- trigger purchase emails;
- unlock customer content.

## Payment preparation

- Product payment preparation selects the exact active release before provider
  interaction.
- It creates a pending `Sale` and `SaleItem`, then flushes without committing.
- A missing active release blocks provider interaction and triggers a best-effort
  admin notification. Notification failure must not replace the customer-facing
  unavailable result.
- Payment preparation remains provider-independent and does not call provider
  APIs directly.
- Higher-level orchestration owns provider calls and transaction completion.
- Public initiation accepts only customer email and the selected checkout
  configuration as browser inputs. It re-resolves the exact product and active
  currency-specific price, active release, optional consultation add-on, and
  provider offer server-side. Consultation selection resolves only
  `service_type = consultation` with `usage_type = addon`, requires the product
  currency, and creates a separate service `SaleItem`; the sale total is then
  derived from the persisted item snapshots.
- Checkout orchestration resolves `PaymentProviderOffer` for the prepared
  sale's product and provider. A missing mapping or provider configuration fails
  closed.
- Successful Lava.top invoice creation stores the returned invoice `id` in
  `Sale.external_payment_id`, commits the still-pending sale, and returns the
  hosted `paymentUrl`.
- If that identity commit fails after invoice creation, orchestration rolls back
  the database transaction and raises a reconciliation-required error carrying
  only the provider invoice ID. It does not retry provider invoice creation.
- If payment-session creation fails, preserve the `Sale`, mark it `failed`, keep
  `external_payment_id` null, and create no entitlements.
- Retrying after such a failure creates a new `Sale`.
- Payment identity is unique by `(payment_provider, external_payment_id)` when
  the external identifier is present.
- `Sale.external_payment_id` stores the originating provider's external payment
  identifier. A Stripe Checkout Session ID is one possible provider-specific
  example, not the field's universal meaning.

Provider webhooks must validate signatures from server-owned secrets, normalize
provider data at the integration boundary, and delegate business transitions to
services. Successful payment is the normal origin of delivery and service
entitlements.

For Lava.top, `contractId` is the provider invoice identity and is reconciled
exactly against `(payment_provider, external_payment_id)`. An Offer ID identifies
provider configuration, not a payment, and must not be used as the sole
fulfillment or reconciliation key. The Payment-result webhook accepts only
`payment.success` and `payment.failed` after constant-time verification of the
dedicated inbound `X-Api-Key`. The inbound webhook secret is separate from the
outbound Lava.top API key. Explicit server-to-server invoice verification uses
the same normalized payment event and domain reconciliation path.

The implemented Sale transitions are `pending -> paid` and
`pending -> failed`. Re-delivery of the already-applied terminal result is a
safe no-op. A conflicting terminal result, an unknown invoice, or a provider
amount/currency mismatch is observable as reconciliation-required and does not
rewrite history. Reconciliation locks the Sale row before applying a result.

On success, the paid transition and all `SaleItem` fulfillment are one database
transaction: every product item receives its exact-release
`DownloadEntitlement`, and every consultation service item receives one
`ConsultationEntitlement`. Bundles create both atomically. Existing correct
entitlements make replay idempotent; unsupported items, inconsistent existing
entitlements, or any creation failure roll back both the paid transition and all
new fulfillment. A pending Sale older than 24 hours is shown as stale in Admin
for operator reconciliation; stale is an operational condition, not a new
payment status.

Live server-to-server validation on 2026-08-10 reconciled the provider-successful
50 RUB Sale #6 from pending to paid and created exactly one
`DownloadEntitlement` for its sole product item. It created no
`ConsultationEntitlement` because the Sale contained no consultation item. A
repeat reconciliation returned idempotent and did not duplicate fulfillment.
The earlier 50 RUB Sale #5 remained pending because Lava.top reported its
invoice as non-terminal (`NEW`/`IN_PROGRESS` equivalent); no status was forced
manually. This validates manual invoice reconciliation for a product-only Sale.

On 2026-08-14, real Sale #8 validated the bundle path with a 100 RUB payment
(50 RUB product plus 50 RUB consultation). Lava.top reported the invoice as
`COMPLETED`; founder-operated manual reconciliation changed the Sale to paid
and made exactly one product entitlement and one consultation entitlement
available. The purchase email was sent and both protected access pages opened.
The run did not exercise live webhook delivery or a browser return from
Lava.top.

## Purchase email and delivery communication

Customer purchase email is a post-payment delivery workflow. It must never be
used as proof of payment and must not participate in the transaction that
authoritatively confirms payment.

The required ordering is:

    Authoritative payment confirmation
        -> Sale becomes paid
        -> all SaleItem entitlements are created atomically
        -> database transaction commits
        -> purchase email becomes eligible for delivery

A failure to send customer email must therefore never roll back a confirmed
payment, remove entitlements, or change a paid Sale back to another payment
state. Email delivery has its own durable operational lifecycle and must be
retryable independently from payment reconciliation.

Purchase-email delivery must be idempotent. Replayed provider webhooks, repeated
server-to-server reconciliation, or operator retries must not cause duplicate
customer purchase emails once the same delivery has already been completed.
The application must persist enough delivery state to distinguish at least an
email that still requires delivery from one that has already been sent or has
failed and requires operational attention. The exact persistence model and
migration are implementation decisions and are not prescribed here.

One Sale should normally produce one purchase email containing the customer
access relevant to all fulfilled SaleItems in that Sale. A product-only Sale
includes its protected product-download access. A Sale containing a
consultation entitlement includes the corresponding protected consultation
access. A bundle may include both in the same purchase communication.

Under approved D5, checkout or order creation must persist the resolved order
language (`ru` or `en`) in durable `Sale.purchase_language`. Webhook,
reconciliation, and retry email rendering must use that stored value.
A later browser request, webhook, currency, and SKU or package identity do
not determine email language. G13 implements the approved localized renderer for
product-only, bundle and consultation-only orders with focused tests. It
preserves payment confirmation, atomic fulfillment, Resend transport,
idempotency, and retry and reconciliation behavior.

G13 blocks transport when a download link has expired. With no ambiguous prior
attempt, delivery records a safe diagnostic and enters `FAILED`. For an
ambiguous attempt, delivery retains `SENDING` and its original
`sending_started_at`. The existing 23-hour window still governs transition
to `RECONCILIATION_REQUIRED`. Controlled reissue is a separate
[pre-release Admin operation](../release_readiness.md#g13c--reissue-download-access).

### Purchase delivery monitoring (G13D)

Normal customer fulfillment runs immediately after authoritative payment
confirmation. Monitor payment confirmation, entitlement fulfillment, purchase
email dispatch, and provider-reported delivery outcomes. The critical incident
detection SLO is 30 minutes, subject to when external providers expose reliable
evidence. Make critical notifications eligible for dispatch as soon as the
incident is detected. The SLO covers detection only.

Use Resend Webhooks as the primary source of provider email delivery events.
G13D-3 defines the scheduled jobs, independent alert delivery, and external
monitoring for the first commercial release.
The initial commercial release requires neither Celery nor Redis. Keep provider
credentials, recipient identifiers, API limits, and monitoring settings in
environment-owned configuration. The primary recipient for critical operational
email alerts is `khokhlov.a.a@gmail.com`. Application code must read the address
from that configuration.

Safe automatic recovery is required before public sales. Keep detection separate
from recovery orchestration and preserve the G13D-1 scanner's read-only access
to commerce and delivery records. Recovery may change those records only
through approved domain services:

- Verify unresolved Lava.top invoices through bounded API polling. A provider
  response of `COMPLETED` must match the stored invoice identity, amount, and
  currency before recovery invokes the existing authoritative payment
  reconciliation and fulfillment workflow.
- Attempt eligible pending purchase emails automatically. Retry eligible failed
  or ambiguous attempts only under existing idempotency guarantees. Preserve
  the 23-hour ambiguous-send boundary and the stable Resend idempotency key
  `purchase-email/{delivery_id}`. Retries may render the currently approved
  template with current application configuration. This supersedes the
  byte-equivalent request requirement. Recovery requires no original email body
  snapshots, immutable HTML or text copies, or request fingerprints solely for
  idempotency verification. Validate URLs and application configuration through
  deployment and configuration checks.
- If Resend returns `invalid_idempotent_request`, stop automatic attempts for
  that delivery, preserve its idempotency history, and set
  `reconciliation_required`. The existing G13D incident check escalates this
  state for operator review. Never generate a replacement key to bypass the
  conflict. `concurrent_idempotent_requests` and unclassified HTTP 409 responses
  retain the existing ambiguous-send handling and retry safeguards.

Recovery must never create a replacement payment or invoice, mark a Sale paid
without authoritative provider evidence, bypass payment or fulfillment
invariants, or reset email idempotency history. It must never reissue expired
download tokens without separately approved G13C rules, resend past the safe
retry window without the required provider reconciliation, change refunded
purchases, or restore revoked access.

Prevent overlapping recovery attempts and bound retries. Record recovery
attempts and outcomes. Keep customer PII, capability tokens, protected URLs,
and credentials out of diagnostics and notifications. Conditions that cannot
be resolved safely with the available evidence require operator intervention.
Persist incidents and alert the operator on unresolved problems. Track
measurable indicators of polling behavior so operators can decide when the
architecture needs revision.

#### G13D-1 local incident detection

G13D-1 scans committed data for every paid Sale, including historical test
transactions. Missing SaleItems, missing or incompatible entitlements, a
download entitlement for the wrong release, a missing purchase-email record,
and email states `failed` and `reconciliation_required` are immediate errors.
Entitlement checks cover fulfillment structure. Normal expiry, completed
downloads, and booked consultations do not signal a missing entitlement.

Email states `pending` and `sending` are warnings at five minutes or more.
Measure pending age from record creation and sending age from the start of the
ambiguous send, falling back to record creation if the start is absent. The
warning leaves the 23-hour retry boundary intact. The `sent` state records
Resend acceptance of the send request.

PostgreSQL stores one open incident per rule and Sale or SaleItem. A pass
serializes incident writes, reads fulfillment in one statement, and commits
incident updates together. It records first detection and last observation.
A later pass resolves the episode when the rule no longer matches, including
when the Sale is outside the paid population. A recurring condition creates a
new episode under the same identity and preserves the resolved episode.
Monitoring leaves commerce and email-delivery records read-only.

#### G13D-2a Lava.top payment recovery

G13D-2a keeps automatic lookup outcomes and scheduling separate from Sales
Admin's explicit payment-check fields. A PostgreSQL session advisory lock
prevents overlapping passes without keeping a database transaction open during
provider calls. After lookup, recovery locks and revalidates the Sale. An
existing terminal Sale takes precedence over the lookup. A validated
`COMPLETED` result uses the existing reconciliation and initial email
orchestration. `NEW` and `IN_PROGRESS` keep the Sale pending. An uncertain
`FAILED` result, invalid invoice evidence, or a domain reconciliation failure
pauses automatic attempts for operator review. The webhook and manual
reconciliation remain available. See the
[recovery command and polling schedule](../operations.md#g13d-2a-lavatop-payment-recovery).

#### G13D-2b Resend webhook delivery monitoring

After a public HTTPS endpoint is available, register and manage it in the
Resend Dashboard. Keep the existing production API key at Sending access and
prohibit Full Access keys. Store the dedicated webhook signing secret as
server-owned configuration. Use the official Svix verification library to
verify the original raw body before JSON processing, validate `svix-id`,
`svix-timestamp` and `svix-signature`, and enforce timestamp tolerance and
replay protection. Keep signing secrets, signatures and raw payloads out of
logs. See [Resend's verification documentation](https://resend.com/docs/webhooks/verify-webhooks-requests).

Subscribe to these events and exclude open and click tracking:

| Event | Meaning and handling |
| --- | --- |
| `email.sent` | Resend accepted the message for delivery. |
| `email.delivered` | The recipient's mail server accepted the message. |
| `email.delivery_delayed` | Resend is still attempting delivery. Suppress application resend. |
| `email.bounced`, `email.failed`, `email.suppressed` | Require operator attention. |
| `email.complained` | Create a separate complaint incident and preserve any successful delivery history. |

Use the provider email ID and the dedicated `purchase_email_delivery_id`
Resend tag as correlation evidence for `PurchaseEmailDelivery`. The send
response is authoritative for binding `provider_message_id`. A tag locates a
candidate, and an untagged legacy event can match a unique stored provider ID.
Webhook handling and send completion lock the same delivery row. An event
arriving before the provider ID is saved is committed as
`awaiting_provider_confirmation` without applying provider state. Send
completion applies pending events with an exact provider ID match in the same
transaction. A mismatch or five minutes without confirmation requires operator
review. The tag alone never establishes a binding.

Persist only
the provider email ID, internal delivery ID, event type, provider event
timestamp and Svix message ID, with receipt timestamp and processing outcome
where required. Exclude raw payloads, recipient addresses, subject, HTML or
text content, bounce messages and other unnecessary PII from persistence.

Deduplicate deliveries by Svix message ID and apply state updates
idempotently, including on manual replay. Use the webhook's top-level
`created_at` as the authoritative provider event timestamp for ordering.
The nested `data.created_at` records when the email record was created.
Older events must leave newer provider state intact. Track
complaints separately from delivery status, and keep provider delivery status
distinct from the existing `PurchaseEmailDelivery` dispatch lifecycle. The
monitoring pass removes receipts 90 days after first receipt. Provider delays
open automatically resolvable warnings. Terminal failures, complaints and
correlation issues create operator-required incidents tied to the originating
Svix event. The scanner leaves these incidents open. Explicit resolution
records the operator and reason without changing delivery or dispatch state.

G13D-2b observes and escalates delivery events. Sending and retries are
outside its scope. Safe automatic purchase-email recovery belongs to G13D-2c.
The 30-minute critical detection SLO applies when reliable provider evidence
reaches the endpoint. Provider outages, failed delivery attempts and endpoint
disablement can extend detection latency despite automatic webhook retries.
Healthchecks.io monitors our monitoring infrastructure. Establish successful
Resend-to-application delivery separately through the
[Dashboard delivery history](../operations.md#g13d-2b-resend-webhook-operations).

#### G13D-2c safe automatic purchase-email recovery

Only a newly applied successful payment starts immediate dispatch. Idempotent
payment replays leave email delivery to the recovery command or explicit
operator action. The recovery command uses the existing attempt service and
rechecks the paid Sale, due time, attempt count and provider evidence while
holding the delivery row lock. It commits the claim before contacting Resend.
The stable key and original ambiguous-send timestamp govern every retry.

Pending deliveries become eligible after the configured delay. A failed
delivery is automatically retryable only with a persisted `transient`
classification. The Resend adapter classifies an explicit
`rate_limit_exceeded` rejection as transient. Configuration, rendering,
expired download access and definitive request validation failures require
correction. Historical and unclassified failures are unknown. Ambiguous
provider outcomes remain in `sending`. Provider acceptance or other recorded
delivery or complaint evidence blocks automatic sending. A verified receipt
awaiting confirmation also suppresses automatic sending while leaving
provider-message binding to the authoritative send response.

Automatic recovery processes at most 20 deliveries per pass, with a
ten-minute minimum interval and a three-attempt ceiling using the existing
counter, including initial dispatch. The original 23-hour boundary still
moves exhausted ambiguous deliveries to `reconciliation_required` without a
provider request. An idempotency conflict also stops automatic attempts.
Explicit operator retries and reconciliation authorization remain separate.
See the [recovery command](../operations.md#g13d-2c-purchase-email-recovery).

#### G13D-3 operational monitoring

Run four independent Ubuntu systemd service/timer pairs. The Incident Scanner,
Lava.top Recovery, and Purchase Email Recovery each target a five-minute
interval. The Alert Dispatcher targets one minute. Stagger the schedules,
prevent overlapping runs of each job, and isolate failures so a failed job
does not stop the others. Each execution is short-lived and bounded and
records its outcome and sanitized diagnostics.

Use a PostgreSQL notification outbox with independent delivery state and
deduplication for each incident and channel. The Incident Scanner detects and
records incidents. The Alert Dispatcher owns network delivery through
the Telegram Bot API and independent SMTP. Channel state is persisted separately.
The dispatcher tries Telegram first when both channels are due. A failed
Telegram attempt falls back immediately to SMTP when SMTP is due. Subsequent
attempts honor each channel's own deadline. Provider acceptance on either
channel skips the other, and the dispatcher checks that the incident is still
open before each claim. Repeated scans preserve notification identities.
The dispatcher retries temporary failures
with backoff and uses at-least-once delivery. An interruption after provider
acceptance can result in a duplicate. Keep customer PII, payment information,
capability tokens, protected URLs, and credentials out of notifications.

G13D-3a implements the outbox and a dispatcher-callable materializer. Each
invocation considers up to 100 open incidents with missing channel entries in
incident ID order, including incidents recorded by Resend webhooks. It
commits both channel identities atomically and preserves existing delivery
state on repeated or concurrent calls. Resolving an incident leaves any
existing entries intact. Each entry stores only the incident
reference, channel, creation and attempt metadata, next attempt time, and
delivery confirmation time. Channel entries restrict deletion of their
incident. The dispatcher will own delivery and retry decisions.

G13D-3b implements one-pass dispatch with PostgreSQL overlap protection,
transactional claims, and a two-minute recovery lease. It commits each claim
before network I/O. Temporary and ambiguous failures retry after 1, 2, 5,
15, and 30 minutes, then every 60 minutes while eligible. Permanent failures
stop retries for the affected channel. Delivery means provider acceptance.

The Alert Dispatcher must recheck incident resolution before
delivery. Pending notifications for resolved incidents must not
be sent. Record them as skipped, preserving outbox history
and distinguishing skipped notifications from successful
deliveries. Review resolved, skipped, and recurring incidents
during a weekly operational review. Weekly review does not
replace immediate alerting for open incidents.

Use Healthchecks.io to monitor scheduled job heartbeats externally. Monitor
public HTTP/HTTPS availability with a separate external check. Detection of
monitoring failures must remain possible when local jobs or the Alert
Dispatcher are unavailable. See the
[operational targets and measurements](../operations.md#g13d-3-operational-monitoring-target).

Vultr telemetry and provider alerts are already configured. Host-level,
application-level, and PostgreSQL-specific monitoring integration remains
unimplemented. Select additional tools and production thresholds using the
actual deployed environment and observed workload. Complete integration and
validation before public sales.

#### Purchase email transport and protected URLs

Customer-facing delivery URLs must be generated from server-owned application
configuration rather than inferred from an incoming Host header or browser
request. Capability tokens and protected delivery URLs remain sensitive:
application logging, provider metadata, analytics, and other telemetry must not
record them unnecessarily.

Email transport is an infrastructure boundary and must remain separate from
commerce business logic. Business services must not depend directly on a
specific email provider API.

Resend is the approved first transactional-email transport for MVP. SmartBudgetSite
uses the Resend REST API with a server-owned `RESEND_API_KEY`; the provider
adapter is responsible only for transport-specific request and response handling.
The configured sender identity is `SmartBudget <support@neocitrix.com>`.
Inbound replies to that public address remain handled separately through
Cloudflare Email Routing.

The Resend domain `neocitrix.com` and outbound sending from
`support@neocitrix.com` were validated before application integration by a real
API send and successful delivery to an external Gmail mailbox. This validates
the transport and domain configuration only; it does not yet validate the
SmartBudgetSite purchase-email workflow, persistence, retry behavior, or
production delivery links.

## Payout operations

Payout routing is an operational concern and must not be encoded in business
logic or hardcoded into application architecture. The current operational
intention is to route RUB balances to a Russian payout destination and EUR
balances to a foreign EUR payout destination, avoiding unnecessary currency
conversion whenever same-currency payout is available.

Solo Bank is the currently planned foreign EUR payout destination, subject to
production validation. Solo payout compatibility must be validated before
release; this intention does not make a specific payout destination an
application-level dependency.

## Product and release ownership

`Product` represents a commercial SKU, not a file. `ProductRelease` represents a
concrete released file/version for that SKU.

```text
Product (what is sold)
    -> ProductRelease (what is delivered)
```

One SKU may have many releases, but only one active public release may be used
for new payment preparation. A database invariant and service publishing logic
must prevent multiple active releases.

New product `SaleItem`s store the exact `ProductRelease` selected before provider
interaction. Later publication must not silently switch a historical purchase to
a different release. Customers own the purchased SKU; the release reference is
the fixed delivery snapshot.

Legacy `Product.version`, `Product.release_date`, and `Product.archive_path` are
transitional fields. New delivery logic must not use them. After release and
download-entitlement integration is complete, remove them from the model,
schema, admin forms, templates, data scripts, and tests.

`ProductRelease` owns:

- version and release notes;
- archive and integrity metadata;
- storage provider and object key;
- publication state and release timestamp.

It does not own pricing, edition, family, product sale status, payment logic, or
customer ownership.

## Release administration

Product creation and release upload are separate operations. After product
creation, the admin flow should lead to release management. Routine releases are
managed from a dedicated dashboard entry.

Uploaded releases are inactive candidates. Publishing is an explicit service
action that atomically deactivates the previous active release, activates the
selected release, sets `released_at` when needed, and guarantees one active
public release per SKU. Templates and admin controls must not implement this
lifecycle themselves.

Publication owns one explicit database transaction. It locks the selected
release's owning `Product` row with PostgreSQL `SELECT ... FOR UPDATE` before
loading and changing the product's releases. All publication attempts for one
SKU therefore serialize on the same durable row, while different products may
publish independently. The existing partial unique active-release index remains
the final invariant. Re-publishing the active release is idempotent: storage is
verified again and the existing `released_at` value is preserved.

Administrative release archives have an inclusive application-level size limit
of 50 MiB (52,428,800 bytes). Archive size and SHA-256 metadata are calculated
in one bounded pass using chunks no larger than 1 MiB; the route does not read
the complete archive into a process-memory bytes object. An archive larger than
the limit is rejected with HTTP 413 before R2 upload or `ProductRelease`
persistence.

The upload service validates the product, version, filename, size, and archive
before creating an object. Each attempt receives a new opaque key under the
managed product-release prefix; keys do not contain the customer filename and
are never reused for a retry. R2 metadata records the expected SHA-256 and file
size, and a successful upload is confirmed with `HEAD` before database
persistence.

`(product_id, version)` is the idempotency identity. An identical retry returns
the existing release only after its R2 object is verified. A retry whose
filename, size, SHA-256, or normalized release notes differ returns a conflict
without touching storage. Database constraints remain the final concurrency
authority. A losing concurrent attempt removes only its own unique object after
the winning row is classified.

After an R2 side effect, database failure triggers rollback and a fresh-session
ownership check. A proven-unowned attempt object is removed. If ownership cannot
be established, or cleanup fails, the object is retained and the response
supplies an opaque operation reference for manual reconciliation. Existing
objects are never overwritten or deleted as compensation.

```text
Release candidate -> Published (active) -> Archived
```

## File storage

Cloudflare R2 is the primary binary storage provider. Product archives must not
be stored permanently on application VPS instances. R2 objects remain private;
the backend owns authorization and issues short-lived signed access only after
entitlement validation.

Publishing verifies the persisted object's size and SHA-256 against R2 inside
the product-locked publication transaction and before changing publication
state. Missing objects, metadata mismatches, and storage inspection failures
roll back the transaction and leave the active release unchanged.

Founder-operated reconciliation compares database rows with paginated R2
listing plus per-row `HEAD` metadata. It is read-only by default. Explicit
orphan deletion is limited to sufficiently old objects matching the current
opaque managed-key format, after an immediate database ownership recheck.
Reconciliation never repairs or deletes database rows and never runs at startup.
Objects owned by active or historical inactive database releases are retained,
including releases referenced by sale items or download entitlements.

The application-level release limit is evaluated after Starlette has parsed the
multipart request. It bounds application processing and route memory, but does
not prevent the request parser from receiving and temporarily spooling the full
multipart body. The production reverse proxy must therefore enforce a request
body limit slightly above 50 MiB to allow multipart overhead without weakening
the application file limit.

```text
SaleItem
    -> DownloadEntitlement
        -> ProductRelease
            -> private Cloudflare R2 object
```

This keeps binary storage independent from application hosting and permits VPS
or provider replacement without changing customer ownership.

## Download entitlement

`DownloadEntitlement` is the backend-owned source of truth for download access.
It belongs to a product `SaleItem`, not directly to a `Sale`, and references the
release already fixed on that item. Entitlement creation must never dynamically
resolve the currently active release.

MVP rules:

- only product items on paid sales are eligible;
- `product_release_id` is required;
- one product item has at most one entitlement;
- service items never receive download entitlements;
- tokens are secure, unique, and expire after a configured lifetime;
- newly issued download entitlements default to 24 hours after payment
  confirmation. Issuance uses `DOWNLOAD_TOKEN_TTL_HOURS`. Previously issued
  entitlements retain their stored expiry;
- every GET/POST access is validated before storage access is exposed;
- signed URLs are short-lived; the current default is 900 seconds;
- capability responses use `Cache-Control: private, no-store, max-age=0`,
  `Pragma: no-cache`, `Expires: 0`, and `Referrer-Policy: no-referrer`;
- signed R2 GET responses override cache behavior to the same private no-store
  policy and use an already expired response date;
- signed-URL issuance records an attempt and updates attempt timestamps;
- current maximum attempts is three;
- issuance is not proof that the browser completed the transfer;
- status remains `available` after issuance while time and retry limits permit.

Lifecycle statuses are `available`, `completed`, `expired`, and `cancelled`.
Expiration may be derived dynamically without immediately mutating stored
status. Customer access and error pages expose the approved opaque
`DownloadEntitlement.support_reference` separately from explanatory text, never
the capability token or an internal identifier. The reference remains visible
and selectable without JavaScript; the progressive copy action copies only the
reference value and provides localized success feedback.

Download capability paths, query strings, signed R2 URLs, and redirect
`Location` values must not be written to application or operational logs.
Uvicorn access logging retains ordinary request diagnostics while removing
query strings and replacing the token path segment with `[REDACTED]`. The
production reverse proxy must disable access logging and caching for download
capability routes. A customer purchase email may contain the capability because
delivery requires it, but click tracking or provider link rewriting must remain
disabled for capability links.

Rate limiting is separate from the three-attempt entitlement rule. Download GET
uses 60 requests per 15 minutes per client IP and 30 per 15 minutes per keyed
capability identity. Download POST uses 10 per 15 minutes per IP and 5 per 15
minutes per capability. Unsupported methods use the same 10/5 limits and remain
HTTP 405 until exhausted. A rate-limited POST performs no entitlement update,
storage-client creation, or R2 signing. Every download 429 retains the complete
capability response-header policy and contains no token or raw URL.

Strict one-time completion, automatic completion detection, IP/user-agent audit
records, and backend file proxying are deferred until reliable completion
criteria justify them. Future admin reissue/reset must be explicit and auditable.

## Refund architecture

The current full-Sale refund workflow is administrative. The approved D4
target separates customer request submission from operator-controlled money
movement. The rules below describe the existing workflow until the bounded
refund implementation is completed.

### Current full-Sale workflow rules

- Only an administrator may start or confirm a refund.
- Only a `Sale` whose payment status is `paid` is eligible for refund.
- The implemented workflow supports full-Sale refunds only. The approved
  consultation-only partial refund for a bundle requires separate implementation.
- SmartBudgetSite must preserve the originating payment provider and provider
  payment identity for every historical Sale. Refund execution must route through
  that originating provider so a future Stripe migration does not break refunds
  for historical Lava.top Sales.
- SmartBudgetSite must not change `Sale.payment_status` to `refunded` merely
  because an administrator requested a refund.
- `Sale.payment_status = refunded` is allowed only after the founder has
  completed the exact full refund manually in the originating provider and
  explicitly confirms in SmartBudgetSite that the provider evidence was
  verified. This operator confirmation does not claim bank or card settlement.
- `reconciliation_required` is reserved for real internal/provider uncertainty,
  not ordinary operator cancellation or validation failure. Manual database
  edits are not a supported recovery mechanism.
- Starting and confirming a refund must be idempotent. Repeated administrative
  actions must not create a second refund operation or repeat entitlement
  mutation.
- `Sale`, `SaleItem`, payment identity, refund-operation history, and entitlement
  history must never be deleted as part of refund processing.

### Entitlement consequences

A confirmed full-Sale refund revokes future customer access derived from that Sale.

For product items:

- `available` becomes `cancelled`;
- `completed`, `expired`, and `cancelled` remain unchanged;
- historical download-attempt and completion data must remain preserved;
- refund processing must not delete the entitlement or its audit history.

For consultation items:

- `available` becomes `cancelled`;
- `booked`, `expired`, and `cancelled` remain unchanged;
- booked consultation history must not be rewritten to make it appear that the
  consultation never occurred;
- refund processing must not delete consultation entitlement or provider event
  history.

Both protected capability validators also require the owning Sale to remain
`paid`. A refunded Sale therefore fails closed even when a historical entitlement
status is intentionally preserved.

### Administrative workflow

The implemented normal operator flow is:

`Sales -> Sale -> Refund -> confirmation`

The protected Sale detail page requires explicit acknowledgement before creating
the one pending operation. The founder then performs the exact full refund
manually in Lava.top Sales. SmartBudgetSite makes no provider refund API call.
After verifying the full amount and provider-side evidence, the founder must
explicitly acknowledge `I verified the full refund in Lava.top.` before internal
confirmation can reconcile the Sale and entitlements.

The administrative surface must distinguish at least:

- refund available;
- refund operation in progress or awaiting authoritative confirmation;
- refund confirmed;
- reconciliation required / provider outcome uncertain;
- refund unavailable because the Sale is not eligible.

Provider-specific error text, credentials, raw payloads, or secret identifiers
must not be exposed unnecessarily through the Admin UI.

### Provider-independent boundary

Refund business logic belongs in the application/service layer and operates on
provider-independent refund concepts.

Future provider integrations may be responsible for:

- provider-specific refund execution;
- authentication;
- provider refund/payment identifiers;
- provider-specific statuses and responses;
- authoritative refund verification or lookup;
- normalization into the internal refund lifecycle.

The domain layer must not assume that Lava.top, Stripe, or another provider uses
the same refund endpoint, status model, webhook behavior, idempotency mechanism,
or timing semantics.

### Lava.top MVP contract

Confirmed provider facts supplied by direct Lava.top support:

- Refund initiation through API is currently unavailable. Support passed the
  request/idea to the provider's developers; this is not a delivery commitment.
- One Lava.top transaction permits at most one refund. A second refund against
  the same transaction is unsupported.
- Lava.top processes its side of a refund immediately; customer bank/card
  settlement may take up to 10 business days.

Live UI observations: Lava.top supports a manually entered refund amount. After
a real 50 RUB full refund, the UI showed the 50 RUB amount, status `SENT`, refund
date, and a Sales refund marker. `GET /api/v2/invoices/{id}` continued to expose the original
invoice as `COMPLETED` without refund fields; the downloaded invoice and Sales
report exposed no useful additional refund data.

In the verified live SmartBudget refund, Lava.top showed the full refund amount,
status `SENT`, and a refund date; the money later reached the customer's bank card
while the UI still displayed `SENT`, and no later `settled`, `completed`, or
equivalent UI state was observed. `SENT` is therefore provider-side evidence
that Lava.top sent or processed the refund, but not proof that bank/card
settlement has already occurred. SmartBudgetSite neither calls nor infers
undocumented provider capabilities and must not depend on a later Lava.top UI
transition to determine whether money reached the customer. For MVP, the
founder's explicit verification of the manual full refund is the authoritative
operator action permitting internal confirmation; it is not a claim of bank or
card settlement.

Unresolved provider capability: authoritative refund verification/reconciliation
through API, webhook, lookup, or another machine-readable mechanism remains
unconfirmed while Lava.top support investigates and prepares a response.
Neither public documentation nor the live observations establish a provider
refund identifier, refund-status lookup contract, idempotency contract, refund
webhook, or complete status lifecycle. SmartBudgetSite must not claim independent
machine-readable verification of refund completion until such a contract is
confirmed. This pending question is separate from confirmed API initiation
unavailability.

### Persisted refund operation

`RefundOperation` is separate from terminal `Sale.payment_status`, with exactly
zero or one operation per Sale enforced by a database uniqueness invariant. Its
provider-independent lifecycle is `pending`, `confirmed`, or
`reconciliation_required`; there is no terminal `failed` state.

The persisted model supports `reconciliation_required`, but the current
founder-operated Lava.top MVP implements only `no operation -> pending ->
confirmed`. No current service or route automatically transitions an operation
to `reconciliation_required` or sets `reconciliation_required_at`. That status
is reserved for a future explicitly implemented uncertainty and recovery path.

The operation snapshots the full Sale amount, currency, originating payment
provider, and external payment ID. It also stores request/confirmation/
reconciliation timestamps plus optional provider refund identity, provider
status, and observation time for future integrations. Optional provider metadata
never drives `Sale.payment_status` directly.

Creation requires a paid Sale, non-empty provider and external payment identity,
and no existing operation. The workflow accepts no operator-entered amount, so
partial and item-level refunds cannot enter it. Confirmation owns one database
transaction, locks the Sale, operation, and both entitlement sets, revalidates
the immutable snapshot, reconciles access, and only then changes the operation
to `confirmed` and the Sale to `refunded`. Any reconciliation failure rolls the
whole transaction back.

<a id="deferred-customer-refund-requests-and-item-targeted-refunds"></a>

### Approved refund rules and customer requests (D4)

SmartBudget offers a voluntary full refund without a reason within 14 calendar
days of confirmed payment, including after download, opening or use. Mandatory
defect and non-conformity rights remain
unaffected. Troubleshooting may be offered and must never replace mandatory
refund or remedy rights. Consultation cancellation is handled separately. If the
consultation has not started, policy permits cancellation for a full refund of
its price.

The earlier D4 bundle directions below are retained as design history. All
transactions to date are tests. The first public release offers separate Sales
and payments, and refunding a standalone consultation leaves a separately
purchased SmartBudget licence unaffected. Preserve test-data compatibility.

The retained bundle implementation uses one Sale and one provider payment
with separate SaleItems. Earlier D4 refund directions used the original item amounts:

- If the customer cancels only an add-on consultation and keeps SmartBudget,
  refund only the consultation SaleItem and preserve the product access. This
  direction requires item-level accounting.
- If the customer refunds SmartBudget from a bundle, refund the entire bundle.
  This applies even when the consultation has already been delivered. The
  add-on does not survive the product refund. If a consultation is wanted after
  the refund, the customer must make a new standalone purchase at the then-current
  standalone price. Do not retroactively convert or reprice the add-on.

Preserve the single-payment bundle implementation and historical transaction
composition under the [first-release amendment](#first-release-sales-model-amendment).
The Lava.top limit of one refund
action per transaction constrains execution. It does not limit customer rights.
If a later required refund cannot go through the original provider path, an
alternative method may be used only with the customer's explicit agreement
and appropriate evidence. Preserve original purchase, payment and entitlement
history, including evidence of any consultation already delivered.

R53 requires a bilingual `/refund-request` form for SmartBudget and standalone
consultation purchases. Identify the purchase, persist the explicit request
and evidence, and send receipt confirmation. Keep the form accessible for
requests after the voluntary deadline. A voluntary SmartBudget request within
the window requires no reason. Feedback and support email remain available
for support and fallback. Money movement stays operator-controlled.

After successful persistence, trigger a durable operator notification through
Telegram, with administrative email/SMTP fallback when delivery is unconfirmed.
Preserve retries and delivery evidence. Exclude financial and card details,
capability tokens and unnecessary personal data from alerts. Notification
failure must leave the request intact, and operators must see pending requests
and their age. Reuse established transport and reliability patterns where
appropriate while keeping requests outside purchase-delivery incidents.
Notification and reminder design and R53 implementation remain pending.

The first-release amendment defers bundle item-accounting implementation and
keeps exceptional or historical cases under the operator procedure. Request
intake still needs bounded implementation and validation. Preserve the current
paid-Sale capability checks and `RefundOperation.sale_id` uniqueness.
Any future partial refund design must preserve unaffected access and account
for amounts already refunded.

#### Voluntary SmartBudget refund eligibility clock

R42a persists nullable `Sale.paid_at` in server-side UTC on the first
authoritative transition from pending to paid, in the same transaction as
payment confirmation and fulfillment. Webhook replays and manual reconciliation
preserve the stored value, including NULL for historical paid Sales.
`NormalizedPaymentEvent` carries no reliable provider payment timestamp.
`Sale.created_at` records pending-order creation and must not start the window.

R42b implements `assess_voluntary_refund_window(paid_at, *, now=None)` in
`app/services/refund_eligibility_service.py`. It defaults to server UTC and
normalizes aware inputs to UTC before adding 14 days to the payment timestamp.
It returns an immutable status and deadline. The deadline is inclusive
(`within_window`), and later times are `expired`. Missing, invalid, or future
payment timestamps yield `manual_review` with no deadline. A caller-supplied
assessment time must be timezone-aware.

R42c displays the assessment and any UTC deadline on the protected Admin Sale
Detail page for paid Sales containing a product item. This is read-only
information for the operator. The existing full-Sale refund controls and
provider verification requirements apply regardless of the assessment. Manual
review applies to legacy paid Sales with no timestamp. Consultation
cancellation follows separate rules. The approved policy says “within 14
calendar days of payment confirmation”. Use the inclusive UTC deadline.

Expiry affects only the voluntary no-reason SmartBudget refund. Continue to
accept online requests after the deadline and let the operator distinguish an
expired voluntary window from requests for defects, non-conformity, statutory
rights or other applicable remedies that still require review.

### Public refund-policy and supply-consent boundary

R49–R55 define the public requirements and release readiness owns the pre-sale
gate. The [2026-11-14 publication candidate](../release_uiux_requirements.md#appendix-b--approved-refund-policy-publication-candidate)
supersedes the recovered policy. Align Checkout, FAQ, purchase email and actual
operations before publication and independently validate applicable obligations.

Payment, email, protected access and downloading do not establish a universal
waiver of mandatory rights. For orders containing SmartBudget, support a
separate, initially unchecked express request for immediate digital delivery
where legally applicable. Keep it separate from Privacy, Terms and marketing.
The voluntary 14-day SmartBudget refund policy remains available even when
statutory withdrawal consequences differ. Where applicable, separate early
consultation-start consent from digital-content consent. Persist the evidence
with the order and accurately reflect it in purchase communication. These
consents address supply and service commencement. Do not present them as
anti-abuse measures. Keep legal applicability,
supply-start and no-consent handling, and durable confirmation in the bounded
implementation and publication review. Do not infer legal applicability from
locale, SKU, currency or payment method.

The 2026-11-14 decision supersedes the earlier policy-only seller disclosure.
Publish a bilingual `/legal/seller-information` page linked from policy §9,
the neutral footer label “Юридическая информация” / “Legal Information”,
and the pre-payment Checkout legal-disclosure flow. Keep the address and
telephone on that page. The approved identity is Хохлов Андрей Александрович /
Andrey Alexandrovich Khokhlov, an individual using the professional income tax
regime (NPD/self-employed), with `support@neocitrix.com` as public support email.
Publication is blocked until the owner securely supplies the actual geographical
address and mobile telephone.

R54 accepts that customers can retain autonomous local copies after refund;
policy should explain the end of continued-use rights under applicable law and
licence terms and ask customers to stop use and delete copies, without restricting
statutory protections. SmartBudget cannot claim remote removal, inspection,
deletion verification or disabling of downloaded copies. Keep these technical
limitations internal. Public policy uses the approved §6 wording, including
the boundary against requesting device access or personal financial data.
R55 excludes preventive
activation, DRM, time limits and mandatory continued server contact from the
first release; reconsideration requires observed post-release evidence and
explicit review. This does not weaken backend download/booking authorization.
