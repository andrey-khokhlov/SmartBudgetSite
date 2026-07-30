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
- Currency mixing is forbidden at runtime; locale-aware formatting belongs in
  templates.
- Consultation add-on pricing must be visible before checkout. Checkout confirms
  selected items and total rather than revealing a price for the first time.

`products` and `service_addons` are catalog/configuration entities. They are not
purchase history.

## Sales and sale items

`Sale` is the order header. It owns customer identity, payment status, provider
transaction identifiers, total amount, currency, timestamps, and payment
metadata.

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
- If payment-session creation fails, preserve the `Sale`, mark it `failed`, keep
  `external_payment_id` null, and create no entitlements.
- Retrying after such a failure creates a new `Sale`.
- Payment identity is unique by `(payment_provider, external_payment_id)` when
  the external identifier is present.
- For Stripe, `Sale.external_payment_id` is intended to store the Checkout
  Session ID.

Provider webhooks must validate signatures from server-owned secrets, normalize
provider data at the integration boundary, and delegate business transitions to
services. Successful payment is the normal origin of delivery and service
entitlements.

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

Publishing verifies the persisted object's size and SHA-256 against R2 before
activating a release. Publication still uses the existing database lifecycle;
the administrative Publish control and future per-product concurrency control
belong to `REL-005`, not this upload workflow.

Founder-operated reconciliation compares database rows with paginated R2
listing plus per-row `HEAD` metadata. It is read-only by default. Explicit
orphan deletion is limited to sufficiently old objects matching the current
opaque managed-key format, after an immediate database ownership recheck.
Reconciliation never repairs or deletes database rows and never runs at startup.
Objects owned by active or historical inactive database releases are retained,
including releases referenced by sale items or download entitlements.

`REL-005` must place per-product database locking and storage verification
inside the publication transaction; the existing unique active-release index
remains the final invariant.

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
status. Support-facing pages expose only a masked reference, never the token.

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
