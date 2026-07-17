# Sprint Checkpoints

> Status: Historical record.
>
> This document preserves the project checkpoints, decisions, limitations, and
> planning notes that were previously maintained in
> the former monolithic backend architecture document. It is not an active source of truth. Use
> `docs/README.md`, `docs/current_state.md`, and the documents under
> `docs/architecture/` for current guidance.

## Historical resume instructions

The former monolithic document began with session-resume instructions. At that
time, developers were directed to review the architecture and feedback workflow,
locate the latest sprint checkpoint and next-sprint priorities, and continue from
the first unfinished item. Those instructions were superseded by the current
documentation index and source-of-truth boundaries.

---

# Historical Backend Architecture and Sprint Record

## Related project documents

* `docs/product_positioning.md` — primary product strategy document describing the long-term vision, positioning, and product philosophy of SmartBudget.
* `docs/architecture/feedback.md` — feedback workflow and related operational rules.

---

## Purpose

This document describes the structure of the backend and separation of responsibilities.

---

## High-level layers

The backend is divided into several logical layers:

### 1. Web layer (`app/web`)

Purpose:

* Render HTML pages (Jinja templates)
* Handle browser-based interactions
* Return `TemplateResponse` or `RedirectResponse`

Examples:

* `/feedback`
* `/admin/feedback`
* `/admin/feedback/{id}/send-email`
* `/admin/products`

---

### 2. API layer (`app/api/v1`)

Purpose:

* Provide JSON endpoints
* Used by frontend or external clients
* Return structured data (Pydantic models)

Examples:

* `/v1/check-purchase`
* `/v1/feedback`

---

### 3. Service layer (`app/services`)

Purpose:

* Contain business logic
* Independent from HTTP (no Request/Response)
* Reusable across Web and API

Examples:

* `send_feedback_reply`
* `toggle_feedback_publish`

Rules:

* Services may raise `HTTPException`
* Services operate on database models
* Services should not render templates

---

### 4. Repository layer (`app/repositories`)

Purpose:

* Encapsulate database access
* Provide reusable DB queries

Examples:

* `FeedbackAdminRepository`
* `ProductsRepository`

---

### 5. Core layer (`app/core`)

Purpose:

* Infrastructure
* Database engine, session
* Config, logging, i18n

---

### 6. Dependencies (`app/dependencies`)

Purpose:

* Dependency Injection (DI)
* Provide shared dependencies (e.g. DB session)

Important rule:

* Use `get_db` from this module everywhere
* Do not duplicate dependency functions

---

## Request flow

Typical flow:

Web route → Service → Repository → DB

or

API route → Service → Repository → DB

---

### Payment transaction boundary

Payment preparation services may:

- validate business rules;
- create pending Sale/SaleItem records;
- flush the database session.

Payment preparation services must NOT:

- commit transactions;
- communicate directly with payment providers.

The transaction boundary is owned by the higher-level payment orchestration flow.

---

## Design principles

* Keep routes thin (no business logic)
* Move logic to services
* Avoid duplication
* Use a single DI entry point
* Keep layers independent

---

## Configuration management

Whenever a new application setting is introduced:

- add it to `.env.example`;
- add it to the active local development `.env`;
- verify whether deployment documentation and production environment variables also require updating.

A configuration change is not considered complete until both the example configuration and the active development configuration have been updated.

Sensitive values must never be committed to the repository. Only placeholder values belong in `.env.example`.

---

## How to implement new features

When adding new functionality, follow this order:

### 1. Define business logic in service

```python
def some_business_action(db: Session, ...):
    ...
```

---

### 2. Use service in route

Web route:

* call service
* return `TemplateResponse` or `RedirectResponse`

API route:

* call service
* return JSON

---

### 3. Use repository inside service

* do not access DB directly from routes
* use repository methods for queries

---

### 4. Add tests

Prefer testing services:

* test business logic directly
* verify DB changes
* verify exceptions (status_code, detail)

Optionally:

* add route tests for critical endpoints

---

## What NOT to do

Avoid:

* putting business logic in routes
* duplicating logic across routes
* creating multiple `get_db` implementations
* mixing HTML rendering with business rules

---

## Refactoring rule

If a route starts to contain:

* multiple `if` conditions
* validation logic
* DB updates

→ move this logic to a service

---

## Sprint checkpoint: admin feedback refactoring and tests

### Completed:

* unified `get_db` usage via `app.dependencies`

* removed duplicate DB dependency definitions

* made `feedback_messages.email` nullable

* added Alembic migration

* introduced service layer

* moved all feedback logic to `feedback_service`

* isolated email sending in `mail_service`

* added full service test coverage:

  * email sending rules
  * publish/unpublish
  * resolve toggle
  * reply draft
  * validation edge cases

* added route-level tests for critical flows

* implemented real SMTP sending (Gmail App Password)

* ensured:

  * clean separation of concerns
  * no real emails in tests (global mocking)

### Architecture decision:

* service tests = business logic
* route tests = wiring only

---

## Sprint 12: current admin products state

### Implemented:

* `ProductsRepository`
* route `/admin/products`
* route `/admin/products/new` (GET)
* template `admin_products_list.html`
* template `admin_product_form.html`
* basic route test for `/admin/products`
* list page is styled and acts as central admin UI

### Current limitations:

* Edit flow is not implemented
* Create form is temporary
* POST create must NOT be finalized yet
* product model still reflects old pricing logic

---

## Sprint checkpoint: product-based reviews

### Completed:

* added `product_id` to feedback
* created FK and migration
* backfilled existing data
* implemented product-scoped reviews
* added `/reviews/{slug}`
* redirect `/reviews → /reviews/smartbudget`
* updated repository, routes, tests

### Architecture decisions:

* reviews are product-scoped
* use `product_id` (not slug) internally
* reviews are scoped per product SKU (e.g. SmartBudget RU vs SmartBudget INT are independent)

---

## Sprint 17: Product family purchase flow

### Completed:

* added `family_slug` to products
* implemented product-family purchase options route:

  * `/products/{family_slug}/buy`
* linked SmartBudget landing CTA to:

  * `/products/smartbudget/buy`
* added repository method:

  * `ProductsRepository.list_products_by_family_slug`
* purchase options page now:

  * loads only products from the selected `family_slug`
  * shows only products with status `in_sale`
  * displays active product price from `product_prices`
  * links selected SKU to `/checkout/{product_slug}`
* checkout route now accepts optional consultation query flag:

  * `/checkout/{product_slug}?consultation=1`
* added shared helper:

  * `app/utils/product_utils.py`
  * `get_product_package(slug)`
* package display (`RU` / `INT`) is now derived from selected product SKU, not from UI language
* tests updated and passing:

  * repository coverage for product-family filtering
  * repository coverage for active price loading

### Architecture decisions:

* `family_slug` groups related SKUs under one product family
* `slug` still identifies one exact sellable SKU
* `/products/{family_slug}/buy` is the correct bridge between landing and checkout
* UI language and product package are separate concepts
* product package must be derived from selected product identity, not from current site language

### Current limitation:

* consultation can be selected in UI and passed to checkout as a query parameter
* checkout can display that consultation was selected
* consultation price is not yet calculated from the database
* total amount still reflects product price only until service/add-on pricing is implemented

---

## Sprint 18: Services/add-ons + checkout total + localization

### Completed:

* introduced `service_addons` model
* added fields:

  * `family_slug`
  * `package_code`
  * `service_type`
* seeded consultation add-ons:

  * RU (RUB)
  * INT (EUR)
* implemented `ServiceAddonRepository`
* integrated add-on into checkout route
* implemented total calculation:

  * product + optional consultation
* added currency mismatch guard in checkout
* implemented Jinja `money` filter

  * RU: `7 400,00`
  * EN: `7,400.00`
* passed `lang` from request to templates
* applied localization-aware formatting in UI
* updated checkout template:

  * separate product price
  * separate consultation price
  * correct total
* added tests:

  * checkout with add-on
  * currency mismatch guard
* seeded INT Standard product via migration
* improved buy page UX:

  * added RU/INT explanation (language + payment)
  * introduced recommended badge (INT)

### Architecture decisions:

* services/add-ons are separate from products
* pricing always comes from DB, never from UI/query params
* UI language and product package remain independent
* formatting is handled in templates, not backend
* currency mixing is explicitly forbidden at runtime

---

## Sprint 19: Purchase flow + checkout UI/CSS polish

### Completed:

* created dedicated `product_buy.css`
* redesigned `/products/{family_slug}/buy` into responsive product cards
* implemented responsive 2-column → 1-column layout
* improved:

  * spacing
  * typography
  * CTA hierarchy
  * card structure
* replaced inline JavaScript in templates with structured event-based logic
* added consultation checkbox UX improvements
* implemented localization-aware recommended product logic:

  * RU interface → RU package recommended
  * EN interface → INT package recommended
* fixed language propagation issue on `product_buy`

  * added `lang` to template context
* updated language switch UX:

  * navigation now displays current language instead of target language
* improved mobile/tablet responsiveness for:

  * product cards
  * hero typography
  * CTA buttons
  * checkout summary block
  * payment buttons
* added adaptive breakpoints for:

  * tablets
  * large phones
  * compact phones
* stabilized product card height alignment for 2-column layouts
* improved ultra-mobile behavior (~320px width)
* aligned checkout visual style with product-buy page

### Architecture / UX decisions:

* avoid inline JavaScript in templates where possible
* UI language and recommended package are related UX concepts
* mobile-first responsive polish is required even for MVP purchase flow
* compact/mobile layouts should prefer readability over strict two-column preservation
* checkout and product-buy pages should share a unified visual style

---

## Sprint 20 checkpoint: consultation flow architecture clarified

### Context restored

During Sprint 20 planning, the logical connection between the purchase flow, consultation flow, and future sales architecture was clarified.

The current product flow is:

* `/products` — public product catalog
* `/products/smartbudget` — SmartBudget landing page
* `/products/smartbudget/buy` — SmartBudget SKU/package selection page
* `/checkout/{product_slug}` — checkout page for the selected SKU

The landing page should remain a product explanation page, not a price list.
Product prices belong on the buy/selection page, because SmartBudget may have multiple SKUs:

* RU Standard
* INT Standard
* RU Pro later
* INT Pro later
* possible future editions/packages

### Final UX decision

SmartBudget landing page must provide two separate user paths:

1. Buy SmartBudget

   * user goes to `/products/smartbudget/buy`
   * selects exact SKU/package/version
   * may optionally add a setup consultation
   * add-on consultation price must be visible before checkout
   * checkout confirms product price, consultation price, and total

