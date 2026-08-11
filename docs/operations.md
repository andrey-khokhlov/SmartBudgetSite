# Operations

This is the authoritative source for local development commands, environment
configuration rules, deployment preparation, and operational validation.

## Development commands

## Run application

```bash
python run.py
```

With the normal local `.env` configuration, the application is available at
`http://127.0.0.1:8800`. This is the authoritative local development startup
method; avoid documenting or running parallel startup commands that can create
duplicate application processes.

`run.py` binds Uvicorn to `APP_HOST` and `APP_PORT`. Settings precedence is:

```text
process environment
    -> selected environment file
        -> Settings default
```

`ENV_FILE` selects the environment file and defaults to `.env`. A process
environment value overrides the selected file, and `Settings.APP_PORT = 8000`
is only the fallback when neither source supplies `APP_PORT`.

## Port contract

| Port | Purpose | Environment scope | Port role |
|---:|---|---|---|
| `8000` | Fallback `APP_PORT` from `Settings` | Any environment without an `APP_PORT` override | Application bind port |
| `8800` | Normal configured local SmartBudgetSite listener | Local development through `.env`, initially copied from `.env.example` | Application bind port |
| `4000` | Internal SmartBudgetSite listener in the production environment | Production through `.env.prod` when that file is selected | Application bind port; not a public reverse-proxy port |
| `5433` | Local host access to the development PostgreSQL container | Local Docker development | Host-side database port mapping |
| `5432` | PostgreSQL listener inside the container | Local Docker network/container | Container port |
| `5173` | Allowed origin for a separately run frontend development server | Local frontend development only | Frontend development origin; not a SmartBudgetSite bind port |
| `587` | Configured outbound SMTP submission endpoint | Environments using the example SMTP configuration | External provider port; not a local bind port |

Docker Compose maps host port `5433` to PostgreSQL container port `5432`.
Production reverse-proxy, public HTTPS, and host-port selection remain part of
`REL-002`; the internal application port `4000` does not define that deployment
architecture.

## Codex pytest validation environment

Codex pytest runs must keep temporary and cache data outside the repository.
Use these locations:

```text
C:\Users\Admin\AppData\Local\SmartBudgetSite\pytest-temp\<task-name>
C:\Users\Admin\AppData\Local\SmartBudgetSite\pytest-cache
```

Replace `<task-name>` with a short task-specific name. Every focused or full
Codex validation command must specify both locations:

```powershell
python -m pytest [test paths] `
  --basetemp="C:\Users\Admin\AppData\Local\SmartBudgetSite\pytest-temp\<task-name>" `
  -o cache_dir="C:\Users\Admin\AppData\Local\SmartBudgetSite\pytest-cache"
```

The task-specific basetemp directory may be removed after validation. The shared
external pytest cache may be retained between runs. Repository-local
`.codex-pytest-*` directories are a configuration error and must not be created.

## Alembic (database migrations)
```
# Show current applied migration (version in DB)
alembic current

# Show full migration history
alembic history

# Generate new migration based on model changes
alembic revision --autogenerate -m "message"

# Apply all pending migrations (upgrade DB to latest state)
alembic upgrade head

# Rollback last migration (use carefully)
alembic downgrade -1
```

## Docker (PostgreSQL)
```
# Start containers in background
docker compose up -d

# Stop containers
docker compose down

# Stop and REMOVE volumes (⚠️ will delete database data)
docker compose down -v
```

## PostgreSQL checks
```
-- List all tables in public schema
SELECT schemaname, tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Check current database and user
SELECT current_database(), current_user;
```

## Notes
* Keep all committed Alembic migration files in alembic/versions (this is your DB history).
* Do NOT delete migrations unless you clearly understand consequences.
* Delete temporary/debug scripts (like check_db.py) before commit.
* Store all secrets (DB credentials, SECRET_KEY) only in .env.
* Never commit .env to Git.

## Current OpenAI platform notes

These are current operational observations, not permanent platform guarantees:

* Treat Codex usage as a limited engineering resource and reserve it for bounded repository work.
* When a Weekly Full Reset is available, it can immediately begin a new usage period.
* Additional Codex Credits are available separately when needed.

## Environment variables rule

* Every variable added to `.env` MUST be added to `.env.example`
* `.env.example` contains only example values (no real secrets)
* `.env` is never committed to Git

## Configuration completion rule

Whenever a setting is introduced:

