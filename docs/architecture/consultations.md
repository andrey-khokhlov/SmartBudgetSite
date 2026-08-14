# Consultation Architecture

## Purpose

This is the authoritative source for consultation offers, purchase ownership,
booking entitlements, lifecycle transitions, Calendly integration, webhooks, and
admin visibility.

## Customer paths and pricing

SmartBudget has two distinct consultation paths:

1. A discounted setup consultation added to a SmartBudget purchase.
2. A higher-priced standalone consultation.

The add-on price is shown on the product buy page before checkout. The standalone
page shows its own price and terms. Calendly access is exposed only after a
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

## Purchase and booking are separate events

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
after that time; expired entitlements remain expired. `expired -> booked` and
`cancelled -> booked` are blocked. Lifecycle transitions belong in services,
not repositories.

The default booking window is 14 days after entitlement creation. It controls
when a slot must be booked, not the date on which the consultation occurs.
MVP uses bounded lazy reconciliation rather than a scheduler or background
worker. Opening Consultation Entitlements Admin reconciles every due available
entitlement before filtering or pagination, commits the transition through the
Admin request, and displays only persisted lifecycle state.

## Booking page and customer communication

The protected page exposes a config-driven `CALENDLY_CONSULTATION_URL` only after
validation. Provider URLs are infrastructure configuration, not business logic.
Missing provider configuration produces a deterministic fallback message.
Support diagnostics use a masked token reference and never reveal the full
token.

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
per keyed capability identity. Unsupported methods use 10 per 15 minutes per IP
and 5 per 15 minutes per capability, remain HTTP 405 before exhaustion, and do
not introduce a booking POST mutation. Rate-limit responses are localized,
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

It is not a validated first-booking reconciliation key because the entitlement
does not know the provider event URI before the booking exists. The initial
matching strategy remains an integration question until a real
`invitee.created` payload is captured through a public HTTPS endpoint. Possible
candidates include a backend token returned by Calendly, invitee email with
additional safeguards, or another supported tracking field. Do not finalize or
replace this architecture based only on assumed payloads.

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
