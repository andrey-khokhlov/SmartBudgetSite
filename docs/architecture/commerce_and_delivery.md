# Commerce and Delivery Architecture

## Purpose

This is the authoritative source for products, offers, sales, payments, product
releases, download entitlements, and protected product delivery.

## Product catalog and purchase path

- `family_slug` groups related SKUs into one product family.
- `slug` identifies one exact sellable SKU.
- `/products/{family_slug}/buy` bridges the product landing page and checkout.
- The landing page explains the product; package selection and prices belong on
  the buy page.
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
- Consultation add-on pricing must be visible before checkout. Checkout confirms
  selected items and total rather than revealing a price for the first time.

`products` and `service_addons` are catalog/configuration entities. They are not
purchase history.

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
confirmed automatically only by the authenticated provider webhook. Explicit
server-to-server payment verification is the founder-operated fallback for
known invoices and live validation, not the normal production completion path.

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
- current default token lifetime is 12 hours;
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

Refunds are administrative commerce operations. They are not customer-initiated
self-service actions in the MVP.

### Authoritative business rules

- Only an administrator may start or confirm a refund.
- Only a `Sale` whose payment status is `paid` is eligible for refund.
- MVP supports full-Sale refunds only. Partial refunds and item-level refunds are
  intentionally out of scope even if a payment provider supports them.
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

Lava.top UI supports a manually entered refund amount. After a real 50 RUB full
refund, the UI showed the 50 RUB amount, status `SENT`, refund date, and a Sales
refund marker. `GET /api/v2/invoices/{id}` continued to expose the original
invoice as `COMPLETED` without refund fields; the downloaded invoice and Sales
report exposed no useful additional refund data.

Neither public Lava.top documentation nor this live observation establishes a
refund-creation API, provider refund identifier, refund-status lookup contract,
idempotency contract, refund webhook, or complete status lifecycle. In the
verified live SmartBudget refund, Lava.top showed the full refund amount, status
`SENT`, and a refund date; the money later reached the customer's bank card
while the UI still displayed `SENT`, and no later `settled`, `completed`, or
equivalent UI state was observed. `SENT` is therefore provider-side evidence
that Lava.top sent or processed the refund, but not proof that bank/card
settlement has already occurred. SmartBudgetSite neither calls nor infers
undocumented provider capabilities and must not depend on a later Lava.top UI
transition to determine whether money reached the customer. For MVP, the
founder's explicit verification of the manual full refund is the authoritative
operator action permitting internal confirmation; it is not a claim of bank or
card settlement.

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