- add it to `.env.example` with a placeholder;
- add it to the active local development `.env`;
- determine whether deployment documentation and production environment
  variables must also be updated.

A configuration change is not complete until the example and active development
configuration are updated. Secrets, tokens, credentials, and provider signing
secrets must never be committed or accepted from request input.

Purchase-email delivery is controlled by
`PURCHASE_EMAIL_DELIVERY_ENABLED`. When enabled, `RESEND_API_KEY`,
`MAIL_FROM_EMAIL`, `MAIL_FROM_NAME`, and an absolute server-owned
`PUBLIC_BASE_URL` are required at startup. `PUBLIC_BASE_URL` owns customer
download and consultation link construction; request Host headers are never
used. Keep delivery disabled in local environments unless a deliberate
provider send is intended. Automated tests always use fake transports.

`PRODUCT_RELEASE_MAX_UPLOAD_BYTES` owns the application-level administrative
release archive limit. Its default and production value are 52,428,800 bytes
(50 MiB), and the value must remain strictly positive. The inclusive limit is
enforced while size and SHA-256 metadata are calculated in bounded 1 MiB chunks;
larger archives receive HTTP 413 before storage upload or database persistence.

The deployment reverse proxy must set its request-body limit slightly above the
50 MiB application file limit to allow multipart overhead. This perimeter limit
is not configured in the current repository. Without it, Starlette can receive
and temporarily spool the complete multipart body before the application-level
release check runs, even though the route no longer buffers the complete archive
in process memory.

## Capability URL protection

The public download and consultation booking paths contain bearer capabilities:

```text
/download/{token}
/consultation/book/{token}
```

Every response for these path families, including errors and redirects, uses:

```text
Cache-Control: private, no-store, max-age=0
Pragma: no-cache
Expires: 0
Referrer-Policy: no-referrer
```

Uvicorn access logging remains enabled, but its configured filter removes every
query string and replaces download and booking token segments with
`[REDACTED]`, including capability paths embedded literally or percent-encoded
inside another request target. Application code must not log raw capability
tokens, full capability URLs, raw request targets, signed R2 URLs, or redirect
`Location` values. SQLAlchemy hides bound parameters globally so database
exceptions do not disclose token lookup values.

Signed R2 GET responses specify `private, no-store, max-age=0` and an already
expired response date while retaining the configured short TTL and attachment
content disposition.

The production reverse proxy and CDN are not configured in this repository.
Their release configuration must:

- disable access logging for both capability route families;
- avoid request-line, URI, query-string, and Referer values in related error
  logging;
- bypass all proxy and CDN caching for capability routes;
- avoid exporting signed R2 query strings into general operational logs.

Release-environment validation must confirm those perimeter rules and actual
provider behavior. Future customer emails may contain capability links only as
the required delivery context; email click tracking and provider link rewriting
must be disabled for them.

## Rate limiting and trusted client identity

`RATE_LIMIT_ENABLED` defaults to `true` and cannot be `false` in production.
`RATE_LIMIT_MAX_IDENTITIES` defaults to 10,000 and must be positive. Thresholds
remain version-controlled application policy rather than environment strings.
The limiter is process-local and non-persistent.

Initial production must run exactly one application worker. Multi-worker
production is unsupported until a shared atomic limiter backend is approved.
Restarting the process resets application counters; this is an accepted bounded
residual risk only while the required production perimeter remains active.

Application policies:

| Boundary | Application policy |
|---|---|
| `POST /v1/feedback` | 5/15 min and 20/24 h per client IP |
| `POST /v1/check-purchase` | 12/10 min per IP and 10/60 min per normalized-email HMAC |
| `POST /checkout/{slug}` | 8/10 min per client IP |
| download GET | 60/15 min per IP and 30/15 min per capability HMAC |
| download POST | 10/15 min per IP and 5/15 min per capability HMAC |
| unsupported download methods | 10/15 min per IP and 5/15 min per capability HMAC |
| consultation booking GET | 60/15 min per IP and 30/15 min per capability HMAC |
| unsupported booking methods | 10/15 min per IP and 5/15 min per capability HMAC |
| admin authentication | shared 5/15 min per IP across login and invalid-cookie access |
| Calendly pre-verification | 120/min per IP |
| Calendly post-verification | 300/5 min provider-wide and 10/3 min per signature HMAC |
| Lava.top pre-verification | 120/min per IP |
| Lava.top post-verification | 300/5 min provider-wide |

