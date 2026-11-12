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

## Temporary visual-only UI/UX review environment

The temporary local review database is `smartbudget_review`, separate from the
ordinary `.env` development database. Its environment file is
`.env.review.local`, ignored by the existing `.env.*.local` Git rule. It selects
that database through `DATABASE_URL` and isolates storage with:

```dotenv
R2_PRODUCT_RELEASES_PREFIX=product-releases-review-20261026
UPLOAD_DIR=uploads-review
PURCHASE_EMAIL_DELIVERY_ENABLED=false
```

Lava.top API credentials are intentionally absent for visual-only review; do
not enable live checkout. Existing R2 configuration supports Admin release
upload and publication under the separate review prefix. Keep that prefix
separate from the normal managed prefix so reconciliation cannot classify
another database's releases as orphaned objects.

In a dedicated PowerShell session, select the existing review environment and
use the normal migration and startup paths:

```powershell
$env:ENV_FILE = ".env.review.local"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe run.py
```

Before migration or startup, ensure no inherited `DATABASE_URL` or provider
environment overrides replace the review file's values. Stop the existing
local listener before starting another process on the same port. This is a
temporary local review setup, not production deployment or live payment
validation. Closing the dedicated session leaves normal `.env` selection intact.

### Temporary external HTTPS access

The validated review endpoint is `https://smartbudget-review.neocitrix.com`,
served by the locally managed named Cloudflare Tunnel `smartbudget-review`
(UUID `aff8bb9a-4a82-4f4b-9596-c718371abf72`). Its local origin is
`http://127.0.0.1:8800`. The dedicated local configuration is
`C:\Users\Admin\.cloudflared\config-smartbudget-review.yml`, with
`protocol: http2` explicitly configured. The tunnel credentials JSON remains
private local material and must not be copied into repository documentation.

The default `C:\Users\Admin\.cloudflared\config.yml` belongs to the separate
Ollama tunnel. Do not reuse or modify it for SmartBudget review.

### Review-only Cloudflare perimeter

A fail-closed WAF custom rule on the review hostname permits only `GET` and
`HEAD` requests to explicitly approved public visual-review routes and
`/static/*`. All other methods and paths are blocked at the Cloudflare edge.
In particular, external access is blocked to `/admin*`, `/v1/*`, `/download/*`,
`/consultation/book/*`, `/docs`, `/redoc`, `/openapi.json`, administrative
product-release routes, and POST checkout. This permits visual inspection,
not external administrative, API, capability, or purchase operations.

A Response Header Transform Rule adds
`X-Robots-Tag: noindex, nofollow, noarchive`. A Cache Rule bypasses cache for
`smartbudget-review.neocitrix.com`.

### Confirmed external validation

Manual checks from outside the local origin verified:

| Check | Observed result |
| --- | --- |
| Public `/` GET | HTTP 200 |
| EN checkout GET | HTTP 200; `sb_lang=en` preserved |
| `/admin` | Cloudflare HTTP 403 |
| POST checkout | Cloudflare HTTP 403 |
| `/v1/health` | Cloudflare HTTP 403 |
| `/download/test` | Cloudflare HTTP 403 |
| Response headers | `X-Robots-Tag` present; `cf-cache-status: DYNAMIC` |
| Five consecutive public root GETs | HTTP 200 for all five |

This evidence validates temporary review access and its review-only perimeter;
it is not production deployment or production security validation.

### VPN and network constraints

Hiddify/VLESS caused unstable long-lived Cloudflare Tunnel edge connections,
with repeated control-stream disconnects and intermittent HTTP 502/520/530
responses. AmneziaWG produced stable review access in the validation run;
prefer AmneziaWG over Hiddify while `cloudflared` is running for review sessions.
Keep `protocol: http2` explicitly configured.

The connectivity pre-check under AmneziaWG found `region1.v2.argotunnel.com`
reachable and `region2.v2.argotunnel.com` unavailable. This reduces network
redundancy and was accepted only for the temporary review environment because
repeated public requests succeeded. It is not suitable evidence of production
deployment readiness.

