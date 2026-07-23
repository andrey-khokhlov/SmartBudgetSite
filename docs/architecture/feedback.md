# Feedback Architecture and Workflow

## Document role

This document is the authoritative source for feedback and review workflow,
publication rules, and founder-operated feedback administration.

Backend layer boundaries are documented in `docs/architecture/backend.md`.
Implementation status and current priorities are documented in
`docs/current_state.md`.

## Purpose

SmartBudgetSite uses feedback as a private communication channel that may, in a
limited and deliberate case, provide the source material for a public product
review. The workflow is designed for clear, sustainable operation by a solo
founder rather than as a general-purpose support platform.

## Scope

This document covers:

- feedback message types and lifecycle;
- admin list and detail workflows;
- reply-draft and one-time email rules;
- current publication rules;
- product/SKU-scoped reviews;
- the intentionally deferred separation of private feedback from curated public
  reviews, Q&A, and FAQ content.

It does not define the general backend layers, product or pricing models, or
unrelated admin functionality.

## Current implemented behavior

### Feedback message types

#### `site_issue`

- Used for private support.
- Admin may review the message, prepare a reply draft, and send one email reply
  when an email address is available.
- It must never be published as a public review.

#### `general_question`

- Used for private communication.
- Admin may review the message, prepare a reply draft, and send one email reply
  when an email address is available.
- It must never be published as a public review.

#### `product_feedback`

- Used for product-related feedback.
- Admin may handle it privately through the reply workflow or publish it as a
  product review when all publication requirements are satisfied.
- Email sending is blocked after publication.

#### `purchase_or_download_issue`

- Used for private support when a customer has a purchase or download problem.
- It does not require the product-feedback purchase-verification flow.
- Admin may review the message, prepare a reply draft, and send one email reply
  when an email address is available.
- It must never be published as a public review.
- It may include a generic `support_reference` copied from a safe
  customer-facing error page.

### Support references

`FeedbackMessage.support_reference` is nullable, structured support context. It
does not create ownership and has no foreign key to an entitlement or payment
record. This keeps the field compatible with download references and future
payment references such as `PAY-*` without coupling private feedback to one
provider or domain entity.

Each `DownloadEntitlement` owns a unique, randomly generated public reference in
the format `DL-XXXXXXXX`. The suffix uses uppercase unambiguous alphanumeric
characters. The reference is independent from the private download token and
does not expose database identifiers, sale identifiers, customer data, provider
identifiers, storage keys, or exception text.

Download error pages may link to `/feedback` using only the exact private
feedback type, the stored public support reference, and language context. The
feedback GET route validates these values and resolves an existing `DL-*`
reference through a service and repository before rendering customer context.
The feedback POST route validates the structured reference again before
persistence. Invalid, unknown, or unsupported prefill references are ignored;
malformed submitted references are rejected.

Payment support-reference generation is not implemented. The generic feedback
field and prefill contract only preserve compatibility for that future work.

### Protected admin workflow

Feedback administration is available through protected admin routes.

The list page:

- shows feedback ID, creation time, type, email, subject, and resolution state;
- orders unresolved messages first and newest messages first within each group;
- paginates the result set.

The detail page allows the admin to:

- view the message;
- mark it resolved or open;
- save or edit the reply draft;
- send the one permitted email reply;
- publish or unpublish eligible product feedback.

This is a lightweight operational inbox. It is not a helpdesk, ticketing system,
CRM, live chat system, or customer-success platform.

### Reply draft and email

`admin_reply` is an internal draft. It is not sent automatically and remains
editable before sending.

Email sending is a one-time action and requires:

- a non-empty `admin_reply`;
- a non-empty customer email address;
- no previous send recorded in `reply_sent_at`;
- feedback that is not currently published.

After sending:

- `reply_sent_at` is set;
- `reply_sent_to_email` stores the destination address;
- any further conversation continues in the regular email client.

The admin interface is not a threaded email client. It sends the initial reply
only and does not manage an ongoing conversation thread.

### Publication and product reviews

The current direct-publication model uses fields on `feedback_messages`.
Eligibility is governed by the authoritative business rules below.

When published:

- `is_published = true`;
- `published_at` is set;
- email sending is blocked.

When unpublished:

- `is_published = false`;
- `published_at = null`.

Public display uses:

- `/reviews/{slug}` for one product;
- `/reviews` as a redirect to the configured default product review page.

### Product-feedback purchase lookup

The implemented SEC-003, CODE-002, and CODE-001 flow preserves the low-friction
interaction while identifying the exact reviewed SKU:

1. The customer selects product feedback and enters the purchase email.
2. The browser performs the existing public purchase lookup roundtrip.
3. If one qualifying paid product purchase exists, the browser selects it
   automatically without displaying a selector.
4. If multiple qualifying paid product purchases exist, the browser displays a
   product selector.
5. The customer reviews, edits, and submits the feedback normally.

Email is a practical purchase lookup key for this flow. It is not strong proof
of identity, mailbox ownership, or exclusive authority to act for the purchase.
MVP does not add email confirmation, a magic link, a one-time code, or another
browser verification roundtrip.

When no qualifying purchase exists, the public response remains exactly
`{"verified": false}`. Verified responses contain a safe purchase list with only
an opaque `purchase_reference`, public product name, and public edition. They do
not return purchase dates, internal `sale_id`, `sale_item_id`, or `product_id`
values, provider identifiers, payment metadata, or other purchase details.