2. Book standalone consultation

   * user goes to a separate consultation page
   * user sees standalone consultation price and terms
   * user pays for consultation
   * Calendly booking is shown only after successful payment

### Important UX rule

Consultation price must never appear for the first time only on checkout.

The discounted consultation add-on price must be visible on the buy page next to the checkbox, for example:

* `Add 1:1 SmartBudget setup consultation + 35 EUR`
* `Добавить личную консультацию по настройке SmartBudget + 3 500 RUB`

Checkout should only confirm the selected items and total amount.

### Calendly decision

Calendly must be available only after successful payment.

Reason:

* do not allow unpaid booking of limited consultation slots
* keep consultation capacity protected
* avoid manual cleanup of unpaid bookings

---

### Consultation notification flow note

Consultation flow has two separate business events:

1. consultation purchased
2. consultation slot booked in Calendly

These events must not be treated as the same thing.

Example:

* customer may purchase consultation
* but postpone Calendly booking
* or never complete booking

Purchased consultation does not automatically mean booked consultation.

For MVP:

* booking responsibility belongs to the customer
* customer receives booking access immediately after payment
* consultation may remain unused if no slot is selected

### Calendly access flow

After successful payment:

* user is redirected to success page
* success page contains Calendly booking button/link
* purchase confirmation email also contains the same Calendly link

Reason:

* user may close browser without booking immediately
* confirmation email acts as fallback access to booking flow

### Important MVP rule

Calendly link should not be generated later manually.

The same booking link should be:

* shown immediately after payment
* included in confirmation email

### Calendly single-use booking link rule

Consultation booking must use a single-use Calendly link, not a public reusable booking link.

Reason:

* each paid consultation item gives access to exactly one booking slot
* discounted add-on consultation must not allow repeated bookings
* standalone consultation must also allow only one booking per paid consultation item

MVP rule:

* after successful payment, customer receives one single-use Calendly link
* the same single-use link is shown on success page
* the same single-use link is included in purchase confirmation email
* after one successful Calendly booking, the link expires and cannot be reused

This applies to both:

* SmartBudget consultation add-on
* standalone consultation purchase

Future implementation note:

* generate/store one Calendly single-use link per paid consultation sale item
* store it on the sale item or future consultation booking record
* later use Calendly webhook to store scheduled/completed booking status

### Calendly link separation rule

Add-on consultation and standalone consultation must use separate booking links.

Reason:

* add-on consultation has discounted price
* standalone consultation has higher standalone price
* public users must not access discounted add-on booking flow without buying SmartBudget

MVP rule:

* add-on Calendly link is shown only after successful SmartBudget purchase with consultation add-on
* standalone Calendly link is shown only after successful standalone consultation purchase
* SmartBudget landing page must not expose add-on Calendly link directly

### MVP approach

For MVP:

* rely on native Calendly email notifications
* admin receives booking email immediately after user selects a slot

This avoids premature webhook/integration complexity.

### Future architecture direction

Later implement:

Calendly webhook
→ backend endpoint
→ consultation booking record
→ Telegram notification

Possible future endpoint:

`/v1/webhooks/calendly`

Possible future Telegram notification example:

```text
New consultation booked:
Client: ...
Package: SmartBudget INT
Consultation type: add-on
Time: ...
Calendly booking URL: ...
```

### Important business rule

`admin_sales` and consultation scheduling are different concerns.

`admin_sales` tracks:

* purchases/payments

Calendly tracks:

* actual booked consultation slots

## Consultation architecture design note

### Current state

`ServiceAddon` already exists and is used by checkout.

Current fields include:

* `code`
* `name`
* `service_type`
* `family_slug`
* `package_code`
* `currency_code`
* `amount`
* `is_active`

Current repository lookup uses:

* `family_slug`
* `package_code`
* `service_type`

This is no longer sufficient because the same service type can be sold in different usage scenarios.

Example:

* consultation as discounted SmartBudget add-on
* consultation as standalone service with higher standalone price

### Decision

Add `usage_type` to `service_addons`.

Allowed MVP values:

* `addon`
* `standalone`

Example records:

* `consultation_1h_ru_addon`
  * `service_type = consultation`
  * `usage_type = addon`
  * `family_slug = smartbudget`
  * `package_code = RU`
  * `currency_code = RUB`
  * `discounted add-on price`

* `consultation_1h_ru_standalone`
  * `service_type = consultation`
  * `usage_type = standalone`
  * `family_slug = smartbudget`
  * `package_code = RU`
  * `currency_code = RUB`
  * `standalone consultation price`

* `consultation_1h_int_addon`
  * `service_type = consultation`
  * `usage_type = addon`
  * `family_slug = smartbudget`
  * `package_code = INT`
  * `currency_code = EUR`
  * `discounted add-on price`

* `consultation_1h_int_standalone`
  * `service_type = consultation`
  * `usage_type = standalone`
  * `family_slug = smartbudget`
  * `package_code = INT`
  * `currency_code = EUR`
  * `standalone consultation price`

### Why not use `addon_price` / `standalone_price` fields

Do not add separate price columns such as:

* `addon_price`
* `standalone_price`

Reason:

* this makes the table harder to extend
* each usage scenario should be an explicit offer/record
* future services may have more than two usage scenarios
* admin UI stays simpler when each row has exactly one price

### Repository rule

`ServiceAddonRepository.get_active_addon()` must be extended to filter by:

* `family_slug`
* `package_code`
* `service_type`
* `usage_type`

For SmartBudget checkout add-on usage:

* `service_type = consultation`
* `usage_type = addon`

For standalone consultation page:

* `service_type = consultation`
* `usage_type = standalone`

---

## Sprint 22 checkpoint: consultation usage_type stabilization

### Completed:

* added `usage_type` to `ServiceAddon`
* implemented DB migration with safe backfill strategy
* existing consultation add-ons are now migrated to:

  * `usage_type = addon`
* updated `ServiceAddonRepository.get_active_addon()` lookup:

  * `family_slug`
  * `package_code`
  * `service_type`
  * `usage_type`
* updated checkout route:

  * consultation in checkout is now explicitly resolved as:

    * `service_type = consultation`
    * `usage_type = addon`
* updated `/products/{family_slug}/buy` backend context:

  * route now builds `product_options`
  * each product card receives:

    * product
    * active product price
    * consultation add-on
* updated `product_buy.html`:

  * consultation special price is now visible before checkout
  * add-on price is shown directly inside product cards
  * unavailable add-ons are handled safely
* improved consultation add-on UX:

  * introduced "Special price with purchase" messaging
  * stabilized responsive behavior for consultation pricing block
  * protected monetary amount from bad line wrapping
* added/updated tests:

  * model tests
  * repository tests
  * checkout tests
* added regression coverage:

  * checkout must ignore `usage_type = standalone`
  * checkout must use only `usage_type = addon`

### Architecture decisions:

* `service_type` defines WHAT the service is:

  * consultation
  * onboarding
  * support

* `usage_type` defines HOW the service is sold:

  * addon
  * standalone

* checkout product flow must never implicitly load standalone consultation pricing
* consultation pricing must be visible before checkout begins
* `ProductsRepository` remains product-focused and does not resolve service/add-on logic

---

## Sprint 23: sale_items architecture foundation

### Problem with current architecture

Current sales architecture assumes:

* one sale = one product

This is no longer correct.

Examples:

* SmartBudget + consultation add-on
* standalone consultation purchase
* future multiple services/add-ons
* future bundles or multiple quantities

Current architecture cannot correctly represent:

* multiple purchased items
* item-level pricing
* item-level service tracking
* item-level Calendly links
* item-level webhook processing

This becomes especially important for:

* Paddle webhooks
* consultation fulfillment
* standalone services
* future refunds/partial refunds

---

## Target architecture

### `sales` = order header

`sales` should become an order-level entity.

Responsibilities:

* customer identity
* payment status
* provider transaction IDs
* total amount
* currency
* timestamps
* payment provider metadata

Example:

```text
Sale #1001
Customer: user@example.com
Currency: EUR
Total: 74 EUR
Status: paid
```

`sales` should NOT directly represent purchased business items anymore.

---

### New table: `sale_items`

Each purchased item must become a separate row.

Example:

```text
Sale #1001
 ├── SmartBudget INT Standard
 └── Consultation add-on
```

---

## Initial MVP item types

Allowed item types:

* `product`
* `service`

### Product item examples

* SmartBudget RU Standard
* SmartBudget INT Standard
* future Pro editions

### Service item examples

* consultation add-on
* standalone consultation
* future onboarding/support services

---

## Planned `sale_items` responsibilities

Each sale item should eventually support:

* independent pricing snapshot
* independent fulfillment state
* independent webhook linkage
* independent external metadata
* independent refundability

This is especially important for services.

Example:

* product may already be delivered
* consultation may still be unbooked

These are different lifecycle states.

---

## Important architecture rule

`products` and `service_addons` remain catalog/configuration entities.

`sale_items` are immutable purchase snapshots.

Reason:

Catalog pricing may change later.
Purchase history must remain historically accurate.

Example:

```text
Current consultation price:
79 EUR

Old sale item:
35 EUR
```

Sale item must preserve the historical purchased price.

---

## Future consultation flow implication

Calendly access should eventually belong to a specific `sale_item`, not to the entire sale.

Reason:

One order may later contain:

* multiple consultations
* multiple services
* future recurring services

Correct ownership level is:

```text
sale_item
```

not:

```text
sale
```

---

## Future Paddle webhook implication

Paddle webhook events should eventually resolve:

```text
provider transaction
→ sale
→ sale_items
```

instead of:

```text
provider transaction
→ product only
```

This architecture is required for:

* mixed carts
* add-ons
* standalone services
* future refunds
* future subscription-like services

---

## Migration strategy note

Do NOT immediately delete old `sales.product_id` logic.

Recommended migration approach:

1. introduce `sale_items`
2. backfill existing sales
3. temporarily support both architectures
4. migrate business logic gradually
5. remove old direct product linkage later

Reason:

This reduces migration risk and keeps rollback simpler.

---

## Consultation booking ownership model

### Architectural decision

Calendly is used only as:

* scheduling UI
* slot management provider
* calendar integration layer

Critical business rules MUST remain under SmartBudgetSite backend control.

The system MUST NOT rely on Calendly one-time links as the primary protection mechanism.

Reason:

* avoid vendor lock-in
* avoid dependency on Calendly pricing/features
* maintain full control over entitlement logic
* support future migration to another booking provider or custom scheduler

