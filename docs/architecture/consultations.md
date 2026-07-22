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

Lookups include `family_slug`, `package_code`, `service_type`, and `usage_type`.
Product checkout explicitly requests `service_type = consultation` and
`usage_type = addon` and must never load standalone pricing implicitly.
`ProductsRepository` remains product-focused and does not resolve add-ons.

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

Supported transition behavior includes `available -> booked` and an idempotent
`booked -> booked` no-op. `expired -> booked` and `cancelled -> booked` are
blocked. Lifecycle transitions belong in services, not repositories.

The default booking window is 14 days after entitlement creation. It controls
when a slot must be booked, not the date on which the consultation occurs.
Expiration may be derived dynamically until a scheduled job or admin action
persists it.

## Booking page and customer communication

The protected page exposes a config-driven `CALENDLY_CONSULTATION_URL` only after
validation. Provider URLs are infrastructure configuration, not business logic.
Missing provider configuration produces a deterministic fallback message.
Support diagnostics use a masked token reference and never reveal the full
token.

The intended paid flow shows the same protected booking access immediately on
the success page and in the confirmation email so the customer can return later.
Booking remains the customer's responsibility for MVP.

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
