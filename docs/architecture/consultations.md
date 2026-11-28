# Consultation Architecture

## Purpose

This is the authoritative source for consultation offers, purchase ownership,
booking entitlements, lifecycle transitions, Calendly integration, webhooks, and
admin visibility.

## Customer paths and pricing

Under the [first-release sales model amendment](commerce_and_delivery.md#first-release-sales-model-amendment),
new public consultation purchases use only the existing standalone flow, with
their own Sale and payment transaction. Keep the capacity management requirement
for standalone sales. Preserve historical add-on pricing, SaleItems, entitlements,
booking and refund handling for existing bundles.

The implementation supports two distinct consultation paths:

1. A discounted setup consultation added to a SmartBudget purchase.
2. A higher-priced standalone consultation.

Public add-on selection and pricing must be suppressed while new bundles are
disabled. The standalone page shows its own price and terms. Calendly access is exposed only after a
successful paid purchase. Add-on and standalone provider access must remain
separate so a public user cannot obtain discounted booking access.

`ServiceAddon.service_type` defines what the service is, such as consultation,
onboarding, or support. `usage_type` defines how it is sold: currently `addon` or
`standalone`. Each usage scenario is a separate catalog record with one price;
do not introduce `addon_price` and `standalone_price` columns.

The business identity used for lookup and versioning is `family_slug`,
`package_code`, `service_type`, `usage_type`, and `currency_code`. Product
checkout explicitly requests `service_type = consultation`, `usage_type =
addon`, and the exact selected product currency; it must never load standalone
pricing or fall back to another currency implicitly. `ProductsRepository`
remains product-focused and does not resolve add-ons.

At most one offer may be active for one full business identity. Creating an
active version or reactivating a historical version automatically deactivates
the other active version in the same service-owned transaction. Currency and
usage type are parts of the identity, so corresponding RUB/EUR and
add-on/standalone offers remain independent.

### Standalone checkout boundary (D3)

A standalone consultation remains a separate `ServiceAddon` with
`usage_type=standalone`. Use the approved
[standalone service provider mapping](commerce_and_delivery.md#standalone-service-routing-d3)
for a service-only Sale. This keeps routing separate from product
`PaymentProviderOffer` mappings and preserves the paid confirmation boundary
for booking. Public Checkout is implemented. End-to-end payment, email and
booking validation remain open.

### Approved consultation prices by sales mode

Owner-approved on 2026-10-26 for 60-minute consultations:

| Sales mode | RU | EN |
| --- | ---: | ---: |
| `addon` with SmartBudget purchase | 3,900 RUB | 69 EUR |
| `standalone` | 5,900 RUB | 99 EUR |

The retained bundle pricing yields totals of 6,890 RUB and 118 EUR if that
mode is reactivated. Only standalone consultation pricing applies at launch.
These are independent market prices, not currency conversions. The complete
launch price table is recorded in `commerce_and_delivery.md`; runtime
consultation prices remain database-owned `ServiceAddon` data. Approval does
not claim that existing catalog records or public pages have been updated.
Consultation remains an optional paid service, and the existing offer identity,
entitlement lifecycle, booking, and capacity rules remain unchanged.

## Purchase and booking are separate events

### Cancellation and refund coordination

For standalone consultations, a cancellation request before the session starts
qualifies for a full refund, including when an appointment was booked or
prepared. Mandatory remedies remain available for undelivered, defective or
improperly delivered services. A refund leaves separate SmartBudget rights
unaffected.

Persisting a standalone consultation refund request also closes booking access
permanently under that Sale. A future consultation requires a new purchase.
The same coordination boundary applies when the founder starts a full refund
that includes a consultation, including historical bundles. A
`ConsultationCancellation` record per entitlement closes access without
changing booking lifecycle status at intake. Purchases on separate Sales are
independent. Calendly cancellation alone creates no refund request.

Before executing a monetary refund, check the consultation and booking
disposition. Keep outage exceptions visible with required follow-up so that
provider outages do not delay mandatory refunds beyond applicable deadlines.
Preserve booked-entitlement history and existing transaction and entitlement
ownership. Live initial booking-to-entitlement matching remains open under
R39. Verify the exact meeting and invitee before accepting cancellation evidence.
R39-C makes unused Shares eligible for the existing R39-B revocation pass
immediately after access closes. Verified delayed bookings and reschedules
update disposition evidence without restoring access. The founder verifies
the exact Event and Invitee and may cancel a verified upcoming one-on-one
appointment. The provider is contacted outside row locks. A bounded retry
claim and a target recheck prevent stale outcomes from overwriting a newly
linked meeting. A verified elapsed appointment with no active successor
satisfies provider disposition without a cancellation call. It establishes
neither service delivery nor monetary eligibility. Live validation remains open.

A purchased consultation is not automatically a booked consultation. The
customer may book later or never book. Sales administration tracks purchases and
payments; consultation lifecycle administration tracks booking access and
scheduled slots.

The backend owns the business right:

```text
Sale
    -> SaleItem (consultation service)
        -> ConsultationEntitlement
            -> protected booking page
                -> Calendly scheduling UI
```

Calendly supplies scheduling UI, slots, and calendar integration. It does not own
the right to book. Provider one-time links may be an implementation detail, but
backend validation remains mandatory and the provider must remain replaceable.

## Consultation entitlement

`ConsultationEntitlement` represents one customer right to book one consultation
and is the source of truth for access and lifecycle state. It belongs to the
specific service `SaleItem`, not the whole `Sale`.

MVP relationship:

```text
SaleItem (consultation service) 1 -> 0..1 ConsultationEntitlement
```

Only paid consultation service items receive entitlements. Product items do not.
The one-entitlement rule may later expand for multi-session packages, but no
universal entitlement table should replace domain-specific entities with
different lifecycle rules.

The entitlement owns:

- a backend-generated secure UUID booking token;
- expiry and status;
- provider reconciliation metadata;
- booked/cancelled timestamps as applicable.

It does not replace `SaleItem`, store catalog pricing, define raw provider
payloads, or render provider UI.

## Booking token and lifecycle

Public access uses `/consultation/book/{token}`. Before provider access is shown,
the backend validates that the token exists, the entitlement permits booking,
the booking window is open, and the related purchase remains valid.

Statuses are:

- `available` — valid access may proceed;
- `booked` — booking is confirmed and the token cannot be used again;
- `expired` — the booking window elapsed;
- `cancelled` — access is blocked.

Supported transition behavior includes `available -> booked`, `available ->
expired`, and an idempotent `booked -> booked` no-op. Time expiration applies
only when an available entitlement has `expires_at` at or before the current UTC
time. Booked and cancelled entitlements preserve their lifecycle history even
after that time. An expired entitlement can become booked only for its first
verified Calendly booking on a paid Sale. The Event and active Invitee must
match the pinned Event Type and signed Share correlation, and the provider's
invitee creation timestamp must be at or before `expires_at`. This also
applies to the first booking of an available entitlement. Late bookings,
cancelled entitlements and refunded Sales remain ineligible. Lifecycle
transitions belong in services.

The default booking window is 14 days after entitlement creation. It controls
when a slot must be booked, not the date on which the consultation occurs.
MVP uses bounded lazy reconciliation rather than a scheduler or background
worker. Opening Consultation Entitlements Admin reconciles every due available
entitlement before filtering or pagination, commits the transition through the
Admin request, and displays only persisted lifecycle state.

## Booking page and customer communication

The protected GET renders a localized booking form after validating the
entitlement. Its CSRF-protected POST exclusively provisions or recovers an
individual Calendly Share and redirects the customer to it after persistence and
an eligibility recheck. GET does not write to the database or call Calendly.
The POST cannot confirm a booking or mark the entitlement booked. Missing
configuration produces a localized fallback. Diagnostics use a masked capability
reference.

Provisioning locks the owning Sale and entitlement and commits an opaque claim
and the pinned Event Type URI before calling Calendly. The Share URI and
customer URL are stored in a subsequent transaction. A repeat POST reuses a
stored Share. An outstanding claim can only be recovered by listing the
authenticated Calendly user's paginated Shares within a creation-time window,
filtered by the pinned Event Type and matched to the exact server-set name
`SmartBudgetSite:<provisioning_reference>`. One matching valid Share is
required. An unresolved claim prevents another creation attempt. Payment
fulfillment remains independent of Calendly.

Known customer capability failures render through the normal public HTML layout
without weakening validation: an unknown token remains HTTP 404, while a
refunded/cancelled, expired, or already-booked entitlement remains HTTP 403.
The localized page never echoes the capability token, raw exception detail, or
internal/provider identifiers and retains the feedback/support link. The
consultation entitlement has no approved separate public support-reference
field; adding one remains a persistence and domain decision rather than a UI
fallback.

Every booking capability response, including framework-generated errors, uses
`Cache-Control: private, no-store, max-age=0`, `Pragma: no-cache`, `Expires: 0`,
and `Referrer-Policy: no-referrer`. Uvicorn access logging removes query strings
and replaces the booking-token path segment with `[REDACTED]`. Application,
exception, and operational logs must never contain the full booking capability,
and the production reverse proxy must disable access logging and caching for
booking capability routes.

Booking GET uses 60 requests per 15 minutes per client IP and 30 per 15 minutes
per keyed capability identity. The Share POST and unsupported methods each
use 10 per 15 minutes per IP and 5 per 15 minutes per capability in separate
buckets. Unsupported methods remain HTTP 405 before exhaustion. The POST
requires a signed double-submit token scoped to consultation provisioning and
the booking capability. Rate-limit responses are localized,
include integer `Retry-After`, preserve every capability protection header, and
never echo the token.

The intended paid flow shows the same protected booking access immediately on
the success page and in the confirmation email so the customer can return later.
Booking remains the customer's responsibility for MVP. Future capability-bearing
emails must disable click tracking and provider link rewriting.

Authoritative payment success creates a consultation entitlement for every
purchased consultation `SaleItem`. For product-plus-consultation bundles, that
entitlement and the product download entitlement are created atomically in the
same transaction as the Sale's paid transition. Payment fulfillment only makes
booking access available; the customer's later Calendly booking remains a
separate event and lifecycle transition.

## Webhook boundary

The route is `/v1/webhooks/calendly`. The request pipeline is:

```text
raw HTTP request
    -> HMAC signature verification using server-owned configuration
    -> malformed JSON protection and rejection audit
    -> provider event routing
    -> Calendly payload normalization
    -> provider-agnostic internal event
    -> reconciliation lookup
    -> idempotent entitlement lifecycle transition
    -> structured audit logging
    -> successful request transaction commit
    -> HTTP 204 response
```

The route receives raw bytes and headers, verifies the signature, parses the
request, and delegates. It does not contain lifecycle logic, repository access,
or inline provider-payload parsing. The route owns the successful request
transaction: it commits only after webhook processing succeeds and returns HTTP
204 only after the commit completes.

Provider payload shapes remain isolated in normalizers. Domain services consume
normalized events. Verification fails closed for missing, malformed, invalid, or
unknown-provider signatures and uses raw payload bytes with HMAC SHA-256.
Calendly signed timestamps must be non-negative ASCII Unix seconds within an
inclusive 180-second window on either side of server time; requests outside this
transport-level tolerance are rejected before provider event processing.

Before signature verification, the webhook is limited to 120 requests per
minute per client IP. After verification it uses a fixed Calendly provider
bucket of 300 per 5 minutes and a keyed signature-digest bucket of 10 per 3
minutes. A denied request returns JSON HTTP 429 with `Retry-After` and never
enters payload normalization, reconciliation, entitlement mutation, or commit.
Raw payloads and signatures remain excluded from limiter state and logs.

Webhook orchestration coordinates event routing and handoff; repositories perform
lookup only; the consultation entitlement service owns state transitions.
Lower-level lifecycle services flush their changes and do not own the commit.
Unsupported events, malformed payloads, invalid signatures, and reconciliation
mismatches remain safe and observable. Webhooks never create entitlements;
entitlements originate from successful purchases.

## Reconciliation and idempotency

`provider_event_uri` is unique when present and is a valid replay/idempotency key
after a booking is linked. Duplicate delivery must result in a safe no-op for an
already-booked entitlement.

First-booking matching uses `utm_content=v1.<reference>.<tag>`. The 22-character
reference encodes 128 bits of randomness. The 43-character tag encodes an
HMAC-SHA-256 over UTF-8 `smartbudgetsite:calendly-share:v1\n<share_uri>\n<reference>`
using `SECRET_KEY`. Both values use unpadded base64url. The reference uniquely
identifies the entitlement and the tag binds it to the persisted Share URI. The
provider's stored Invitee tracking must agree with the signed webhook tracking.
The customer-supplied tracking is an approved correlation mechanism and can
be copied between Calendly URLs. Tracking carries no booking capability or PII.

Reconciliation verifies the Event and Invitee through fixed-host API requests.
The provider's invitee creation timestamp determines the initial booking time.
It does not use webhook creation or receipt time. The Sale and entitlement are
locked before the first-booking transition. Exact replays preserve existing
metadata. A conflicting first booking is audited and does not replace it.

A reschedule requires an active replacement and a cancelled predecessor that
Calendly marks as rescheduled. Both invitees must identify each other through
the old/new relationship. When the predecessor is the stored current Invitee,
the replacement preserves the original `booked_at` and can reconcile after the
original booking window.

If the original Invitee has no stored mapping, reconciliation can use its
provider-verified signed tracking to recover the entitlement and persisted Share.
Both Events must match the pinned Event Type. Under the Sale and entitlement
locks, the paid, unclaimed entitlement can record the active replacement as its
first booking only if the original Invitee was created within the original
booking window. The original Invitee's creation time becomes `booked_at`.
Provider verification failures return a retryable response. Confirmed
relationship mismatches are audited without changing the entitlement. Initial live
booking, rescheduling and cancellation coordination still require live validation.

## Expired Share revocation

Local booking access closes at the exact `expires_at`. R39-B selects overdue
entitlements with a stored Share or unresolved provisioning claim and no
recorded booking. It does not depend on lazy entitlement expiration. The
worker commits an attempt before contacting Calendly and holds the existing
style of PostgreSQL advisory job lock across a bounded pass. Short write
transactions lock the Sale before the entitlement.

The worker recovers an unresolved claim through the same authenticated,
paginated booking-claim lookup before attempting deletion. It preserves the
Share identity and entitlement history. Only HTTP 204 from the unbooked Share
DELETE endpoint confirms revocation. A booked Share is preserved, and a 404,
ambiguous DELETE or unresolved ownership remains visible and unconfirmed.
Retries use persisted backoff. Provider-confirmed booked Shares leave the
deletion queue and are flagged for reconciliation or operator review.

The timer runs once per minute without a grace period. A copied Share can
remain bookable until confirmed deletion because of timer granularity,
backlog or provider failure. A valid delayed webhook still uses the original
provider booking time. The worker does not cancel meetings. Revocation for a
refund before expiry uses the same pass after R39-C closes access.

## Administration and operations

`/admin/consultation-offers` is the protected founder-operated consultation
catalog surface. It lists active and inactive `ServiceAddon` consultation
records, creates new offers from controlled product-family, package, usage, and
currency values, and edits only `name`, `amount`, and `is_active`. The
consultation-specific application boundary supplies `service_type =
consultation`; it is not founder input on this surface.
New records receive a server-generated UUID string as their purely technical
stable `code`; historical codes remain valid. After creation, `code` and every
business-identity field are immutable. Conceptually different offers require a
new record, and deactivation is the removal mechanism; there is no physical
delete path.

Catalog administration remains separate from purchased-right administration.

`/admin/consultations` is protected by the admin router. The admin view provides
customer email, sale-item context, status badges, booked time, provider event and
invitee links, result count, filtering, and newest-first ordering. Filtering
belongs in the service layer; eager repository loading avoids N+1 queries.

The current `ADMIN_TOKEN` plus HttpOnly cookie and `require_admin` approach is
accepted for MVP. Advanced users/passwords/roles are deferred.

Manual Calendly booking, cancellation emails, Google Meet, and Google Calendar
synchronization have been validated. Some users in Russia may require VPN access
to Calendly; a customer-facing fallback support option remains desirable before
launch.

### Operational capacity

New consultation checkout requires both an eligible catalog offer and
operational capacity. This applies to standalone consultations and to any
checkout with a consultation add-on if bundle sales are enabled separately.
`ServiceAddon.is_active` remains catalog versioning state.

PostgreSQL counts one global workload across currencies and sales modes. An
entitlement counts if its Sale is paid, its SaleItem is a consultation service,
its status is available, its expiry is strictly after the current UTC time,
and it has no ConsultationCancellation. This uses the expiry timestamp
directly. Calendly continues to manage scheduling, and booked appointments
are outside this workload.

Sales close at the configured limit of four by default and reopen below it.
The manual suspension in `/admin/consultation-offers` overrides automatic
availability and remains active until an operator resumes sales. An unknown
capacity state closes new consultation sales. Checkout checks capacity before
creating a Sale or contacting Lava.top. Already pending payments still fulfill
normally, so concurrent confirmations can exceed the limit. Paid booking
access and the entitlement lifecycle continue through their existing flows.

The scheduled dispatcher observes workload and records a warning when it rises
into the warning range (three by default), or an exhaustion alert when it
reaches the limit. Each threshold rearms after a sample below that threshold.
The observation and its two channel entries are committed together in a
consultation-specific outbox. See [operation and validation](../operations.md#consultation-sales-capacity).

### Consultation cancellation and refund requests (D4)

The implemented R53 request intake coordinates standalone consultation refunds
with the booking-access closure described above. The same R39-C disposition
checks apply when the operator starts a full-Sale refund that includes a
historical bundle. Preserve booking and delivery history. Consultation
early-start consent, where applicable, is separate from immediate digital
delivery consent. Commerce Architecture owns the
[refund rules and deferred bundle item accounting](commerce_and_delivery.md#approved-refund-rules-and-customer-requests-d4).
The [pre-sale gate](../release_readiness.md#refund--cancellation-policy-and-consent--mandatory-pre-sale-gate)
owns deployment, live verification, policy publication, and legal validation.