---

## Consultation entitlement flow

After successful purchase:

* backend creates consultation entitlement record
* generates secure UUID booking token
* sets expiration timestamp (currently: 14 days)

Example:

* status = "available"
* expires_at = now + 14 days

User receives a booking link similar to:

```text
/consultation/book/{token}
```

---

## Backend responsibilities

Before showing Calendly embed/page:

* validate token existence
* validate token is not expired
* validate token is not already used
* validate purchase entitlement exists

If validation fails:

* booking page must not be accessible
* user should see explanatory error message

---

## Booking finalization

Calendly webhook is used only to:

* confirm successful booking
* save Calendly event reference
* mark consultation entitlement as used/booked

Example status flow:

* available
* booked
* expired
* cancelled (future)

After successful booking:

* token becomes unusable
* repeated booking attempts must be blocked by backend

---

## Important business rule

Discounted add-on consultations purchased together with SmartBudget:

* are single-use
* are non-repeatable
* must not allow multiple bookings from the same entitlement

The backend must enforce this rule independently from Calendly capabilities.

---

## Future flexibility

This architecture intentionally separates:

* business ownership (SmartBudgetSite)
* scheduling provider (Calendly)

This allows future replacement of Calendly without rewriting consultation entitlement logic.

---

## Sprint 23 checkpoint: sale_items architecture foundation

### Completed:

* introduced `sale_items` table
* added `SaleItem` model
* implemented item-level constraints:

  * exactly one ownership reference
  * product/service type validation
  * positive quantity
  * non-negative amount
* added `Sale.items` relationship
* introduced itemized order architecture:

  * `Sale` = order header
  * `SaleItem` = purchased business entity
* implemented service-layer purchase creation helpers:

  * `create_product_sale`
  * `create_service_sale_item`
  * `create_standalone_service_sale`
* implemented:

  * standalone service sales
  * service-only sales
  * item-level pricing snapshots
* added:

  * `calculate_sale_total()`
* migrated `/v1/check-purchase` logic:

  * product ownership now resolved through `sale_items`
  * no longer depends on `sales.product_id`
* converted previous `xfail` service-only verification test into passing regression coverage
* introduced centralized constants:

  * `SaleItemType.PRODUCT`
  * `SaleItemType.SERVICE`
* added extensive model/service/repository regression coverage

### Transitional architecture state

`sales.product_id` still exists temporarily as a legacy compatibility field.

Current architecture:

```text
Sale
    ↓
SaleItems
    ├── Product item
    └── Service item
```

`SaleItem` is now the source of truth for purchase ownership.

### Important migration decision

Legacy `sales.product_id` must NOT be used for new business logic.

New code should resolve ownership through:

```text
Sale → SaleItems
```

The legacy field is kept only to support:

* incremental migration
* rollback safety
* compatibility with older flows/tests/admin logic

Future cleanup should eventually:

* fully remove `sales.product_id`
* fully derive totals from `sale_items`
* move all purchase logic to item-based ownership

---

## Sprint 24: consultation entitlement system design

### Core architecture decision

Consultation access must be represented by a backend-owned entitlement entity.

The entitlement is the source of truth for whether a customer may access the booking flow.

Calendly must not be treated as the owner of consultation access rights.

Correct ownership chain:

```text
Sale
  ↓
SaleItem
  ↓
ConsultationEntitlement
```

Incorrect ownership chain:

```text
Sale
  ↓
Calendly booking
```

Reason:

* a consultation can be purchased but not booked immediately
* an entitlement can expire without any Calendly event
* Calendly can be replaced later by another provider
* booking provider rules must not define SmartBudget business rules
* discounted add-on consultations must remain single-use even if provider-side links are reusable or misconfigured

---

### ConsultationEntitlement responsibility

`ConsultationEntitlement` represents customer access to one consultation booking right.

It is responsible for:

* linking consultation access to a specific purchased `SaleItem`
* storing backend-owned secure booking token
* storing token expiration timestamp
* storing current entitlement status
* blocking repeated booking attempts
* acting as the stable business object for future Calendly webhook processing

It is NOT responsible for:

* storing product catalog pricing
* replacing `SaleItem` as purchase snapshot
* acting as a generic sale/order entity
* rendering Calendly UI
* defining provider-specific webhook payload structure

---

### Relationship rules

MVP relationship:

```text
SaleItem (service/consultation) 1 → 0..1 ConsultationEntitlement
```

MVP rule:

* only paid consultation service items should receive an entitlement
* product-only sale items must not receive an entitlement
* entitlement belongs to `sale_item_id`, not directly to `sale_id`

Reason:

* consultation ownership exists at item level
* future orders may contain multiple service items
* future refunds or cancellations may affect one item without affecting the whole sale

Future-compatible direction:

```text
SaleItem (service/consultation) 1 → many ConsultationEntitlements
```

This may be useful later for:

* multi-session consultation packages
* onboarding bundles
* support packages

MVP should still implement one entitlement per consultation sale item unless requirements change.

---

### Booking token rules

Each entitlement receives a backend-generated UUID token.

Example public booking URL:

```text
/consultation/book/{token}
```

Token validation must happen before Calendly access is shown.

Validation rules:

* token exists
* entitlement status allows booking
* entitlement is not expired
* linked sale item exists
* linked sale/payment is valid for booking access

If validation fails:

* Calendly must not be shown
* user should see a clear explanatory page

Token must be single-use from the SmartBudget backend perspective.

Calendly one-time links may be used as an implementation detail later, but backend validation remains mandatory.

---

### Entitlement lifecycle

MVP statuses:

* `available`
* `booked`
* `expired`
* `cancelled`

Initial status after successful payment:

```text
available
```

Expected lifecycle:

```text
available → booked
available → expired
available → cancelled
booked → cancelled   (future/manual/admin scenario)
```

Status meaning:

* `available` — customer may access booking page if token is valid and not expired
* `booked` — consultation slot was successfully booked; token must no longer allow booking
* `expired` — booking window passed without successful booking
* `cancelled` — entitlement was manually or automatically cancelled; future behavior may depend on business rules

MVP rule:

* expired status may be derived dynamically from `expires_at`
* physical status update can be implemented later by scheduled job or admin action

---

### Expiration rule

Default MVP booking window:

```text
expires_at = created_at + 14 days
```

Business meaning:

* customer has 14 days after purchase to book a consultation slot
* after expiration, booking access is blocked

Important:

Expiration controls access to booking, not necessarily the consultation event date.

Example:

* customer buys consultation on May 1
* books a slot on May 10
* slot itself may happen on May 20
* this is valid because booking happened before entitlement expiration

---

### Calendly integration boundary

Calendly should be integrated after entitlement validation.

The booking page flow should be:

```text
User opens /consultation/book/{token}
  ↓
Backend validates entitlement
  ↓
If valid: show Calendly embed/link
  ↓
Calendly booking happens
  ↓
Calendly webhook confirms booking
  ↓
Backend marks entitlement as booked
```

Calendly webhook must not create entitlement.

Webhook should only update an existing entitlement that was already created after successful payment.

---

### Future webhook fields

The entitlement model should leave room for provider metadata, for example:

* booking_provider
* provider_event_uri
* provider_invitee_uri
* booked_at
* cancelled_at

Do not overbuild webhook handling in MVP.

First implementation should focus on:

* model/table
* token generation
* entitlement creation after consultation purchase
* token validation service

---

## Sprint 25 checkpoint: consultation booking lifecycle foundation

### Completed:

* implemented lifecycle transition service:

  * `mark_entitlement_as_booked()`
* implemented BOOKED transition rules:

  * only AVAILABLE entitlements may transition to BOOKED
  * BOOKED transition is idempotent
* added booking metadata fields to `ConsultationEntitlement`:

  * `booking_provider`
  * `provider_event_uri`
  * `provider_invitee_uri`
  * `booked_at`
* implemented provider booking metadata persistence
* added lifecycle regression coverage:

  * BOOKED happy path
  * idempotent repeated booking confirmation
  * EXPIRED entitlement rejection
  * CANCELLED entitlement rejection
* introduced reusable test helper:

  * `create_test_consultation_entitlement()`
* implemented provider reconciliation repository:

  * `ConsultationEntitlementRepository`
  * `get_by_provider_event_uri()`
* added repository regression coverage:

  * matching provider event lookup
  * unknown provider event returns None
* added unique partial index:

  * `uq_consultation_entitlements_provider_event_uri`
* enforced external reconciliation integrity:

```text
one provider event
    ↓
exactly one entitlement
```

### Architecture decisions:

* lifecycle transitions belong to service layer, not repositories
* booking confirmation must remain idempotent because webhook providers retry delivery
* provider metadata persistence is optional before booking and populated only after successful booking confirmation
* repository layer is responsible only for reconciliation lookup, not lifecycle decisions
* `provider_event_uri` acts as external reconciliation key
* partial unique index is required because NULL provider event URIs are valid before booking
* tests should validate business behavior rather than internal helper implementation details

### Current lifecycle state

```text
AVAILABLE
    ↓
BOOKED
```

Supported behaviors:

* AVAILABLE → BOOKED
* BOOKED → BOOKED (safe idempotent noop)
* EXPIRED → BOOKED (blocked)
* CANCELLED → BOOKED (blocked)

### Current webhook readiness state

The backend is now capable of:

```text
provider event
    ↓
reconciliation lookup
    ↓
entitlement resolution
    ↓
idempotent booking confirmation
```

provided that a valid reconciliation key is available.

Current implementation uses:

* `provider_event_uri`

This remains suitable for replay/idempotency handling after a booking has already been linked to an entitlement.

Real first-booking reconciliation strategy is still pending validation against actual Calendly webhook deliveries.

### Current limitation

* webhook endpoint not implemented yet
* provider signature verification not implemented yet
* Calendly payload normalization layer not implemented yet
* booking cancellation synchronization not implemented yet

### Clarification after Calendly API validation

The earlier assumption that `provider_event_uri` can be used as the first reconciliation key is incomplete.

`provider_event_uri` is suitable for replay/idempotency after a provider booking has already been linked to an entitlement, but it cannot resolve the first `invitee.created` webhook because the entitlement does not know the provider event URI before the Calendly booking exists.

Real first-booking reconciliation must be validated against an actual Calendly webhook payload after a public HTTPS endpoint is available.

Possible first reconciliation candidates:

* backend booking token passed into Calendly, if Calendly returns it in webhook payload
* invitee email, with additional safeguards
* another provider-supported tracking/custom field discovered from real payload