The production perimeter must provide:

| Boundary | Perimeter policy |
|---|---|
| feedback | 10/min, burst 5 |
| purchase lookup | 30/min, burst 10 |
| download GET family | 120/min, burst 20 |
| download POST | 30/min, burst 10 |
| consultation booking family | 120/min, burst 20 |
| admin login | 20/min, burst 5 |
| generic admin safety ceiling | 120/min |
| Calendly webhook | 300/min, burst 100 |
| Lava.top payment-result webhook | 300/min, burst 100 |

No proxy technology is selected in this repository. Production configuration
must return HTTP 429 rather than a technology-default 503 for quota rejection
and must supply an integer `Retry-After`.

Application code uses only the validated ASGI `request.client.host`; it never
parses `Forwarded` or `X-Forwarded-For`. IPv4 is canonicalized normally and
IPv6 is grouped by `/64`, then the identity is HMAC-protected before storage.
Local `python run.py` explicitly disables proxy-header interpretation.
Production must:

- trust forwarded headers only from exact proxy peers or controlled sockets;
- never use a wildcard trusted-proxy setting;
- overwrite or remove incoming `Forwarded` and `X-Forwarded-*` values;
- prevent public traffic from reaching Uvicorn directly;
- keep the application worker count at exactly one.

Application and webhook 429 responses use
`{"detail":"Too many requests. Please try again later."}`. HTML routes use a
localized non-redirecting page. All 429 responses include integer
`Retry-After`; capability responses additionally retain the SEC-009 cache and
referrer headers.

Rate-limit logs contain only policy name, method, route template, identity kind,
retry duration, safe status, and provider name when applicable. Only the first
rejection for a policy/key/window is logged. Raw IPs, capability tokens,
purchase references, emails, credentials, cookies, webhook signatures, signed
URLs, request targets, queries, and HMAC keys are forbidden.

The production perimeter is not configured or validated in this repository.
Release-environment validation must confirm the stated rates, bursts, 429 and
`Retry-After` behavior, trusted-header handling, one-worker process model, and
continued SEC-009 logging/cache behavior.

## Feedback attachment reconciliation

Feedback attachments use private local storage below `UPLOAD_DIR/feedback`.
Database rows contain relative `feedback/<random-name>.<extension>` keys, not
physical filesystem paths.

Run non-destructive reconciliation with:

```bash
python scripts/reconcile_feedback_attachments.py
```

This reports database rows whose files are missing, filesystem files without a
matching attachment row, unsafe persisted keys, and unsafe filesystem entries.
It does not mutate database rows or files.

To delete only validated generated orphan files below the feedback storage root,
run:

```bash
python scripts/reconcile_feedback_attachments.py --delete-orphans
```

The deletion flag never removes database rows, repairs missing rows, or deletes
outside the validated feedback root. Review the read-only report before using
the flag. Reconciliation is founder-operated and does not run at application
startup.

## Product release reconciliation

Run the founder-operated, non-destructive R2/database comparison with:

```bash
python scripts/reconcile_product_releases.py
```

The report covers database rows with missing objects, object size or SHA-256
mismatches, orphaned objects under the managed release prefix, unexpected
legacy keys, and inspection failures. Output uses short key digests rather than
raw object keys. It does not mutate R2 or the database.

After reviewing the report, deletion of eligible stale orphans may be requested:

```bash
python scripts/reconcile_product_releases.py --delete-orphans
```

Deletion applies only to current-format opaque release keys older than the
configured minimum age (24 hours by default). The command rolls back any
ambient database transaction and rechecks ownership immediately before every
delete. It never deletes database-owned objects, repairs or deletes rows, or
runs automatically at application startup. A failed or uncertain delete remains
reported for manual follow-up.

## Product checkout configuration

Use the protected product Admin workflow for normal Lava.top checkout setup:

1. Create the Product with its initial active price, normally using
   `in_development` until its remaining commerce configuration is complete.
2. Upload and publish an active `ProductRelease` through the release Admin
   workflow.
3. Open the Product's Edit page and create or update its explicit `lava_top`
   external Offer ID. Price-by-request Offer IDs may be shared by multiple
   Products.
4. Review the informational missing-prerequisite list. When price, release, and
   provider mapping are present, set the Product to `in_sale` through the normal
   product form.
5. Return to the Edit page and verify `Checkout ready: Yes` before exercising
   public checkout.

