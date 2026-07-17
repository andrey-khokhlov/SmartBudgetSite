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

```text
Release candidate -> Published (active) -> Archived
```

## File storage

Cloudflare R2 is the primary binary storage provider. Product archives must not
be stored permanently on application VPS instances. R2 objects remain private;
the backend owns authorization and issues short-lived signed access only after
entitlement validation.

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
- signed-URL issuance records an attempt and updates attempt timestamps;
- current maximum attempts is three;
- issuance is not proof that the browser completed the transfer;
- status remains `available` after issuance while time and retry limits permit.

Lifecycle statuses are `available`, `completed`, `expired`, and `cancelled`.
Expiration may be derived dynamically without immediately mutating stored
status. Support-facing pages expose only a masked reference, never the token.

Strict one-time completion, automatic completion detection, IP/user-agent audit
records, and backend file proxying are deferred until reliable completion
criteria justify them. Future admin reissue/reset must be explicit and auditable.