Until real payload validation is completed, `provider_event_uri` should be treated as a replay/idempotency key, not as a confirmed first-booking reconciliation key.

---

## Sprint 24 checkpoint: consultation entitlement MVP foundation

### Completed:

* added `ConsultationEntitlement` model
* added Alembic migration for `consultation_entitlements`
* implemented entitlement statuses:

  * `available`
  * `booked`
  * `expired`
  * `cancelled`
* added secure UUID booking token generation
* implemented relationship chain:

```text
Sale
  ↓
SaleItem
  ↓
ConsultationEntitlement
```

* implemented service-layer entitlement creation:

  * `create_consultation_entitlement()`
* implemented token validation service:

  * `get_valid_consultation_entitlement_by_token()`
* implemented protected booking route:

  * `/consultation/book/{booking_token}`
* added placeholder booking page:

  * `consultation_booking.html`
* implemented backend-controlled entitlement validation before booking access
* added timezone normalization helper:

  * `_ensure_utc_aware()`
* stabilized SQLite/PostgreSQL datetime comparison behavior
* implemented extensive regression coverage:

  * entitlement creation happy path
  * reject product sale items
  * reject duplicate entitlement creation
  * valid token lookup
  * unknown token rejection
  * expired token rejection
  * booking route access with valid token

### Architecture decisions:

* entitlement creation belongs to service layer, not ORM model defaults
* low-level services use `flush()` instead of `commit()`
* transaction boundaries remain controlled by higher-level orchestration flow
* booking routes remain thin and delegate validation to service layer
* Calendly integration remains postponed until entitlement foundation is stable
* backend entitlement validation is mandatory even if Calendly later supports one-time booking links

### Current booking flow

```text
Purchase successful
  ↓
Create ConsultationEntitlement
  ↓
User opens:
/consultation/book/{token}
  ↓
Backend validates entitlement
  ↓
If valid → booking UI/provider access allowed
```

### Current limitation

* Calendly embed/webhook integration not implemented yet
* booked/cancelled status transitions still pending
* booking confirmation lifecycle not implemented yet

---

## Sprint 25: consultation booking lifecycle foundation

### Architectural direction

Sprint 25 begins transition from:

```text
entitlement validation only
```

into:

```text
full consultation booking lifecycle
```

The system must now support:

* successful booking confirmation
* irreversible booking ownership transition
* provider metadata persistence
* repeated booking prevention
* future webhook-driven synchronization

---

### Core lifecycle rule

`ConsultationEntitlement` remains the backend-owned source of truth.

Booking providers (Calendly initially) may confirm bookings,
but they must not define whether the consultation is considered booked.

Correct authority:

```text
ConsultationEntitlement.status
```

not:

```text
provider booking existence
```

Reason:

* provider webhook delivery may fail
* provider events may later be deleted/cancelled
* providers may be replaced
* business ownership must remain internal

---

### Booked transition rule

A consultation becomes booked only after backend confirmation.

Expected future flow:

```text
available entitlement
  ↓
customer books slot in Calendly
  ↓
Calendly webhook received
  ↓
backend validates webhook
  ↓
backend updates entitlement
  ↓
status = booked
```

After successful transition to `booked`:

* booking token becomes unusable
* booking page access must be blocked
* repeated booking attempts must fail

---

### Planned booking metadata

`ConsultationEntitlement` should support provider-related metadata.

Planned MVP-compatible fields:

* `booking_provider`
* `provider_event_uri`
* `provider_invitee_uri`
* `booked_at`

Purpose:

* connect backend entitlement to provider booking
* support future admin visibility
* support debugging/webhook reconciliation
* support future cancellation flows

Important:

Provider metadata must remain optional.

Reason:

* entitlement may exist before booking
* webhook may fail temporarily
* provider integration should not block entitlement creation

---

### Important transition rule

Booking confirmation logic must be idempotent.

Example:

If Calendly retries the same webhook multiple times:

* backend must not create duplicate transitions
* backend must not raise inconsistent state errors
* backend should safely ignore already-booked entitlements

This is especially important because webhook providers commonly retry delivery.

---

### Important architecture boundary

Webhook handlers should remain thin.

Recommended flow:

```text
Webhook route
  ↓
Webhook service
  ↓
Consultation entitlement service
  ↓
Repository/DB
```

Webhook route responsibilities:

* validate provider signature
* parse payload
* call service

Business rules must remain inside services.

---

### Sprint 25 implementation priorities

1. booked status transition service
2. booking confirmation persistence
3. repeated booking prevention
4. provider metadata model design
5. webhook-ready service boundary

---

## Sprint 26: webhook integration boundary design

### Core architectural goal

Webhook processing must remain:

* provider-agnostic
* idempotent
* replay-safe
* isolated from HTTP transport details

Calendly-specific payloads and signature formats must not leak into business lifecycle services.

The webhook layer acts as a translation/reconciliation boundary between:

```text
external provider world
    ↓
normalized internal webhook event
    ↓
business lifecycle services
```

---

### Recommended webhook flow

Target flow:

```text
Calendly webhook request
    ↓
signature verification
    ↓
provider payload normalization
    ↓
normalized webhook event
    ↓
reconciliation lookup
    ↓
entitlement resolution
    ↓
idempotent lifecycle transition
```

Important:

The webhook route itself must remain thin.

---

### Webhook route responsibilities

Recommended route:

```text
/v1/webhooks/calendly
```

Route responsibilities only:

* receive raw provider payload
* receive provider headers/signature
* call signature verification service
* call payload normalization service
* delegate orchestration to webhook service
* return safe HTTP response

The route must NOT:

* contain lifecycle logic
* directly mutate entitlement status
* directly access repositories
* parse Calendly payload structure inline

---

### Signature verification abstraction

Provider signature verification must be isolated behind a dedicated abstraction.

Reason:

* providers use different signature schemes
* providers retry delivery
* verification rules evolve
* future providers may be added later

Recommended boundary:

```text
app/services/webhooks/signature_verification_service.py
```

Recommended direction:

```python
verify_webhook_signature(
    provider: str,
    payload: bytes,
    headers: Mapping[str, str],
) -> bool
```

Important:

Business services should never know anything about provider signature formats.

---

### Payload normalization layer

Provider payload normalization must convert external provider payloads into stable internal events.

Reason:

* external payloads are unstable
* providers evolve schemas
* internal lifecycle services should not depend on provider JSON structure
* future provider replacement becomes easier

Recommended boundary:

```text
app/services/webhooks/payload_normalizers/
```

Possible future implementation:

```text
calendly_payload_normalizer.py
```

Normalization target example:

```python
NormalizedBookingConfirmedEvent(
    provider="calendly",
    provider_event_uri="...",
    provider_invitee_uri="...",
    occurred_at=...,
)
```

Important:

Lifecycle services should consume normalized internal events, not raw Calendly payloads.

---

### Reconciliation rule

Webhook reconciliation must use a stable identifier that can connect a Calendly booking to an existing consultation entitlement.

The final first-booking reconciliation key is not yet confirmed.

Current understanding:

* `provider_event_uri` is suitable for replay/idempotency after a booking has already been linked to an entitlement
* `provider_event_uri` is not sufficient for resolving the first `invitee.created` webhook because the entitlement does not know this value before the Calendly booking exists
* real first-booking reconciliation must be validated against actual Calendly webhook payloads

Possible future reconciliation candidates include:

* backend booking token returned by Calendly
* invitee email with additional safeguards
* another provider-supported tracking field discovered during live webhook validation

Until real webhook payload validation is completed, first-booking reconciliation should be treated as an open integration question rather than a finalized architecture decision.

If no entitlement exists:

* webhook must NOT create entitlement automatically
* webhook should be safely rejected/logged

Reason:

Entitlements originate only from successful purchases.

Webhook events must update existing business ownership, not create it.

---

### Duplicate webhook delivery handling

Webhook providers retry aggressively.

Therefore:

* webhook processing must be replay-safe
* lifecycle transitions must remain idempotent
* repeated deliveries must not create inconsistent state

Expected behavior:

```text
BOOKED entitlement
    ↓
repeated booking webhook
    ↓
safe noop
```

This rule already aligns with current lifecycle implementation:

```text
BOOKED → BOOKED
```

---

### Important failure-handling rule

Signature verification failure:

* reject request immediately
* do not process payload

Normalization failure:

* reject request
* log payload safely

Unknown provider event:

* do not create entitlement
* return safe handled response
* keep webhook idempotent

Important:

Webhook failures must never corrupt entitlement lifecycle state.

---

### Architectural direction for Sprint 26

Sprint 26 should focus on:

1. webhook boundary architecture
2. signature verification abstraction
3. provider payload normalization
4. orchestration service structure
5. replay-safe webhook flow
6. clean separation between:

```text
transport layer
provider integration layer
business lifecycle layer
```

---

## Sprint 26 checkpoint: webhook integration boundary foundation

### Completed:

* added dedicated webhook router:

  * `/v1/webhooks/calendly`
* implemented thin webhook route boundary
* introduced provider-agnostic normalized webhook schema:

  * `NormalizedBookingConfirmedEvent`
* implemented Calendly payload normalizer:

  * `normalize_calendly_invitee_created_event()`
* added malformed payload regression coverage
* implemented webhook orchestration service:

  * `process_calendly_webhook()`
* introduced event routing layer:

  * supported:

    * `invitee.created`
  * unsupported events safely ignored
* implemented signature verification abstraction:

  * `verify_webhook_signature()`
* integrated verification into webhook request pipeline
* added route/service regression coverage:

  * webhook endpoint acceptance
  * invalid signature rejection
  * supported event routing
  * unsupported event handling
  * payload normalization
  * malformed provider payload rejection
  * provider verification handling

### Architecture decisions:

* webhook routes must remain thin integration boundaries
* provider payloads must never leak directly into lifecycle services
* normalization layer acts as anti-corruption boundary
* orchestration layer owns provider event routing
* unsupported provider events must fail safely
* signature verification is infrastructure concern, not business concern
* webhook request pipeline must reject invalid signatures before normalization or lifecycle processing
* provider-specific JSON structure must remain isolated inside payload normalizers
* replay-safe/idempotent architecture preparation begins before live provider integration

### Current webhook request pipeline

```text
HTTP webhook
    ↓
signature verification
    ↓
webhook orchestration service
    ↓
event routing
    ↓
payload normalizer
    ↓
provider-agnostic internal event
```

### Current limitation