The Admin provider form does not call Lava.top or validate the Offer ID
remotely. It does not create mappings automatically during Product creation and
does not change Product status. The existing founder-operated CLI remains a
fallback when the Admin UI is unavailable:

```powershell
.\.venv\Scripts\python.exe .\scripts\set_payment_provider_offer.py `
  --product-slug <exact-product-slug> `
  --provider lava_top `
  --external-offer-id <lava-offer-id>
```

Public checkout continues to resolve the exact active price, active release,
and Product/provider mapping server-side and fails closed when configuration is
missing.

## Manual Lava.top checkout smoke test

The Lava.top checkout smoke command is a deliberate live-provider operation.
Running it creates a real Lava.top invoice and a corresponding SmartBudgetSite
`Sale`; it must be invoked manually and must not be included in automated test
or deployment startup commands.

Use an existing product, active release, active currency-specific catalog price,
and `PaymentProviderOffer` mapping:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_lava_top_checkout.py `
  --product-slug smartbudget-int-standard `
  --customer-email <customer-email> `
  --currency EUR
```

The command does not accept an amount. It selects the exact active
`ProductPrice` for the requested currency, uses the existing payment services,
and prints only non-secret sale and invoice diagnostics. It never prints the
customer email, API key, hosted payment URL, request headers, or full provider
response.

### Lava.top payment confirmation and reconciliation

Configure two different server-owned secrets:

```dotenv
LAVA_TOP_API_KEY=<outbound API credential>
LAVA_TOP_WEBHOOK_SECRET=<dedicated inbound Payment-result key>
```

The inbound secret is configured as Lava.top's Payment-result webhook API key
and arrives in `X-Api-Key`; it must never equal the outbound API credential.
When outbound Lava.top checkout is enabled in production, application startup
fails if the inbound webhook secret is empty. The webhook URL is
`/v1/webhooks/lava-top/payment-result`. Do not log either key, raw webhook
payloads, customer data, or hosted payment URLs.

Lava.top may retry webhook delivery. For an unresolved invoice, inspect the
Payment-result webhook history in the Lava.top dashboard and resend the exact
event. Same-outcome replay is safe. HTTP 409 means the event needs operator
reconciliation; do not alter payment status manually in SQL.

For explicit server-to-server verification of one known Sale/invoice pair:

```powershell
.\.venv\Scripts\python.exe .\scripts\reconcile_lava_top_invoice.py `
  --sale-id <sale-id> `
  --external-payment-id <lava-invoice-id>