### Review tunnel cleanup

After the UI/UX review is complete:

1. Stop `cloudflared` for the review tunnel.
2. Remove the review DNS route/hostname.
3. Remove the review-only WAF rule.
4. Remove the review `X-Robots-Tag` transform rule.
5. Remove the review cache-bypass rule.
6. Delete the `smartbudget-review` tunnel if it is no longer needed.
7. Remove the dedicated local review tunnel configuration and credentials only
   after the tunnel is deleted and no longer required.

Do not touch the existing `ha-cloudflare` or `ollama-tunnel` tunnels.

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

After the [Gate 2 review reset](release_readiness.md#gate-2--review-productrelease-artifact-replacement),
independent verification confirmed zero `ProductRelease` references for both old
review objects. The owner confirmed targeted manual deletion of both through
the Cloudflare R2 Dashboard without using `--delete-orphans`.

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

## G13D-1 purchase delivery monitoring

After applying Alembic migrations, run one pass from the repository root
using the configured interpreter and database:

```powershell
.\.venv\Scripts\python.exe -m scripts.monitor_purchase_delivery
```

Exit code 0 means the scan committed, including when it found incidents.
Standard output contains JSON counts for paid Sales scanned, open, opened and
resolved incidents, and open incidents by rule and severity. An operational
failure exits 1 and prints a sanitized JSON error to standard error. The scan
writes only monitoring incidents and makes no provider calls. Development and
review test Sales can produce expected incidents.

Detection depends on when this command runs. Five-minute stall warnings plus
scan cadence and execution time determine detection latency. The
[approved G13D architecture](architecture/commerce_and_delivery.md#purchase-delivery-monitoring-g13d)
covers scheduled monitoring, Lava.top polling, Resend webhook delivery events,
safe recovery, critical alerts, and the external heartbeat. Lava.top recovery
has a separate one-pass command. Scheduled execution and subsequent
integration remain open.

## G13D-2a Lava.top payment recovery

After migrating PostgreSQL, run one pass with the server-owned Lava.top
configuration:

```powershell
.\.venv\Scripts\python.exe -m scripts.recover_lava_top_payments
```

The first lookup is due five minutes after Sale creation. After `NEW` or
`IN_PROGRESS`, check again in five minutes before age one hour, 15 minutes
from one hour to 24 hours, one hour from 24 hours to seven days, and one day
from seven days onward. Age alone never stops polling or changes payment state.

`LAVA_TOP_RECOVERY_MAX_LOOKUPS` defaults to 20.
`LAVA_TOP_RECOVERY_REQUEST_WINDOW_SECONDS` defaults to 120 and limits when new
lookups can start. An in-flight request can finish after that window. Each
pass reserves four slots for Sales aged 24 hours or more at the default
budget, with unused capacity shared between age groups. It processes the
earliest due invoices within each group. HTTP 429 stops the pass and persists
a provider-wide cooldown using `Retry-After` or 15 minutes when unavailable.
Timeouts and provider outages stop the pass and back off globally for
5, 10, 20, then up to 30 minutes.

Exit code 0 returns aggregate JSON for due, processed and deferred lookups by
age, plus sanitized outcome counts. An overlapping invocation skips the pass
and reports `already_running`. An operational failure exits 1 and returns a
sanitized JSON error. Parked invoices stay pending and are excluded from the
automatic due count. Find their internal Sale IDs and review reasons with
this read-only query, then use Sales Admin and the manual verification path:

```sql
SELECT r.sale_id, r.last_checked_at, r.last_outcome
FROM lava_top_payment_recovery AS r
JOIN sales AS s ON s.id = r.sale_id
WHERE s.payment_status = 'pending' AND r.next_check_at IS NULL
ORDER BY r.last_checked_at;
```

The 30-minute detection SLO applies to actively monitored recent purchases
when provider evidence is available and polling capacity is sufficient. Aged
invoices use best-effort detection. Backlogs, provider cooldowns and pauses
for operator review can extend latency. This command is unscheduled.

## G13D-2b Resend webhook operations

The externally verified Resend Forge configuration for `neocitrix.com` has
domain status **Verified** and Forge status **Ready**. Sending is enabled and
receiving is disabled. The sending region is Ireland (`eu-west-1`). The
Return-Path is `mail.neocitrix.com`, with CNAME `mail` pointing to
`send.forge.rmta.net`, proxy mode **DNS Only**, and TTL **Auto**. The existing
production API key remains at **Sending access**. No further DNS or Forge
changes are required. Ireland is the sending region. Resend stores webhook
payloads, message content, delivery logs and account records in the US.
See [Resend's GDPR and data storage policy](https://resend.com/security/gdpr/).

When the public HTTPS endpoint is available, register it through Resend
Dashboard using the [approved event subscription and signing requirements](architecture/commerce_and_delivery.md#g13d-2b-resend-webhook-delivery-monitoring).
The endpoint is `POST /v1/webhooks/resend`. Set the dedicated
`RESEND_WEBHOOK_SIGNING_SECRET` in server-owned configuration. The application
limits requests to 64 KiB and applies a dedicated 120 requests per minute
per-client-IP policy. It acknowledges authenticated events after their receipts
commit, including malformed or unsupported events recorded without payloads.
Use the Dashboard for endpoint management, delivery history and manual replay.
Webhook event history and replay are limited to the account's plan retention
window.
Resend retries failed webhook deliveries. If Resend disables the endpoint,
restore it and re-enable it in the Dashboard before replaying events. Do not
create or use a Full Access key for management or replay. See
[Resend's retry and replay documentation](https://resend.com/docs/webhooks/retries-and-replays).

The five-minute timer is for incident scanning and Lava.top payment recovery.
Resend delivery monitoring uses webhooks. During release validation, verify
live webhook delivery and the Dashboard fallback separately from the
Healthchecks.io heartbeat.

Use the existing monitoring pass to surface deferred confirmation after five
minutes and remove receipts at 90 days from first receipt. Resolve a reviewed
operator-required incident with:

```powershell
.\.venv\Scripts\python.exe -m scripts.resolve_purchase_delivery_incident --incident-id 42 --operator ops --reason "Reviewed provider history" --confirm
```

Use an operator identifier and a reason free of customer data, protected URLs
and tokens. This command records the resolution and leaves email state intact.
Before rollout, review unresolved pre-tag sends. Retrying one with the new tag
can produce an idempotency conflict and require operator reconciliation under
the existing stable-key policy.

## G13D-2c purchase email recovery

Apply the Alembic migration, then use the configured PostgreSQL environment
and interpreter from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.recover_purchase_emails --dry-run
.\.venv\Scripts\python.exe -m scripts.recover_purchase_emails
```

The dry run reports candidates without contacting Resend or changing delivery
state. It previews sending eligibility even when delivery is disabled and
reports the configured sending state. A live pass can still escalate expired
ambiguity while sending is disabled. Exit 0 prints sanitized JSON with due,
selected, deferred and processed counts and outcomes. An overlapping
invocation reports `already_running`. Operational failure exits 1 with a
sanitized error.

`PURCHASE_EMAIL_RECOVERY_PENDING_DELAY_MINUTES` defaults to five minutes.
Each pass selects at most 20 deliveries. It prioritizes expired ambiguity,
then orders by the oldest attempt or creation timestamp and delivery ID.
Retries wait at least ten minutes and use the existing three-attempt ceiling
for automatic recovery. The 23-hour ambiguity boundary applies regardless
of attempts remaining. Explicit operator authorization remains available
through the existing protected flow and emits a sanitized authorization log.

The command is unscheduled. Validate live recovery and include it in the
G13D-3 operational integration before public sales.

## G13 purchase email template cutover

On the legacy release, inspect unfinished deliveries using the target
environment's database.

```sql
SELECT id, sale_id, status, sending_started_at
FROM purchase_email_deliveries
WHERE status IN ('sending', 'reconciliation_required')
ORDER BY id;
```

Resolve any `sending` entries through the existing reconciliation process
before upgrading. Once the 23-hour window has elapsed, the existing Admin retry
action transitions an unresolved attempt to `reconciliation_required` without
contacting Resend. Leave those records subject to the existing explicit
provider reconciliation and resend authorization. An existing delivery keeps
its original idempotency key.

After reconciliation, stop application processes that can start email delivery
and repeat the query. With zero `sending` entries, apply migration
`eb63c5a92f10` and start the G13 application. The migration locks the delivery
table during the check and refuses to change the schema while a `sending`
entry exists. Apply the same operational check before rolling back the renderer.

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

This command is the founder-operated fallback for a known invoice and a live
validation tool. It is not the normal automatic production completion path;
that path is the authenticated Payment-result webhook.

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

On 2026-08-14, the same manual path reconciled real Sale #8 after Lava.top
reported its 100 RUB invoice as `COMPLETED` (50 RUB product plus 50 RUB
consultation). The Sale became paid with exactly one product entitlement and
one consultation entitlement available, the purchase email was sent, and both
protected access pages opened. This validated the bundle path without executing
a live webhook or a browser return from Lava.top.

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

### Manual Lava.top full refund

Use only the protected Sales Admin workflow. SmartBudgetSite supports full-Sale
refunds only and does not call a Lava.top refund API.

Lava.top support confirms that only one refund is possible per provider
transaction; do not attempt a second provider refund. See the authoritative
[Lava.top refund contract](architecture/commerce_and_delivery.md#lavatop-mvp-contract)
for confirmed capabilities, settlement timing, and pending verification research.

1. Open the paid Sale and verify its exact amount, currency, provider, and
   external payment ID.
2. Select **Start refund** and accept the explicit acknowledgement. This creates
   one `pending` `RefundOperation`; it does not issue money or change the Sale
   from `paid`.
3. In Lava.top Sales, manually refund the exact full Sale amount. Do not use a
   partial amount and do not create another SmartBudgetSite operation.
4. Verify the amount and provider-side refund evidence in Lava.top. The observed
   `SENT` label is provider UI metadata, not a SmartBudgetSite lifecycle state
   and not proof of bank/card settlement.
5. Return to the Sale and accept **I verified the full refund in Lava.top.** Only
   this action confirms the internal operation, changes the Sale to `refunded`,
   and revokes future access atomically.
6. If the Admin reports a conflict or persistence error, do not edit SQL or
   start another refund. Preserve the provider evidence and investigate the
   existing Sale/refund operation.

### Pre-release refund operations

Complete the bounded R42 refund and R53 request capabilities after G13D and
before public sales. The [approved refund rules](architecture/commerce_and_delivery.md#approved-refund-rules-and-customer-requests-d4)
govern eligibility, amounts, item access and customer confirmations.

1. Record the customer request, acknowledge receipt, and provide the operator
   with backend-owned purchase context and the status of the voluntary deadline.
2. Prepare the exact refund amount using the applicable rules and purchased
   item snapshots. Flag exceptions for operator review.
3. Have the operator execute the refund manually in Lava.top and verify
   provider evidence before confirming the internal outcome. Lava.top supports
   one refund per transaction and currently offers no refund initiation API.
4. Record the evidence and follow-up. Use the approved recovery procedure for
   conflicting evidence or a later required refund that the original provider
   path cannot process.

`SENT` is evidence of provider-side processing. Final bank or card settlement
requires separate evidence. Authoritative machine-readable refund verification
remains unconfirmed. Optional assisted tooling can be reviewed separately.

## Production VPS provisioning (2026-11-12)

### Status and infrastructure

A dedicated Vultr VPS has been provisioned for the future
SmartBudgetSite production environment.

This is infrastructure preparation only, not an application deployment
or evidence of production readiness.

- Provider: Vultr.
- Instance label: `SmartBudgetSite Production`.
- Hostname: `smartbudgetsite-prod`.
- Region: Amsterdam, Netherlands.
- Plan: Regular Cloud Compute, 2 vCPU, 4 GB RAM, 80 GB SSD.
- Operating system: Ubuntu 24.04 LTS.
- Automatic Vultr instance backups: enabled; restore not yet tested.
- Expected monthly infrastructure cost at provisioning: USD 24
  (USD 20 server + USD 4 backups).
- The production VPS is separate from the existing VPN server.

Infrastructure access details and credentials are stored privately in
KeePassXC and must not be committed to the repository.

### Verified initial configuration

The following checks and configuration steps were completed:

- `cloud-init status --long` reported `done` with no errors.
- The server's ED25519 SSH host fingerprint was independently
  verified through the Vultr console before the first SSH connection.
- The administrative user `andrey` was created.
- SSH public-key authentication for `andrey` was verified.
- `sudo` access was verified successfully.
- SSH hardening was configured through
  `/etc/ssh/sshd_config.d/00-smartbudget-hardening.conf`:
  - `PermitRootLogin no`
  - `PasswordAuthentication no`
  - `PubkeyAuthentication yes`
  - `KbdInteractiveAuthentication no`
- `sshd -t` passed and effective settings were checked with `sshd -T`.
- The SSH service was reloaded successfully and remained active.
- A fresh SSH connection as `andrey` succeeded after hardening.
- Original SSH configuration was backed up under
  `/root/ssh-hardening-backup/`.

### Network access

The Vultr Firewall group `SmartBudgetSite Production` restricts
inbound connections:

- TCP 22: allowed only from the existing VPN server's public
  egress address, `95.179.135.13/32`.
- TCP 80 and 443: allowed from all IPv4 addresses for future
  public HTTP/HTTPS service.
- Other unsolicited inbound traffic: blocked by the Vultr Firewall.
- PostgreSQL port 5432 is not publicly exposed.

The host-level firewall configuration has not yet been validated.

Administrative SSH access currently depends on the VPN egress IP.
If that IP changes or the VPN becomes unavailable, update the
Vultr Firewall rule through the Vultr control panel before
attempting a new SSH connection.

The Vultr web console is an alternative administrative access path.
Do not disable or alter emergency access without validating recovery.

### System updates

- Ubuntu package indexes were refreshed on 2026-11-12.
- Available security and system updates were installed.
- Kernel `6.8.0-149-generic` was installed through `apt-get full-upgrade`.
- The VPS was rebooted successfully.
- SSH connectivity as `andrey` was verified after the reboot.
- `uname -r` confirmed the running kernel is `6.8.0-149-generic`.
- `systemctl is-active ssh` returned `active`.
- `apt-get check` completed without dependency errors.
- Three packages were deferred by Ubuntu phased updates;
  no forced installation was attempted.

### Pending deployment work

The following work has not been completed:

- Installation and configuration of the container runtime.
- Production PostgreSQL provisioning and database backups.
- Application deployment and process lifecycle configuration.
- Reverse proxy, DNS, HTTPS, and production perimeter validation.
- Production migrations, health checks, monitoring, and recovery tests.
- End-to-end production payment and delivery validation.

Vultr instance backups alone are not considered sufficient evidence
of application/database recovery readiness.

Production application deployment remains deferred until the
applicable pre-deployment release gates are satisfied, as defined
in `release_readiness.md`.

This infrastructure preparation does not complete `REL-002`,
`OPS-001`, `SEC-012`, or any live integration validation gate.

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

Verify G13D's five-minute schedule, bounded Lava.top polling, Resend webhook
delivery and replay, safe recovery and operator escalation, critical alerts,
and Healthchecks.io heartbeat. Validate the 30-minute critical detection SLO
against observable evidence and record
provider visibility limits. Walk through refund intake, operator execution,
confirmation, and recovery.
Verify consultation capacity warnings, purchase availability at the approved
limit, and restoration of availability under the approved rules. Confirm
operators can handle routine work and exceptions without jeopardizing customer
obligations.

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