* reconciliation orchestration not implemented yet
* entitlement lookup not integrated yet
* lifecycle transition orchestration not integrated yet
* duplicate delivery replay handling not fully integrated yet
* real Calendly signature verification not implemented yet
* live Calendly webhook payload testing not implemented yet
* webhook audit logging not implemented yet

---

## Sprint 28 checkpoint: Calendly live integration hardening

### Completed:

* implemented real Calendly HMAC signature verification

  * cryptographic verification using:

    * timestamp
    * raw payload bytes
    * HMAC SHA256

* replaced placeholder/fail-open verification behavior:

  * unsigned requests are now rejected
  * invalid signatures are rejected
  * unknown providers fail closed

* introduced Calendly signature parsing helpers:

  * `_verify_calendly_signature()`
  * `_parse_calendly_signature_header()`

* implemented route-level signature enforcement:

  * webhook processing now blocked before orchestration on invalid signature

* added fixture-based webhook payload testing:

  * `tests/fixtures/calendly/invitee_created_real_sample.json`

* hardened Calendly payload normalization:

  * supports both:

    * object URI payload shape
    * direct string URI payload shape

* introduced reusable URI extraction helper:

  * `_extract_uri()`

* implemented centralized webhook observability boundary:

  * `webhook_audit_logger.py`
  * `log_webhook_event()`

* integrated audit logging into successful webhook processing flow

* added extensive regression coverage:

  * missing signature rejection
  * unsupported provider rejection
  * valid HMAC acceptance
  * invalid HMAC rejection
  * route-level unsigned request rejection
  * orchestration not called on failed verification
  * dual-shape payload normalization
  * fixture-based payload normalization
  * webhook audit logging invocation
  * consolidated webhook pipeline verification

### Architecture decisions:

* webhook verification must fail closed
* provider verification belongs to infrastructure layer, not business lifecycle services
* webhook signature verification must use raw payload bytes
* payload normalization layer must tolerate provider payload shape variations
* observability must remain centralized and separated from orchestration logic
* webhook processing audit logs must not contain signing secrets
* successful webhook processing should emit structured audit events
* integration-style tests should use realistic provider payloads and signatures

### Current webhook request pipeline

```text
HTTP webhook
    ↓
real HMAC signature verification
    ↓
webhook orchestration service
    ↓
event routing
    ↓
payload normalization
    ↓
provider-agnostic internal event
    ↓
reconciliation orchestration
    ↓
repository lookup by provider_event_uri
    ↓
entitlement resolution
    ↓
idempotent lifecycle transition
    ↓
BOOKED entitlement state
    ↓
centralized audit logging
```

### Current limitation

* malformed signature header hardening not fully implemented yet
* malformed payload observability not implemented yet
* webhook rejection audit logging not implemented yet
* unsupported-event observability not implemented yet
* reconciliation mismatch audit logging not implemented yet
* cancellation synchronization not implemented yet
* admin visibility for consultation booking state not implemented yet

---

## Sprint 27 checkpoint: webhook reconciliation + lifecycle synchronization

### Completed:

* introduced webhook reconciliation orchestration boundary:

  * `app/services/webhooks/reconciliation_service.py`
  * `reconcile_booking_confirmed_event()`

* integrated repository-based entitlement lookup into webhook processing:

  * normalized provider event
  * provider event URI
  * existing consultation entitlement resolution

* updated Calendly webhook orchestration service:

  * `process_calendly_webhook(db, payload)`
  * now receives DB session explicitly
  * coordinates normalization, reconciliation, and lifecycle handoff

* updated Calendly webhook route wiring:

  * route receives `db: Session = Depends(get_db)`
  * route remains thin
  * route delegates processing to orchestration service

* implemented safe missing-entitlement handling:

  * webhook events must not create entitlements
  * unknown provider events are normalized and handled safely
  * missing reconciliation target does not corrupt lifecycle state

* integrated lifecycle synchronization:

  * successful reconciliation now calls `mark_entitlement_as_booked()`
  * lifecycle mutation remains centralized in consultation entitlement service
  * orchestration layer coordinates but does not own transition rules

* implemented replay-safe webhook behavior:

  * duplicate webhook delivery is idempotent
  * repeated `invitee.created` event keeps entitlement in `BOOKED`
  * duplicate provider delivery does not create inconsistent state

* added/updated regression coverage:

  * reconciliation lookup resolves existing entitlement
  * webhook service calls reconciliation layer
  * missing entitlement is handled safely
  * webhook orchestration marks entitlement as booked
  * duplicate webhook replay remains idempotent
  * route wiring passes DB session into webhook service

### Architecture decisions:

* webhook orchestration owns coordination, not business lifecycle rules
* repository layer performs lookup only and must not mutate lifecycle state
* lifecycle transitions remain inside `consultation_entitlement_service`
* webhook events must never create consultation entitlements
* provider webhook delivery must be treated as replayable and unreliable
* `provider_event_uri` remains the reconciliation key for Calendly booking confirmation
* route-level transaction boundary is acceptable for MVP; explicit audit/transaction hardening can be added later
* normalized internal webhook events are the contract between provider integration and business lifecycle logic

### Current webhook synchronization flow

```text
HTTP webhook
    ↓
signature verification
    ↓
webhook orchestration service
    ↓
event routing
    ↓
payload normalization
    ↓
provider-agnostic internal event
    ↓
reconciliation orchestration
    ↓
repository lookup by provider_event_uri
    ↓
entitlement resolution
    ↓
idempotent lifecycle transition
    ↓
BOOKED entitlement state
```

### Current limitation

* real Calendly signature verification is still placeholder/abstracted
* live Calendly payload testing not implemented yet
* webhook audit logging not implemented yet
* cancellation synchronization not implemented yet
* admin visibility for consultation booking state not implemented yet

---

## Next sprint priorities (after Sprint 28)

### 1. Webhook resilience + rejection hardening

* malformed Calendly signature header handling
* malformed payload rejection hardening
* unsupported event observability
* reconciliation mismatch audit logging
* webhook rejection audit logging
* retry/replay diagnostics preparation
* structured failure-path observability

### 2. Calendly live integration validation

* validate live Calendly webhook delivery in development/staging
* verify real production payload shape
* validate real signing secret configuration flow
* confirm provider event URI consistency
* validate replay behavior from real provider delivery

### 3. Consultation admin visibility

* show consultation entitlement status in admin UI
* display sale item, customer email, booking status, provider event URI, invitee URI, and booked_at
* add filtering for available/booked/expired/cancelled consultations

### 4. Calendly booking UI integration

* add Calendly embed/button after successful entitlement validation
* keep backend entitlement validation before provider access
* prevent showing booking UI for booked/expired/cancelled entitlements

### 5. Merchant of Record integration (Paddle)

* create Paddle account
* configure products and prices
* implement checkout redirect
* define success URL
* plan Paddle webhook handling

### 6. Sales tracking (admin)

* sales list
* filtering
* show product/service sale items
* show consultation presence and lifecycle state

### 7. Deployment preparation

* connect domain
* choose hosting (VPS / PaaS)
* prepare environment variables
* basic production setup

---

## Sprint 29 checkpoint: webhook resilience + rejection hardening

### Completed:

* implemented malformed Calendly signature header rejection hardening

  * malformed signature headers now fail closed
  * malformed signature parsing safely rejects webhook requests

* implemented webhook rejection audit logging

  * invalid signature rejection now emits structured audit event
  * route-level rejection observability added

* implemented unsupported-event observability

  * unsupported provider events are now logged with:

    * `status = ignored`

* implemented reconciliation mismatch audit logging

  * valid normalized webhook events without matching entitlement now emit:

    * `status = reconciliation_mismatch`

* implemented malformed payload observability

  * malformed supported provider payloads now emit:

    * `status = malformed_payload`

  before exception propagation

* implemented route-level malformed JSON observability

  * malformed JSON requests are now:

    * logged
    * rejected with HTTP 400

* introduced centralized webhook audit status constants:

  * `webhook_audit_statuses.py`

* migrated route-level and service-level webhook audit statuses to centralized constants

* added/updated regression coverage:

  * malformed signature header rejection
  * rejection audit logging
  * unsupported-event observability
  * reconciliation mismatch logging
  * malformed provider payload logging
  * malformed JSON rejection logging
  * centralized audit status integration stability

### Architecture decisions:

* failure-path observability is now considered part of webhook infrastructure architecture
* malformed provider payloads must remain visible operationally even when request processing fails
* malformed JSON rejection belongs to route-level transport boundary, not orchestration layer
* unsupported provider events must fail safely and remain observable
* reconciliation mismatches are operational integration events, not business lifecycle failures
* audit status values should remain centralized to avoid semantic drift and typo-based inconsistencies
* webhook observability must remain structured, provider-aware, and independent from lifecycle business logic
* webhook processing should remain fail-closed while still preserving diagnostics visibility

### Updated webhook request pipeline

```text
HTTP webhook
    ↓
real HMAC signature verification
    ↓
rejection audit logging
    ↓
malformed JSON protection
    ↓
webhook orchestration service
    ↓
event routing
    ↓
unsupported-event observability
    ↓
payload normalization
    ↓
malformed payload observability
    ↓
provider-agnostic internal event
    ↓
reconciliation orchestration
    ↓
repository lookup by provider_event_uri
    ↓
reconciliation mismatch observability
    ↓
entitlement resolution
    ↓
idempotent lifecycle transition
    ↓
BOOKED entitlement state
    ↓
centralized audit logging
```

### Current limitation

* retry/replay diagnostics not implemented yet
* webhook delivery attempt correlation not implemented yet
* provider timestamp freshness validation not implemented yet
* cancellation synchronization not implemented yet
* admin visibility for consultation booking state not implemented yet
* structured audit persistence/storage not implemented yet
* webhook metrics/monitoring integration not implemented yet

---

## Next sprint priorities (after Sprint 29)

### Architectural direction change

Webhook infrastructure is now considered production-safe enough for MVP.

Future webhook hardening remains important, but it is no longer the primary delivery focus.

The project priority now shifts back toward:

* user-facing booking flow
* real end-to-end consultation experience
* admin visibility
* payment integration
* deployment preparation

The goal is to avoid endless infrastructure polishing before real product validation.

---

### 1. Calendly booking UI integration

* add Calendly embed/button after successful entitlement validation
* keep backend entitlement validation before provider access
* prevent showing booking UI for booked/expired/cancelled entitlements
* validate first end-to-end consultation booking flow

### 2. Consultation admin visibility

* show consultation entitlement status in admin UI
* display:

  * sale item
  * customer email
  * booking status
  * provider event URI
  * invitee URI
  * booked_at