```

The command queries `GET /api/v2/invoices/{id}` with the outbound credential,
requires the returned invoice identity to match, and applies a terminal
`COMPLETED` or `FAILED` result through the same domain transaction used by the
webhook. `NEW` and `IN_PROGRESS` remain unresolved payment truth. After the
response identity and Sale snapshot are validated under the Sale lock, the
command commits only a provider-independent `non_terminal` observation and its
last-check timestamp, then reports that the invoice is not terminal. Repeating
the lookup safely refreshes that observation. Provider lookup, identity,
reconciliation, database, or commit failures do not record a successful check.

Live validation on 2026-08-10 used this command for two real 50 RUB Sales. Lava.top
reported Sale #6's invoice as terminal and successful; reconciliation changed
Sale #6 from pending to paid, created exactly one product
`DownloadEntitlement`, created no consultation entitlement, and returned
idempotent without duplicate fulfillment when repeated. Lava.top reported Sale
#5's invoice as non-terminal (`NEW`/`IN_PROGRESS` equivalent), so Sale #5
remained pending and no status was forced manually.

On 2026-08-11, the same explicit authoritative path successfully reconciled
real Sale #7. Its purchase email was sent through Resend, its protected product
access page opened, and its protected download completed successfully. This is
product-only manual reconciliation evidence; live automatic Lava.top webhook
delivery remains unvalidated pending public HTTPS.

Live Payment-result webhook delivery remains unvalidated because SmartBudgetSite
is not publicly reachable over HTTPS. Configure and validate the webhook in
Lava.top when a public HTTPS deployment or approved temporary public endpoint
exists; until then, do not treat manual reconciliation evidence as webhook
validation.

Interpret Admin payment state as follows:

- `paid`: authoritative success committed with complete item fulfillment;
- `failed`: authoritative provider failure for a formerly pending Sale;
- `pending`: no terminal provider result has been committed;
- `Check needed`: pending for at least 24 hours with no durable non-terminal
  provider check recorded;
- `Checked — waiting`: pending for at least 24 hours after an explicit lookup
  found the provider invoice non-terminal. The exact last-check time is exposed
  in the Admin tooltip.

## Deployment and external integration validation

Before production deployment, complete the production environment variables,
domain integration, startup validation, and operational logging review.

The first deployed public HTTPS environment must validate the existing
implementation before prompting architecture changes:

1. Create and validate the Calendly webhook subscription, capture a real
   `invitee.created` payload, confirm initial reconciliation, and verify replay
   and cancellation edge cases.
2. Validate Cloudflare R2 S3 connectivity, authenticated bucket access, real
   release upload, stored object metadata, `ProductRelease` persistence,
   identical retry behavior, compensation after a forced database failure, and
   read-only reconciliation against paginated production-like listings.

Use `current_state.md` to identify completed external validation and current
blockers. Test the existing implementation from the deployed environment before
introducing architecture changes or repeating local integration troubleshooting.

See `current_state.md` for current priorities and blockers.

## Validation policy

Critical user-facing flows require automated browser validation where it is
appropriate and at least one real manual browser check before release. A
technically successful request or persisted record is not sufficient when the
rendered interface is incomplete, misleading, or unusable.

Manual browser checks validate the complete rendered experience, including:

- field and control completeness;
- conditional visibility and dynamic state transitions;
- polite announcement of progress and successful completion, prompt
  announcement and control association for errors, and cleanup of stale
  invalid state in both supported public locales;
- keyboard operation and focus behavior across asynchronous state changes;
- JavaScript initialization and error-free execution;
- the intended customer interaction from entry point through confirmation;
- behavior after a normal refresh with previously cached static assets.

Playwright is a development/test-only layer and is not a production runtime
dependency. Browser tests remain separate from ordinary pytest discovery, use
Chromium as the supported browser, and should capture page errors and console
errors while exercising dynamic behavior and critical journeys. The single
source for local Playwright setup and browser-test commands is
`../browser_tests/README.md`; do not duplicate those installation instructions
here. The ordinary non-browser suite uses the Codex pytest validation
environment and command options documented above.

Migration-sensitive behavior must also be validated against PostgreSQL through
Alembic. SQLite schemas created from SQLAlchemy metadata are useful for tests but
do not prove production schema parity. See `architecture/backend.md` for the
authoritative database-parity rule.

# Operational Reviews

## Sprint Closing Review

Purpose: capture everything that must survive beyond the current chat and
sprint.

The review covers:

- implemented functionality;
- architecture decisions;
- intentionally deferred decisions;
- technical debt;
- engineering observations;
- required documentation updates;
- required updates to `current_state.md`;
- required updates to the relevant architecture documents;
- preparation of the next sprint opening message.

Review every unresolved item in the external
`SmartBudgetSite — Working Queue`. Transfer only information that must survive
the sprint, using the authoritative-document classification and review process
defined in `../AGENTS.md`; do not promote the queue itself into repository
documentation. Remove an item from the Working Queue only after an independent
review confirms the repository change and the transfer is explicitly
confirmed. The queue should normally be empty when Sprint Closeout is complete.

Perform the Sprint Closing Review before the final commit of every sprint.

## Release Readiness Review

Purpose: verify that the product is genuinely ready for public release.

### Engineering

Review test results, migrations, documentation synchronization, security,
deployment readiness, logging, and monitoring.

### Product

Review feature completeness, UX, pricing, licensing, consultation flow, and
consistency with product positioning.

### Marketing

Review the landing page, screenshots, product descriptions, FAQ, and release
notes.

### Operations

Review payment-provider readiness, download delivery, support workflow, backup,
recovery, and production configuration.

### Required end-to-end journeys

Before the first public release, manually execute every supported customer
journey end to end. Validation is scenario-based rather than page-based: opening
individual pages does not prove that the customer can complete a workflow or
that the corresponding admin follow-up is usable.

At minimum, verify:

- successful purchase;
- protected download;
- failed payment;
- download failure followed by the support flow;
- product feedback after purchase verification;
- general question submission and follow-up;
- site issue submission and follow-up;
- consultation booking;
- the related admin review and follow-up for each applicable journey.

The product is not release-ready until every supported journey has been
completed and verified in the release environment.

Perform the Release Readiness Review before any public product release.