Product-feedback submission sends the email and `purchase_reference`, not an
internal ownership identifier. The public contract does not accept `sale_id`,
`sale_item_id`, or `product_id`. A successful browser lookup is UI state, not
authorization. The server normalizes the submitted email, resolves the opaque
reference only among paid product `SaleItem` rows owned by that email, rejects
forged and cross-email references, and persists the internally resolved
`product_id`.

The browser opens the protected feedback fields only when the response contains
the literal boolean result `verified === true` and at least one structurally
valid safe purchase. Multiple purchases require a selection before submission.
False, malformed, and request-error responses fail closed.

The accepted residual risk is that someone who knows a purchaser's email may
submit feedback as that purchaser. This does not expose a downloadable product,
payment information, or an internal purchase record; cannot modify a purchase;
and is mitigated operationally through feedback moderation.

CODE-002 establishes exact reviewed-product ownership through the opaque
reference validation, and CODE-001 persists the resolved product association on
the feedback record.

## Authoritative business rules

- Raw feedback is private by default and must not be displayed publicly as-is.
- Only `product_feedback` may currently be published.
- Publication requires both `admin_reply` and `product_id`.
- Public reviews belong to the exact product/SKU identified by `product_id`.
  Reviews are not global or shared across variants such as SmartBudget RU and
  SmartBudget INT.
- Public feedback lookup and submission contracts must not expose or accept
  internal purchase identifiers as browser authority. Exact product ownership
  resolution and persisted product association remain backend-owned
  responsibilities.
- `site_issue` and `general_question` always remain private.
- `purchase_or_download_issue` always remains private.
- Support references must never contain access tokens, provider identifiers,
  signed URLs, storage keys, raw exceptions, customer email addresses, or
  database identifiers.
- Publishing is an explicit admin action, not an automatic consequence of
  receiving positive feedback.
- Feedback, reviews, and Q&A are different content concepts:
  - feedback is raw private input;
  - a review is public content derived from approved product feedback;
  - Q&A is curated and rewritten public content.
- The admin workflow supports one initial email reply and does not become a
  threaded email client.

## Recorded test coverage

Existing documentation records service coverage for:

- email sending with a missing email, successful send, repeated-send rejection,
  missing reply, and published-feedback restriction;
- publication type validation, successful publication, publish/unpublish toggle,
  and missing-reply rejection;
- resolved-state toggling;
- reply-draft saving;
- empty-value normalization.

Route coverage is recorded for successful and repeated email sending and for
publish/unpublish behavior. SMTP is blocked in tests and mail is mocked globally.

The established testing boundary is:

- service tests cover business rules;
- route tests cover HTTP wiring.

### Browser and multipart validation

Feedback browser behavior must be tested as the browser sends it, not only as an
equivalent logical API payload. In particular, omitting the optional `files`
field from a test request does not reproduce `FormData` behavior when a browser
includes an empty multipart file part for an unselected file input.

Regression coverage for optional attachments must include:

- submission with no attachment selected through the real browser form;
- the browser-equivalent zero-byte empty-file sentinel;
- one or more valid named attachments;
- rejection of malformed upload states rather than treating them as absent.

Browser coverage for the dynamic form should also capture page and console
errors, verify initialization, switch through every supported message type, and
assert the expected visible and hidden fields. The general browser-validation
and release rules are defined in `../operations.md`.

## Download support-flow prefill

The implemented download failure-to-Feedback flow minimizes repeated typing
without submitting anything automatically. After an existing `DL-*` reference
is resolved server-side, a small service-level DTO carries only customer-facing
context: customer email, public support reference, public product name and
edition, release version, purchase date, and localized initial subject and
message. The form preselects the private `purchase_or_download_issue` type and
shows the support reference as readonly. Email, subject, and message remain
editable, and the customer must explicitly choose Send.

If the customer selects another message type, the reference is hidden and
disabled so it is excluded from submission; switching back restores the same
readonly reference. After a successful submission, the browser clears all
prefilled values and returns the form to a clean ordinary state while retaining
the success confirmation.

The prefill DTO never contains download tokens, provider identifiers, signed
URLs, storage keys, raw exceptions, database or ownership identifiers, or
internal statuses. Payment support prefill remains unimplemented.

## Post-MVP product enhancement

Add a **Leave feedback** entry point directly inside the SmartBudget workbook so
legitimate users can open the feedback form from the product itself without
manually entering their purchase email. This is a future product enhancement,
not part of the SEC-003 MVP security boundary and not currently implemented
behavior.

## Intentionally deferred target architecture

The current use of `feedback_messages.is_published` is transitional. It remains
the implemented behavior until a separate public-content model is explicitly
introduced.

The target separation is:

- `feedback_messages` — private raw input that is never itself a public display
  entity;
- `product_reviews` — explicitly approved and curated public reviews linked to
  `product_id`;
- `product_qna` — curated product questions and founder answers;
- curated FAQ content — generally useful questions and answers with optional
  product association, visibility, and ordering metadata.

Separate entities allow private support, reviews, Q&A, and FAQ content to have
independent lifecycles. Public records may retain the relevant product reference,
curated text and reply, publication state, timestamps, and an optional display
name or anonymized author label.

This target is intentionally deferred. It must not be described as current
behavior, and implementation should occur only when that work is explicitly in
scope.