* add filtering for:

  * available
  * booked
  * expired
  * cancelled

### 3. Calendly live integration validation

* validate live Calendly webhook delivery in development/staging
* verify real production payload shape
* validate real signing secret configuration flow
* confirm provider event URI consistency
* validate replay behavior from real provider delivery

### 4. Deployment preparation

* connect domain
* choose hosting (VPS / PaaS)
* prepare environment variables
* basic production setup

### 5. Merchant of Record integration (Paddle)

* create Paddle account
* configure products and prices
* implement checkout redirect
* define success URL
* plan Paddle webhook handling

### 6. Sales tracking (admin)

* sales list
* filtering
* show product/service sale items
* show consultation presence and lifecycle state

### Founder operational analytics MVP

Admin dashboard should eventually provide lightweight operational analytics suitable for a solo founder.

The goal is operational visibility, not full BI infrastructure.

Planned MVP visibility includes:

* total sales count
* revenue overview
* consultation booking count
* active vs booked consultation state
* recent purchases
* recent customer activity

Important limitation:

The project intentionally avoids premature analytics complexity such as:

* advanced BI dashboards
* cohort analysis
* attribution systems
* retention analytics
* complex reporting infrastructure

Operational clarity is prioritized over analytical sophistication during MVP stage.

---

## Future webhook operational hardening

The following items remain intentionally postponed until after the first real end-to-end integration validation:

* provider timestamp freshness validation
* replay-window validation
* webhook delivery correlation diagnostics
* structured replay/retry observability
* duplicate delivery diagnostics enrichment
* webhook metrics/monitoring integration
* structured audit persistence/storage

---

## Sprint 30 checkpoint: booking flow MVP + consultation admin visibility

### Completed

#### Calendly booking page MVP integration

* added backend-controlled consultation booking page:

  * `/consultation/book/{booking_token}`

* implemented backend-owned entitlement validation before provider access

* booking page now renders only after successful entitlement validation

* added config-driven Calendly integration:

  * `CALENDLY_CONSULTATION_URL`

* `CALENDLY_CONSULTATION_URL` currently remains in `.env` for local/dev booking flow validation

* development/staging booking URLs are intentionally environment-driven

* production Calendly URL must remain deployment-configured and must not be hardcoded in application source code

* provider access URLs are treated as infrastructure configuration, not business logic

* added booking button integration:

  * provider access remains controlled by backend validation
  * Calendly URL injected via config
  * provider logic remains outside business lifecycle layer

* implemented safe provider misconfiguration fallback UX:

  * if Calendly URL is missing, user sees deterministic fallback message
  * avoids silent broken booking state

---

#### Booking page UX improvements

* migrated booking page texts to i18n system

* added localized booking flow keys:

  * `consultation_booking_title`
  * `consultation_booking_intro`
  * `consultation_booking_status`
  * `consultation_booking_expires_at`
  * `consultation_book_button`
  * `consultation_booking_unavailable`

* added masked diagnostic booking reference:

  * `masked_token`
  * displayed as short support/debug reference
  * avoids leaking full booking token

---

#### Booking flow hardening

* implemented BOOKED-specific rejection message:

  * `"This consultation has already been booked."`

* preserved generic rejection for other invalid states

* added regression coverage for:

  * booking page rendering
  * Calendly URL injection
  * booking button rendering
  * masked token rendering
  * prevention of full token leakage
  * BOOKED entitlement rejection messaging
  * booking fallback UX

---

#### Consultation admin visibility foundation

* added repository query:

  * `get_all_with_sale_data`

* added admin service boundary:

  * `get_consultation_entitlements`

* added admin consultations route:

  * `/admin/consultations`

* added first admin consultations template:

  * `admin_consultations.html`

* implemented first operational consultation visibility table

* added responsive-safe admin table wrapper

* added admin consultation table styling:

  * readable spacing
  * row separation
  * responsive horizontal overflow handling

* created first real development consultation entitlement generator:

  * `scripts/create_dev_consultation_entitlement.py`

* validated real end-to-end admin visibility flow using live dev data

---

### Architecture decisions

* booking provider access must remain backend-controlled
* provider URLs must remain config-driven
* booking lifecycle ownership remains inside SmartBudgetSite backend
* booking page UX must remain deterministic even under provider misconfiguration
* support diagnostics should expose masked references only
* admin consultation visibility is operational infrastructure, not customer-facing UI
* operational admin pages should prioritize readability and support workflows over visual polish
* development operational tooling belongs in `/scripts`, not inside `/app`

---

## Founder-oriented MVP strategy

SmartBudgetSite is intentionally being developed as a founder-operated MVP platform.

Primary goal of the current phase is NOT to build a fully-featured SaaS platform before launch.

Primary goal is to build a stable operational product system that:

* supports independent product sales
* supports consultation booking lifecycle
* minimizes manual operational overhead
* provides sufficient operational visibility for a solo founder
* allows long post-launch focus on SmartBudget product evolution itself

The platform should remain:

* operationally sustainable
* understandable by one developer
* maintainable without full-time backend work

The current roadmap intentionally prioritizes:

* operational clarity
* automation
* sales/support visibility
* deployment readiness
* stable purchase + delivery lifecycle

over:

* advanced SaaS features
* complex account systems
* enterprise admin tooling
* premature scalability abstractions

Important strategic direction:

After MVP launch, project focus is expected to temporarily shift toward:

* SmartBudget product improvements
* customer feedback collection
* English improvement
* LinkedIn/GitHub positioning
* international market preparation

Further large-scale website/platform expansion should happen only after real market validation or meaningful recurring revenue.

## Sprint 31: Consultation admin usability improvements

### Goal

Improve operational visibility for consultation booking lifecycle administration.

### Implemented

#### Consultation admin page improvements

* Added customer email column.
* Added booked_at column.
* Added status badges for:

  * available
  * booked
  * expired
  * cancelled
* Improved datetime formatting for admin readability.
* Added result count indicator.
* Added status filtering (All / Available / Booked / Expired / Cancelled).
* Added clickable provider links:

  * provider_event_uri
  * provider_invitee_uri

#### Backend improvements

* Moved consultation status filtering from route layer into service layer.
* Preserved repository ordering by created_at DESC.
* Continued eager loading of SaleItem → Sale relationships to avoid N+1 queries.

#### Admin routing hardening

* Fixed consultation admin page to use admin_router protection.
* Moved router.include_router(admin_router) to end of route registration section to prevent future route registration mistakes.

### Current status

Consultation admin usability improvements are considered complete for MVP.

### Remaining priorities

1. Admin operational hardening
2. Real Calendly integration validation
3. Consultation admin operational visibility enhancements as real booking data appears

## Sprint 32 checkpoint: Calendly webhook secret ownership hardening

### Completed

* added `CALENDLY_WEBHOOK_SIGNING_SECRET` to application settings
* stopped reading Calendly webhook signing secret from request headers
* moved Calendly webhook signature verification to server-owned configuration
* updated webhook route and service tests to use configured signing secret
* standardized admin token setting usage as `settings.ADMIN_TOKEN`
* updated admin route tests to use authenticated test client fixture
* removed obsolete public feedback admin API endpoints:

  * /v1/feedback/admin
  * /v1/feedback/admin/{feedback_id}

* consolidated feedback administration behind protected admin routes only

### Architecture decisions

* webhook signing secrets must be owned by the backend configuration, not by incoming requests
* webhook request headers may contain signatures, but must never provide verification secrets
* admin tests should use a shared authenticated client fixture for protected routes
* anonymous admin access tests should continue using the plain test client

### Current status

Calendly webhook signature verification is now suitable for real provider validation.

---

### Admin authentication review outcome

* current ADMIN_TOKEN + HttpOnly cookie + require_admin approach is accepted for MVP
* admin route protection consistency was reviewed and validated
* advanced authentication (users/passwords/roles) is intentionally postponed until post-MVP validation

### Calendly availability validation

Manual end-to-end validation was completed:

* booking flow works correctly
* Google Meet links are generated correctly
* email confirmations and cancellations work correctly
* Google Calendar synchronization works correctly

Operational note:

* users located in Russia may require VPN access to reach Calendly booking pages
* consultation booking page should later include a fallback support/contact option if Calendly is unavailable
* evaluate whether customer-facing guidance about VPN requirements is needed before public launch

## Sprint 36 checkpoint: Calendly API validation foundation

### Completed

* created Calendly Personal Access Token
* validated Calendly API access through `/users/me`
* validated current Calendly user URI
* validated current Calendly organization URI
* verified required PAT scopes
* implemented Calendly API client foundation
* implemented webhook subscription discovery
* implemented Calendly API validation script
* confirmed that no Calendly webhook subscriptions currently exist
* confirmed that real webhook validation requires a publicly reachable HTTPS endpoint
* documented current reconciliation assumptions

### Architecture decisions

* Calendly API access is now validated independently from webhook delivery
* webhook subscription lifecycle should be managed through the Calendly API
* current reconciliation based on `provider_event_uri` must be treated as a replay/idempotency mechanism, not a validated first-booking reconciliation strategy
* actual first-booking reconciliation remains an open integration question until real webhook payloads are captured

### Current limitation

* real webhook payloads have not yet been captured
* first-booking reconciliation strategy remains unvalidated
* public HTTPS endpoint is still required for live webhook testing

## Deployment readiness status

### Hosting feasibility

Completed:

* verified that Hetzner registration is not available for Russian residents
* verified that Contabo registration is not available for Russian residents
* evaluated alternative hosting providers
* successfully created Serverspace account using real Russian identity data
* verified Netherlands region availability
* verified deployment infrastructure availability

Important finding:

* deployment is no longer blocked by hosting availability
* deployment is currently blocked by international payment infrastructure

### Domain infrastructure

Completed:

* verified Cloudflare Registrar ownership of neocitrix.com
* verified Cloudflare DNS operation
* verified that SmartBudgetSite has never been publicly deployed
* verified that current DNS records belong only to historical Home Assistant and Ollama usage

Important finding:

* domain ownership and DNS infrastructure are operational
* no production DNS records currently exist for SmartBudgetSite

## International payment infrastructure status

### Current status

* Russian cards cannot currently be used for planned hosting payments
* international banking became a deployment dependency
* Kazakhstan banking route is under evaluation
* VPS purchase is intentionally postponed until payment infrastructure is available

### Project decision

* continue SmartBudgetSite development while payment infrastructure is being arranged
* treat payment setup as an external dependency
* avoid blocking product development on banking timelines

### Superseded assumption

Earlier architecture checkpoints treated `provider_event_uri`
as the likely reconciliation key for Calendly booking confirmation.

Calendly API validation demonstrated that this assumption is incomplete.

Current understanding:

* `provider_event_uri` remains useful for replay handling and idempotency
* `provider_event_uri` is not sufficient for first-booking reconciliation
* first-booking reconciliation remains an open integration question until real webhook payloads are captured

Sprint 36 supersedes earlier assumptions regarding first-booking reconciliation.

## Next sprint priorities (after Sprint 36)

### 1. Deployment preparation

Completed:

* hosting provider evaluation
* deployment feasibility validation
* Serverspace account creation
* Cloudflare domain validation

Current status:

* Serverspace account successfully created
* Netherlands deployment region verified
* Cloudflare Registrar ownership verified
* Cloudflare DNS infrastructure verified
* deployment infrastructure is technically available

Blocked by:

* international payment infrastructure setup
* VPS purchase

Remaining:

* production environment variable setup
* domain integration planning
* production startup validation planning
* operational logging review

---

### 2. Product delivery architecture

New priority:

* define product file storage strategy
* define versioned product delivery strategy
* define download link lifecycle
* define future admin upload workflow
* define release management approach

Goal:

* establish a maintainable product delivery process before first public sales
* avoid manual file distribution workflows after launch
* keep product delivery architecture compatible with future product updates

Decision:

* product delivery must be entitlement-based
* customers receive a protected download page link, not a direct public file URL
* each paid product sale item creates one backend-owned download entitlement
* each download entitlement is tied to the delivered product version
* MVP delivery should prioritize reliable customer access over strict one-click download blocking
* repeated download attempts are allowed only within controlled retry limits
* download access must be blocked when token expiration or retry limits are exceeded

MVP download retry policy:

* allow limited retry attempts for interrupted or failed downloads
* allow retries only within a short validity window
* track download attempt count
* track first download attempt timestamp
* track last download attempt timestamp
* treat signed-URL issuance as a download attempt, not as successful completion
* keep the entitlement status `available` after signed-URL issuance
* do not infer successful completion from a direct Cloudflare R2 redirect because the backend cannot reliably confirm that the browser completed the download
* defer strict one-time completion until reliable completion criteria are available

Anti-abuse controls:

* use secure random download tokens
* never expose direct public storage URLs permanently
* generate short-lived file access URLs only after backend validation
* limit total download attempts per entitlement
* limit download access by expiration window
* show a support-oriented message when access is blocked

Deferred beyond the MVP:

* strict one-time completion
* automatic completion detection
* richer attempt audit logging, including IP address and user agent persistence
* backend file proxying

Support rule:

* admin support tooling should later allow controlled reissue/reset of a download entitlement
* reissue/reset must be explicit and auditable

### Product release architecture

`Product` represents a sellable SKU, not a downloadable file.

Examples:

* SmartBudget RU Standard
* SmartBudget INT Standard
* SmartBudget RU Pro

`ProductRelease` represents a concrete released file/version for one product SKU.

Examples:

* SmartBudget RU Standard v1.0
* SmartBudget RU Standard v1.1
* SmartBudget INT Standard v1.0

`products.version` and `products.archive_path` are legacy/transitional fields and must not be used for new download delivery logic.

New product delivery logic must resolve downloadable files through:

SaleItem
    ↓ product_release_id
ProductRelease
    ↓ storage_key
Cloudflare R2 object

Each product SKU may have many releases, but only one release may be active at a time for new payment preparation.

Customers own the purchased SKU. Each new product `SaleItem` also stores the exact `ProductRelease` selected before payment-provider interaction so later release publication cannot change the purchased release snapshot.

#### Legacy Product fields cleanup rule

Current `products` fields:

* `version`
* `release_date`
* `archive_path`

are transitional legacy fields from the pre-release-management architecture.

New product delivery logic must not depend on these fields.

After `ProductRelease` and `DownloadEntitlement` are fully integrated, these fields must be removed from:

* SQLAlchemy `Product` model
* Alembic schema
* admin product create/edit forms
* product list templates
* seed/dev data scripts
* tests

Until removal, these fields may remain only for backward compatibility and migration safety.

Important rule:

`ProductRelease` is the source of truth for downloadable product version and file storage metadata.

### ProductRelease responsibilities

`ProductRelease` is a technical release entity.

It is responsible for:

* released product version
* release notes
* downloadable archive metadata
* storage provider
* storage object key
* file integrity metadata
* release publication state

It is NOT responsible for:

* product pricing
* product edition
* product family
* product status
* payment logic
* customer ownership

Those responsibilities remain owned by `Product`, `ProductPrice`, `SaleItem`, and `DownloadEntitlement`.

Architecture rule:

Business entities and release management must remain separated.

`Product` describes what is sold.

`ProductRelease` describes what is delivered.

#### Admin release workflow

Product creation and release upload must remain separate operations.

After a product is created successfully, the admin flow should redirect to the product release management page for that product.

The Admin Dashboard should also provide a dedicated release management entry point for routine release uploads.

Workflow:

Create Product
    ↓
Redirect to Manage Releases for created product
    ↓
Upload first release

Regular update workflow:

Admin Dashboard
    ↓
Product Releases
    ↓
Select product / open product releases
    ↓
Upload new release
    ↓
Mark release as active

Administrative usability note:

This page should list all products together with their current active release and allow administrators to navigate directly to release management for an existing product.

This is a usability improvement only. The underlying release management architecture remains unchanged.

#### Release publishing rule

Product Releases must be managed as a release lifecycle, not as a raw file list.

Each product SKU may have many releases, but only one release may be the active public release used for normal customer download delivery.

Admin UI must not allow administrators to manually change the active public release as the primary workflow.

Instead, publishing must happen through an explicit business action:

* Upload release
* Publish release

The publish action must:

* deactivate the previously active release for the same product
* activate the selected release
* set `released_at` when needed
* keep the operation atomic
* guarantee that one product cannot have multiple active public releases

This rule must be enforced in the service layer, not only in templates or admin UI.

Business meaning:

* `Upload release` creates a release candidate.
* `Publish release` makes that release the current customer-facing downloadable version.

Important:

The backend must guarantee that only one active public release exists for each product SKU at any time.

### Product version ownership model

Decision:

* customers purchase a product edition/SKU, not release metadata as a separate commercial product
* product ownership remains tied to the purchased SKU
* each new product `SaleItem` is bound to the exact active `ProductRelease` selected during payment preparation
* future download delivery must preserve that fixed release snapshot rather than dynamically switching the purchase to a later active release
* a future `DownloadEntitlement` may reference the purchased release for delivery, support, rollback, or controlled reissue scenarios
* historical product versions may be retained for operational and customer-delivery purposes without changing SKU ownership

Examples:

* SmartBudget RU Standard purchase → active RU Standard release fixed on its `SaleItem`
* SmartBudget INT Standard purchase → active INT Standard release fixed on its `SaleItem`

Important:

* product version numbers are release-management metadata
* customer ownership is based on purchased product identity, not release version

Release candidate
        ↓
Published (Active)
        ↓
Archived

### Product file storage strategy

Decision:

* Cloudflare R2 is the primary product file storage provider
* product files must not be stored permanently on application VPS instances
* download delivery architecture should remain independent from hosting provider selection
* SmartBudgetSite backend remains responsible for entitlement validation and download authorization
* Cloudflare R2 remains responsible for binary file storage

Architecture direction:

SaleItem
    ↓
DownloadEntitlement
    ↓
ProductRelease
    ↓
Cloudflare R2 object

Benefits:

* product files survive VPS migrations
* hosting provider can be replaced without moving product assets
* product storage scales independently from application hosting
* future release management becomes simpler
* download delivery remains compatible with short-lived signed URLs

Important:

* direct public access to R2 product files must not be allowed
* all download access must pass through backend entitlement validation

---

### 3. Real Calendly integration validation

Completed:

* manual booking flow validation
* Google Meet integration validation
* email notification validation
* Google Calendar synchronization validation
* Calendly API validation
* PAT validation
* current user discovery
* current organization discovery
* webhook subscription discovery

Current findings:

* no Calendly webhook subscriptions currently exist
* public HTTPS endpoint is required for real webhook validation
* current `provider_event_uri` approach is insufficient for first-booking reconciliation
* actual first-booking reconciliation strategy remains unvalidated

Remaining:

* create publicly reachable HTTPS endpoint
* create real Calendly webhook subscription
* capture real `invitee.created` webhook payload
* determine actual first-booking reconciliation strategy
* validate real webhook lifecycle transitions
* validate replay behavior from live provider deliveries
* verify provider booking/cancellation edge cases
* verify SmartBudgetSite webhook processing against real provider deliveries

Important:

* do not repeat Calendly account setup validation
* do not repeat PAT validation
* do not repeat Google Meet validation
* do not repeat booking flow validation

---

### 4. Merchant of Record validation

Current status:

* Paddle onboarding investigation started
* Paddle registration appears unsuitable for current Russian-resident setup
* FastSpring onboarding initiated
* FastSpring account successfully created
* FastSpring onboarding specialist assigned
* product review information submitted to FastSpring

Remaining:

* obtain FastSpring onboarding decision
* determine payout eligibility requirements
* determine supported payout destinations
* validate merchant onboarding requirements
* select final Merchant of Record provider
* define checkout architecture
* define payment success lifecycle
* prepare payment webhook architecture

Important:

* Stripe is selected for the first direct payment-provider integration; real Checkout Session creation is not implemented yet
* international banking infrastructure remains a prerequisite for production launch

---

### Current project state

Operational:

* Admin Dashboard
* Products admin
* Feedback admin
* Consultation Entitlements admin
* Sales admin
* Admin filtering and pagination operational

Calendly:

* Calendly account configured and validated
* Google Meet integration validated
* booking and cancellation flows validated
* Calendly API access validated
* webhook infrastructure prepared

Infrastructure:

* Serverspace account prepared
* Cloudflare domain infrastructure verified
* deployment technically feasible

Quality:

* all automated tests passing

---

### Strategic launch constraint

Current primary deployment blocker:

* international payment infrastructure

Current non-blockers:

* hosting availability
* domain ownership
* DNS infrastructure
* Calendly account setup
* backend implementation readiness

Project decision:

* continue SmartBudgetSite development while payment infrastructure is being arranged
* treat international banking setup as an external dependency
* avoid pausing product development while waiting for banking resolution

---

### Historical documentation rule (superseded)

At this checkpoint, the monolithic backend architecture document was the primary
project state document. The approved documentation architecture later replaced that role with
`docs/current_state.md` and the active documents under `docs/architecture/`.

The operational rules recorded at that checkpoint were:

* update the authoritative documentation when implementation changes it
* preserve sprint checkpoints as history
* avoid re-validating already-confirmed infrastructure decisions

## Sprint 37 checkpoint: Product release foundation

### Completed

* documented product delivery architecture
* documented ProductRelease ownership model
* documented legacy Product field cleanup rule
* documented admin release workflow
* documented release publishing rule
* added `ProductRelease` model
* added `Product` → `ProductRelease` relationship
* added Alembic migration for `product_releases`
* added `ProductReleaseRepository`
* added `ProductReleaseService`
* implemented release creation service logic
* implemented release publishing service logic
* enforced one active public release per product through service-level publish logic
* added Product Releases admin route foundation
* added Product Releases admin template foundation
* added Product Releases entry point styling
* split shared admin CSS into `admin.css`
* moved page-specific admin CSS into dedicated files
* added repository and service tests for product releases
* all automated tests passing: 102

### Architecture decisions

* `Product` remains the commercial SKU entity
* `ProductRelease` is the technical release entity
* uploaded releases are inactive candidates by default
* publishing a release is an explicit business action
* publish logic belongs to service layer, not repository or template
* admin routes must call service methods, not repositories directly
* shared admin UI styles belong in `admin.css`
* page-specific admin styles belong in dedicated CSS files

### Current limitation

* upload release form is not implemented yet
* real file upload to Cloudflare R2 is not implemented yet
* publish action is not wired to Admin UI yet
* download entitlements are not implemented yet
* legacy `products.version`, `products.release_date`, and `products.archive_path` still exist temporarily

## Sprint 38 checkpoint: Product release upload + Cloudflare R2 integration

### Completed

* implemented Product Release upload form
* added multipart release archive upload flow
* added `python-multipart` dependency
* implemented Cloudflare R2 storage service
* added R2 configuration settings
* added storage key generation for product release archives
* integrated release file upload with ProductRelease creation flow
* added Product Releases admin upload route
* added Product Release upload form template
* added upload form styling
* added R2 storage service regression coverage
* added Product Release upload route regression coverage
* added standalone R2 connection validation script
* configured boto3 client with explicit connection and read timeouts
* all automated tests passing

### Architecture decisions

* Cloudflare R2 remains the primary product binary storage provider
* application VPS instances must not permanently store product release archives
* release upload is performed through the admin application flow
* storage object keys are generated by backend storage logic
* ProductRelease stores storage metadata and does not own binary file content
* R2 access remains private and backend-controlled
* R2 connectivity validation must be performed from the future VPS environment
* local R2 connectivity workarounds must not be introduced into application architecture

### External environment validation status

Cloudflare R2 integration is implemented at application level.

Local live validation is blocked by the current network environment:

* the R2 S3 API hostname resolves correctly through Cloudflare DNS-over-HTTPS
* direct TCP connectivity to the resolved R2 S3 API endpoints on port 443 fails
* boto3 reaches the TLS connection stage but fails with `SSL UNEXPECTED_EOF_WHILE_READING`
* the same connectivity limitation was reproduced independently from the application upload form
* the failure is below the SmartBudgetSite application layer

Final live R2 validation is deferred until SmartBudgetSite is deployed to the future VPS.

Required VPS validation:

* validate R2 S3 API connectivity
* validate authenticated bucket access
* validate real Product Release archive upload
* verify uploaded object metadata
* verify ProductRelease persistence after successful upload

### Deferred external integration validation

The future VPS deployment now has two explicit live integration validation tasks:

1. Calendly webhook validation through a publicly reachable HTTPS endpoint
2. Cloudflare R2 S3 API connectivity and real release upload validation

Both validations must be performed from the deployed server environment.

Important:

* do not repeat local Calendly account, PAT, Google Meet, or manual booking validation
* do not repeat local R2 network troubleshooting unless the VPS reproduces the same connectivity failure
* VPS validation should test the existing implementation before introducing architecture changes

### Current limitation

* real R2 archive upload has not yet been validated against the live R2 S3 API
* Product Release publish action is not wired to Admin UI yet
* download entitlements are not implemented yet
* legacy `products.version`, `products.release_date`, and `products.archive_path` still exist temporarily

## Sprint 39 checkpoint: Payment foundation and release binding

### Completed

* added a database-level invariant allowing at most one active `ProductRelease` per `Product`
* added a partial unique index on `product_releases.product_id` where `is_active IS TRUE`
* added nullable `SaleItem.product_release_id` for legacy compatibility
* bound every new product `SaleItem` to the exact active `ProductRelease` selected at payment preparation time
* added provider-agnostic `payment_service.prepare_product_payment()`
* implemented pending `Sale` and `SaleItem` creation before payment-provider interaction
* blocked payment preparation when the selected product has no active release
* added a synchronous admin email notification attempt when payment preparation is blocked by a missing release
* ensured notification failure is logged and does not replace the unavailable-release business result
* added dedicated `ADMIN_NOTIFICATION_EMAIL` configuration
* added recipient validation in `mail_service`
* added a partial unique index on `(payment_provider, external_payment_id)` where `external_payment_id IS NOT NULL`
* decided that `Sale.external_payment_id` will store the Stripe Checkout Session ID
* kept this foundation provider-independent: no real Stripe API calls or payment initiation POST route are implemented yet
* all automated tests passing: 112

### Architecture decisions

* product ownership remains tied to the purchased `Product`/SKU
* each new product `SaleItem` stores the exact `ProductRelease` selected before payment-provider interaction
* payment preparation services may flush the database session but must not commit
* higher-level payment orchestration owns transaction completion
* payment preparation services do not communicate with payment providers
* a missing active release blocks payment before any provider interaction
* failed payment-session creation must preserve the `Sale`, mark it as `failed`, keep `external_payment_id` as `NULL`, and create no entitlements
* retrying payment after a failed payment-session creation creates a new `Sale`
* admin notification SMTP failure must not break the customer-facing unavailable result
* new configuration settings require updates to `.env.example`, the active local `.env`, and deployment configuration
* unique payment identity is scoped by `(payment_provider, external_payment_id)`

### Current limitations / next work

* no real Stripe Checkout Session creation
* no payment initiation POST route
* no payment-provider adapter
* no payment webhook processing
* no transition from `pending` to `paid` or `failed` through provider events
* no `DownloadEntitlement` creation after successful payment
* no localized route response for release unavailability yet
* no real PostgreSQL migration execution validation yet
* no end-to-end SMTP notification test outside mocked tests
* no commit yet

## Sprint 40 checkpoint: Download entitlement and protected delivery MVP

### Completed

* added `DownloadEntitlement` model
* added download entitlement statuses:
  * `available`
  * `completed`
  * `expired`
  * `cancelled`
  * implemented relationship chain:

```
  Sale
    ↓
  SaleItem
    ├──→ ProductRelease
    └──→ DownloadEntitlement
```

* enforced one download entitlement per `SaleItem`
* bound each entitlement to the exact `ProductRelease` stored in `SaleItem.product_release_id`
* added secure unique download token generation
* added configurable download token lifetime:
  * `DOWNLOAD_TOKEN_TTL_HOURS`
  * current default: 12 hours
* added download lifecycle fields:
  * `attempt_count`
  * `first_attempt_at`
  * `last_attempt_at`
  * `completed_at`
  * `expires_at`
* added `DownloadEntitlementRepository`
* added `download_entitlement_service`
* implemented entitlement creation rules:
  * only product sale items are eligible
  * parent sale must be paid
  * `product_release_id` is required
  * duplicate entitlement creation is blocked
  * service uses `flush()` and does not commit
* implemented backend validation of download entitlements by secure download token
* added customer-facing protected download page
* added `GET /download/{token}` with read-only entitlement validation
* added `POST /download/{token}` with entitlement revalidation and attempt recording
* backend validates every download request before exposing temporary storage access
* added Cloudflare R2 signed GET URL generation
* configured signed URL lifetime through `DOWNLOAD_SIGNED_URL_TTL_SECONDS`
  * current default: 900 seconds / 15 minutes
* configured retry limit through `DOWNLOAD_MAX_ATTEMPTS`
  * current default: 3 attempts
* signed-URL issuance increments `attempt_count`
* `first_attempt_at` is populated only once and `last_attempt_at` is updated for every attempt
* entitlement intentionally remains `available` after signed-URL issuance
* retries remain available while the token is unexpired and the attempt count is below `DOWNLOAD_MAX_ATTEMPTS`
* added localized RU/EN download page and error handling
* added masked support reference without exposing the download token
* added focused repository, service, storage, and route regression coverage
* added Alembic migration:
  * `b8f4a2d91c6e_add_download_entitlements.py`
* all automated tests passing: 143

### Architecture decisions

* `DownloadEntitlement` is the backend-owned source of truth for product download access.
* Product download ownership belongs to `SaleItem`, not directly to `Sale`.
* Delivered release is fixed from `SaleItem.product_release_id`.
* Entitlement creation must never resolve the currently active release dynamically.
* One product `SaleItem` may have at most one download entitlement in the MVP.
* Service `SaleItem`s must not receive download entitlements.
* Download tokens are secure, unique, and expire after a configurable lifetime.
* Entitlement expiration may be validated dynamically without immediately mutating status.
* Services may raise `HTTPException` under the current documented project convention.
* Transaction ownership remains outside the entitlement service.
* customer-facing download access must always pass through backend entitlement validation before any storage-provider URL is exposed.
* Direct Cloudflare R2 delivery through a redirect does not reliably confirm that the browser completed the download.
* Signed-URL issuance is a download attempt, not successful completion.
* Download access is controlled by token expiration and `DOWNLOAD_MAX_ATTEMPTS`.
* Automatic completion detection, strict one-time completion, richer attempt audit logging, and backend file proxying are deferred.

### Current limitations / next work

* automatic download completion detection is intentionally deferred
* strict one-time completion is intentionally deferred
* richer attempt audit logging, including IP address and user agent persistence, is deferred
* backend file proxying is not implemented
* no purchase email with download link
* no payment-success orchestration creating download entitlements
* no Stripe webhook integration
* no admin reissue/reset workflow
* integrate the protected download flow with the Feedback workflow:
  * add a dedicated "Purchase or download issue" feedback type;
  * allow preselecting the feedback type from download pages;
  * prefill the download support reference;
  * streamline customer support for download-related issues.
  * download attempts are committed before storage-provider interaction
