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
| `4000` | Internal SmartBudgetSite listener in the production environment | Production Docker configuration | Application bind port |
| `80`, `443` | Caddy HTTP and HTTPS listeners | Production Docker configuration | Public IPv4 host ports |
| `5433` | Local host access to the development PostgreSQL container | Local Docker development | Host-side database port mapping |
| `5432` | PostgreSQL listener inside the container | Local Docker network/container | Container port |
| `5173` | Allowed origin for a separately run frontend development server | Local frontend development only | Frontend development origin; not a SmartBudgetSite bind port |
| `587` | Configured outbound SMTP submission endpoint | Environments using the example SMTP configuration | External provider port; not a local bind port |

Development Compose maps host port `5433` to PostgreSQL container port `5432`.
Production Compose publishes only Caddy's HTTP and HTTPS ports.

## Production Docker configuration (REL-002)

`compose.prod.yml` uses `Dockerfile.prod` for the FastAPI image, PostgreSQL 16
for the database and the official Caddy 2.11 image with
`deploy/Caddyfile.prod` for automatic HTTPS. Use `-f compose.prod.yml` explicitly
from the repository root. Its project name is `smartbudget-production`.
Development still uses `docker-compose.yml` and `python run.py`.

The Caddy service belongs to the `public` Compose profile.
A default Compose startup does not activate the public reverse proxy.
Enable the `public` profile explicitly only after the required SEC-012
perimeter controls, DNS/HTTPS configuration, and pre-exposure checks
have been approved and validated. Do not treat a successful container
startup as authorization to expose the application publicly.

### Runtime and configuration contract

- FastAPI runs as an unprivileged user with `APP_ENV=prod`, port `4000`,
  exactly one Uvicorn worker and reload disabled. The application rate limiter
  remains enabled. PostgreSQL and FastAPI have no published host ports.
- FastAPI's production `TrustedHostMiddleware` accepts the configured
  `SMARTBUDGET_HOST` and `127.0.0.1` for the container healthcheck. It rejects
  other hosts with HTTP 400. Development and test can use arbitrary local hosts.
- Only FastAPI and PostgreSQL join the internal database network. FastAPI and
  Caddy share the proxy bridge, which also provides outbound access for
  application integrations and Caddy's certificate automation. Keep other
  containers off the proxy bridge and verify its `172.30.192.0/28` subnet
  does not overlap a route on the deployment host.
- Caddy is the direct public IPv4 edge. It strips incoming `Forwarded`,
  `X-Forwarded-*` and `X-Real-IP` values. Its reverse proxy sets the standard
  forwarded client IP, scheme and host from the connection and request.
  Uvicorn runs with `--no-proxy-headers` so the production ASGI middleware sees
  the TCP peer. The middleware accepts one valid IP and one HTTP(S) scheme
  from Caddy's fixed bridge address (`172.30.192.2`) and saves that socket
  address for the internal perimeter check. Compose supplies the same address
  to Caddy and to the app as `SMARTBUDGET_CADDY_PEER`.
  Keep DNS IPv4-only for this topology. Adding IPv6 ingress, a CDN or another
  proxy requires separate client-IP and trust-boundary validation.
- Caddy adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  and `Strict-Transport-Security: max-age=31536000` to proxied HTTPS responses.
  HSTS is scoped to the configured hostname. Caddy defaults `Referrer-Policy`
  to `strict-origin-when-cross-origin` when the upstream sends no policy.
  Capability responses retain `Referrer-Policy: no-referrer`.
- The `postgres_data`, `feedback_data`, `caddy_data` and `caddy_config` named
  volumes retain database files, private uploads, certificate state and Caddy
  configuration state across container replacement. Keep the same project
  name on redeploy and omit `--volumes` from teardown. Keep the upload volume
  writable by the app's UID/GID `10001` when restoring it. Caddy has no mount
  of the upload volume.
- The database probe checks that the server accepts TCP connections. Compose
  starts the app after that probe passes, and Caddy after the app responds on
  its loopback `/v1/health`. These probes cover process startup only.
  Database authentication, schema, persistence, public HTTPS and provider
  readiness require separate checks.

Use two restricted runtime files, for example `/etc/smartbudget/compose.env`
and `/etc/smartbudget/app.env`. Base them on `.env.production.example` and
`.env.production.app.example` respectively. Point `SMARTBUDGET_APP_ENV_FILE`
at the absolute app file. The Compose file supplies the database bootstrap
values only to PostgreSQL and passes the bare `SMARTBUDGET_HOST` DNS hostname
to Caddy and FastAPI. Production application startup requires a valid hostname.
Use the corresponding `https://` origin as the app's `PUBLIC_BASE_URL`.
Keep private settings outside Git and the image. Use the production examples
as the starting point and consult `.env.example` for the existing optional
provider settings. Keep delivery switches off until their prerequisites are
verified. Use a dedicated shell with the intended environment and avoid
printing a rendered Compose configuration containing real values.

The database bootstrap login is separate from the app login. Provision or
restore the `POSTGRES_DB` database with a dedicated non-superuser database
owner before the first application migration. Set the app's `DATABASE_URL`
to use that role with `postgresql+psycopg`, host `db` and port `5432`.
Use a generated URL-safe password such as random hex to avoid URL escapes in
the existing Alembic configuration interpolation. PostgreSQL bootstrap
environment values initialize an empty volume only. Verify the roles and
credentials in the target database when using an existing volume.

### Local verification

In a dedicated PowerShell session, use only the example files and a synthetic
database value for Compose interpolation. This check creates no containers
and avoids dumping the rendered environment.

```powershell
$env:SMARTBUDGET_APP_ENV_FILE = ".env.production.app.example"
$env:POSTGRES_PASSWORD = "local-config-check-only"
docker compose --env-file .env.production.example -f compose.prod.yml config --quiet
```

When a matching Caddy binary or image is already available locally, validate
the Caddyfile with the example hostname. For the cached image, use an
isolated validation process without published ports or network access.

```powershell
$caddyConfig = Join-Path $PWD.Path "deploy/Caddyfile.prod"
docker run --rm --pull never --network none --env SMARTBUDGET_HOST=smartbudget.example.invalid --mount "type=bind,source=$caddyConfig,target=/etc/caddy/Caddyfile,readonly" caddy:2.11-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Set `SMARTBUDGET_TEST_CADDY=1` when running `tests/test_production_perimeter.py`
with the [Codex pytest options](#codex-pytest-validation-environment) to check
response headers, HTTPS redirects, and perimeter authorization routing in the
cached Caddy image. The test uses internal TLS and a stub upstream inside a
container with no external network access or published ports. Also set
`SMARTBUDGET_TEST_APP_IMAGE` to a cached build of `Dockerfile.prod` to run the
real Caddy-to-Uvicorn test. It mounts the current app and Caddyfile, uses the
Compose Uvicorn flags on an internal Docker network, and publishes no ports.

In an authorized disposable release environment, validate the image build,
application upload permissions and volume retention across recreation.
Use an external client on the intended Linux host topology to verify that
only Caddy is reachable, that the app observes the actual client IP and
HTTPS scheme, and that client-provided forwarding headers do not change its
rate-limit identity. Local Docker Desktop behavior cannot establish those
Linux ingress results.

### Controlled migrations and release prerequisites

The application startup command runs Uvicorn only. During an authorized
deployment window, build the app image, start and check the database, and
complete the backup and database-role checks. Run migration commands as
separate one-off app containers on the private database network with the
intended deployment settings. Record the starting revision and plan recovery
before applying changes.

```bash
docker compose --env-file /etc/smartbudget/compose.env -f compose.prod.yml run --rm --no-deps app python -m alembic current
docker compose --env-file /etc/smartbudget/compose.env -f compose.prod.yml run --rm --no-deps app python -m alembic upgrade head
docker compose --env-file /etc/smartbudget/compose.env -f compose.prod.yml run --rm --no-deps app python -m alembic current
```

Confirm the expected revision before serving traffic. The private PostgreSQL
deployment has been verified. Public exposure remains closed, and the
following REL-002 and related release obligations remain open.

- **OPS-001 backup and restore.** Continue production backup validation
  and the remaining recovery work in the [OPS-001 runbook](#automated-postgresql-backup-and-retention-ops-001).
  Treat certificate storage as sensitive.
- **SEC-012 perimeter.** Validate the configured trusted hosts, exact Caddy
  proxy trust, forwarding-header sanitization, application and perimeter
  quotas, HTTPS security headers, HSTS, and capability-safe logging in the
  release environment before public exposure.
- **DNS and HTTPS.** Verify the public DNS A record, host reachability on
  TCP 80/443, certificate issuance and renewal, and HTTPS redirects.
- **Live integrations.** Verify payment, storage, email and Calendly in the
  release environment using the approved validation paths.
- **Operational monitoring.** Validate production startup, recovery, the
  scheduled jobs and their external heartbeats, plus host, database and
  public availability monitoring under G13D-3. Container health is only one
  input to that work.

## Automated PostgreSQL backup and retention (OPS-001)

### Verified manual recovery evidence

On 2026-11-24, the owner verified encrypted upload and download through the
existing `gdrive_crypt` remote, plaintext SHA-256 equality and an isolated
PostgreSQL 16 restore of the 2026-11-23 post-migration dump. The restored
database contained 29 tables and Alembic revision `9f3b1a7c2d84`. The
temporary database and test files were removed.

### Verified production automation and restore

The production `smartbudget-postgres-backup` service and timer were installed
and validated. The timer is enabled and active for 03:00 UTC daily with
`Persistent=true`. A manual systemd start succeeded on 2026-11-24.
Scheduled runs on 2026-11-25 and 2026-11-26 each succeeded in about 16 seconds.
Local and encrypted off-site archive inventories were independently confirmed.
Local archives are root-owned with mode `0600` in the root-owned
`/var/backups/smartbudget` directory with mode `0700`. Production pruning and
catch-up after downtime remain unverified.

The owner downloaded an automated archive created on 2026-11-24 from Google
Drive, independently verified its SHA-256 and restored it into an isolated
PostgreSQL database. The restore contained 29 tables at Alembic revision
`9f3b1a7c2d84`. The temporary database and downloaded archive were removed.

### Approved schedule and retention

- Run daily at 03:00 UTC. The persistent systemd timer runs once on return
  after a missed schedule.
- Keep seven successful automated local archives and fifteen successful
  encrypted off-site archives. The job uses PostgreSQL CUSTOM format and
  orders backups by the UTC timestamp in
  `smartbudget-auto-YYYYMMDDTHHMMSSffffffZ.dump`.
- Local archives live under `/var/backups/smartbudget`. Off-site archives
  use `gdrive_crypt:postgresql-automated`, a dedicated directory under the
  existing encrypted Drive remote. Preserve the existing OAuth and crypt
  settings. Manual, pre-migration, post-migration and unrelated files are
  outside automated retention.

### Job behavior and prerequisites

The host runs `python3 -m scripts.backup_postgres` from `/opt/smartbudget`.
It uses `docker compose` with `compose.prod.yml` and the existing private
`/etc/smartbudget/compose.env`. It executes `pg_dump` in the running `db`
service as the `smartbudget` database role through the container's local
PostgreSQL socket. Verify that this role can dump the app database without
a password prompt using existing socket authentication. Keep both production
environment files root-only. The job does not read, copy or log the app
database password, and it does not fall back to the bootstrap role.

Before installing the rendered unit, verify the host's Python 3.11+
interpreter, Compose access, existing root rclone configuration and
available disk space. Restrict write access to the deployment checkout to
authorized administrators because the unit runs it as root. The job requires
a real backup directory owned by the service user with no group or other
permissions. Use mode `0700`. If the root rclone config is outside rclone's
default location, set `RCLONE_CONFIG` to the existing private path in a local
systemd drop-in. Keep credentials
and encryption settings outside the repository and unit templates.

The script holds a nonblocking host file lock for the entire run.
It creates a private temporary archive and runs `pg_restore --file=/dev/null`
to read and decompress it without restoring a database. It uploads a
uniquely named pending object, streams the decrypted bytes back through
rclone and compares SHA-256. It then promotes that verified object within
the same encrypted remote and atomically publishes the local archive.
Both retention plans must be valid before the job removes prior archives.
Remote listing errors, malformed or duplicate entries, and a missing or
out-of-order new backup fail closed. A failed deletion stops the remaining
retention work and can leave extra backups until a subsequent successful run.

The job deletes exact expired names using `rclone deletefile
--drive-use-trash=false`. This bypasses Drive trash for the targeted objects.
It makes no account-wide trash changes. Temporary files are removed on
handled failures and the job attempts exact-name cleanup of its own pending
object. After an abrupt interruption or cleanup failure, review the journal
and reconcile leftover temporary files or pending objects individually while
the job is inactive. These artifacts are excluded from retention counts.
The selected rclone commands and Drive flag are present in upstream
1.60.1. Validate the behavior with the installed `1.60.1-DEV` build and
the actual permission scope before relying on the scheduled policy.

### Systemd installation and monitoring

When reinstalling, render the reviewed
`deploy/systemd/smartbudget-postgres-backup.service.in` with the approved
production values and use the matching `smartbudget-postgres-backup.timer`.

| Placeholder | Production value |
| --- | --- |
| `@JOB_USER@` | `root` |
| `@JOB_WORKING_DIRECTORY@` | `/opt/smartbudget` |
| `@PYTHON_COMMAND@` | `/usr/bin/python3` |

The backup job uses a 30-second stop timeout. The extra time beyond the
standard 15 seconds allows the interrupted job to remove local temporary
files and attempt to remove its pending encrypted upload before systemd
forces termination.

On reinstall, validate the rendered files with `systemd-analyze verify` and
the schedule with `systemd-analyze calendar '*-*-* 03:00:00 UTC'`. Confirm the
non-public database deployment before enablement. Keep the public Compose
profile disabled.

Production monitoring uses the Better Stack heartbeat **SmartBudgetSite —
PostgreSQL Backup**, with a 24-hour interval, a one-hour grace period, and
email notifications. The job exits `0` and logs `status=completed` on
success. Failures exit `1` and a lock skip exits `75`. The production
systemd drop-in at
`/etc/systemd/system/smartbudget-postgres-backup.service.d/override.conf`
uses a success-only `ExecStartPost`. Failed executions are recorded in the
systemd journal. Better Stack sends a missed-heartbeat alert only after the
configured interval and grace period have elapsed without a success heartbeat.

```ini
[Service]
ExecStartPost=/usr/bin/curl --silent --fail --output /dev/null --max-time 10 --config /etc/smartbudget/postgres-backup-heartbeat.curl
```

The curl configuration is root-owned with mode `0600`. Use this format with
the private heartbeat URL.

```ini
url = "YOUR_HEARTBEAT_URL"
```

The KeePassXC entry is
**SmartBudgetSite — Better Stack PostgreSQL Heartbeat**. Rotate the URL before
commercial release because it was inadvertently exposed during configuration
review. Update the private curl file and the vault entry, then confirm receipt
with the new URL.

Better Stack received the production heartbeat after a manually initiated
systemd backup, and the test notification email arrived.
A separate temporary heartbeat with a one-minute interval and one-minute
grace period detected a missed heartbeat, created an incident, sent email,
and resolved the incident automatically after the next heartbeat. The
temporary heartbeat and demonstration monitor were removed.

Verify heartbeat receipt from a scheduled backup on 2026-11-27 or later.
Production backup failure monitoring still needs validation. Check the
sanitized failure stage with
`journalctl -u smartbudget-postgres-backup.service`, confirm the failed run
sends no success heartbeat, and verify the independent email alert after
the configured interval and grace period expire.
Before public commercial release, confirm eligibility for the intended Better
Stack plan. The provider describes its free tier as intended for personal
projects. [Better Stack pricing](https://betterstack.com/pricing)

### Independent Windows recovery from Google Drive

Recovery requires access to the original Google account and the original
dedicated OAuth desktop client. Use a new rclone configuration and obtain
fresh OAuth authorization. The verified procedure used Windows rclone
v1.76.0 and KeePassXC.

| KeePassXC entry | Recovery value |
| --- | --- |
| `SmartBudgetSite — Account Email` | Original Google account for browser authorization |
| `SmartBudgetSite — Google Drive OAuth` | OAuth client ID in Username and client secret in Password |
| `SmartBudgetSite — rclone Crypt Encryption` | Original primary password in Password and original second password in the `rclone_password2` custom attribute |

1. Create an empty, access-restricted Windows recovery directory. Start the
   interactive setup with `rclone --config <recovery-config-path> config`
   and use that same isolated config path in every command.
2. Create a Google Drive remote named `gdrive` using the original desktop
   client ID and secret. Select `drive.file` scope and authorize in the
   browser with the original Google account. Keep the new OAuth tokens in the
   isolated config.
3. Create a crypt remote named `gdrive_crypt` targeting
   `gdrive:SmartBudgetSite/backups-encrypted`. Set filename encryption to
   `standard` and directory name encryption to `true`. Enter both original
   encryption passwords in the interactive setup. Preserve the existing
   production encryption parameters. [rclone Drive configuration](https://rclone.org/drive/) · [rclone crypt configuration](https://rclone.org/crypt/)
4. List the automated archives through the crypt remote and select an
   available archive. Download it to the private recovery directory and
   compare its SHA-256 with an independently recorded reference if one is
   available for that archive.

```powershell
$recoveryDir = "C:\path\to\private\recovery"
$recoveryConfig = Join-Path $recoveryDir "rclone-recovery.conf"
rclone --config $recoveryConfig lsf gdrive_crypt:postgresql-automated --files-only
$archive = Read-Host "Enter an available archive filename from the listing"
$download = Join-Path $recoveryDir $archive
rclone --config $recoveryConfig copyto "gdrive_crypt:postgresql-automated/$archive" $download
Get-FileHash -Algorithm SHA256 -LiteralPath $download
```

On 2026-11-26, this isolated setup listed existing encrypted objects, decrypted
the filenames, and accessed all five automated archives without copying VPS
configuration or OAuth tokens. The archive
`smartbudget-auto-20261124T182037355263Z.dump` matched the independently
verified SHA-256
`6f1f438274b96ae26a1b5ada38bb3f1ce1d54338a57181482104ea31ff98214b`.
The filename and checksum are historical verification evidence. Retention
will eventually remove that archive. The owner removed the temporary
configuration and downloaded archive.

Independent reference hashes are currently retained for selected archives
only, so a later download may lack a reference for an independent SHA-256
comparison. Before publishing each completed backup, the job reads back the
decrypted upload and compares its SHA-256 with the local archive. rclone crypt
separately authenticates the encrypted data as it decrypts it.

Keep secrets out of command arguments and reports. Perform any database restore
against an isolated target and remove the recovery artifacts when finished.

### Remaining OPS-001 obligations

- Verify production pruning of both local and encrypted off-site archives at
  the approved retention counts and persistent catch-up after downtime.
- Verify the scheduled heartbeat, production failure monitoring, URL
  rotation and commercial plan eligibility.
- Verify backup and recovery for private feedback attachments, object storage
  and deployment configuration, and independently verify the KeePassXC
  database backup.
- Validate full infrastructure disaster recovery.

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

G15-A Seller Information uses `SELLER_ADDRESS_RU` and `SELLER_ADDRESS_EN`
for the localized representations of the same complete geographical address,
and `SELLER_CONTACT_PHONE` for the shared contact telephone. Add the
owner-supplied values securely to the application's release environment,
outside version control. All three settings must contain non-blank text for
`/legal/seller-information` and the neutral footer link to appear. Incomplete
configuration hides the footer link and yields HTTP 404 on direct requests.
Keep development values empty or fictional and verify both languages and the
footer link after configuring the release environment.

G15-B uses `REFUND_POLICY_PUBLICATION_DATE` for the public policy's displayed
last-updated date. Keep it blank until the approved publication rollout and
the [publication prerequisites](release_readiness.md#refund--cancellation-policy-and-consent--mandatory-pre-sale-gate)
are satisfied. At rollout, set the approved date as `YYYY-MM-DD` in the
release environment. A configured date makes the policy available immediately
when the seller details are complete, even if the date is in the future.
Invalid non-blank dates fail Settings validation. With a blank date or
incomplete seller details, `/legal/refund-policy` returns HTTP 404 and its
footer link is hidden. After configuring publication, verify the date, both
languages, and the Refund Request, Legal Information and Feedback links.

`BUNDLE_CHECKOUT_ENABLED` defaults to `false`. Keep it false for the first
public release. It controls new public product-plus-consultation purchases.
Product-only and standalone consultation checkout use separate Sales and
payments. Reconciliation, fulfillment, email and refunds for existing Sales
continue under their original composition. Production reactivation requires
explicit owner approval and provider, refund, regression and operational
validation before enabling the setting.

Purchase-email delivery is controlled by
`PURCHASE_EMAIL_DELIVERY_ENABLED`. When enabled, `RESEND_API_KEY`,
`MAIL_FROM_EMAIL`, `MAIL_FROM_NAME`, and an absolute server-owned
`PUBLIC_BASE_URL` are required at startup. `PUBLIC_BASE_URL` owns customer
download and consultation link construction. Keep delivery disabled in local
environments unless a deliberate provider send is intended. Automated tests
always use fake transports.

When `LAVA_TOP_API_KEY` is configured in production, `PUBLIC_BASE_URL` must be
the HTTPS origin served by `SMARTBUDGET_HOST`, regardless of the email switch.
For example, `SMARTBUDGET_HOST=shop.example.test` uses
`PUBLIC_BASE_URL=https://shop.example.test`. A root slash and explicit port
443 are accepted. The URL must omit credentials, query strings, and fragments.
Each final return URL must fit Lava.top's 512-character limit. Local development
can use an HTTP base URL. Checkout omits the return fields when the local base
URL is HTTP or unset.

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

The production Docker Caddyfile leaves HTTP access logging disabled and
excludes HTTP and upstream request error logs. It does not cache responses.
The deployed reverse proxy and any CDN must:

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
`RATE_LIMIT_MAX_IDENTITIES` defaults to 10,000 and must be positive. It bounds
application identities and separately bounds perimeter policy/IP buckets.
Thresholds are version-controlled. Both limiters are process-local.

Initial production must run exactly one application worker. Multi-worker
production is unsupported until a shared atomic limiter backend is approved.
Restarting the process resets application and perimeter counters. Application
rate limiting remains mandatory.

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
| consultation Share POST | 10/15 min per IP and 5/15 min per capability HMAC |
| unsupported booking methods | 10/15 min per IP and 5/15 min per capability HMAC |
| admin authentication | shared 5/15 min per IP across login and invalid-cookie access |
| Calendly pre-verification | 120/min per IP |
| Calendly post-verification | 300/5 min provider-wide and 10/3 min per signature HMAC |
| Lava.top pre-verification | 120/min per IP |
| Lava.top post-verification | 300/5 min provider-wide |

Caddy uses `forward_auth` for the nine groups below. They share a global
rolling limit of 3,000 admissions per 60 seconds. Each group also has an
independent per-client token bucket, initially full to the listed burst and
refilled at the listed rate. IPv4 uses `/32` and IPv6 uses `/64`.

| Boundary | Per minute | Burst |
|---|---:|---:|
| `POST /v1/feedback` | 10 | 5 |
| `POST /v1/check-purchase` | 30 | 10 |
| `GET /download/{token}` family | 120 | 20 |
| `POST /download/{token}` family | 30 | 10 |
| `/consultation/book/{token}` family | 120 | 20 |
| `POST /admin/login` | 20 | 5 |
| Generic Admin | 120 | 20 |
| `POST /v1/webhooks/calendly` | 300 | 100 |
| `POST /v1/webhooks/lava-top/payment-result` | 300 | 100 |

Generic Admin covers `/admin` and `/admin/*` except the separate login POST.
It also covers `GET /v1/feedback/recent`, `PATCH /v1/feedback/{feedback_id}/resolve`,
`GET` and `POST /products/{product_id}/releases/new`,
`GET /products/{product_id}/releases`, and
`POST /products/{product_id}/releases/{release_id}/publish`.

Ordinary public pages, static assets, and healthchecks skip perimeter checks.
Caddy rejects public requests to the authorization endpoint. Its internal
request preserves `Host` for TrustedHost and supplies the socket client IP,
scheme, and fixed policy name. It omits the original URI, query, body, and
other client headers. FastAPI checks the saved TCP peer and hashes the
validated client IP. The authorization request consumes perimeter quota only.
An admitted original request still runs through the application policies.

Perimeter denials return HTTP 429 and an integer `Retry-After`. Limiter
failure or exhausted storage returns HTTP 503. The middleware rejects
malformed, missing, or ambiguous forwarding values from the trusted peer with
HTTP 400. Caddy stops forwarding if authorization fails. Capability quota
denials and limiter errors retain the SEC-009 cache and referrer headers.

The application limiter uses the validated ASGI `request.client.host`.
It never parses `Forwarded` or `X-Forwarded-For`. IPv4 is canonicalized normally
and IPv6 is grouped by `/64`, then the identity is HMAC-protected before storage.
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

Release-environment validation must confirm both quota layers, the global cap,
HTTP 429 and `Retry-After` through Caddy, trusted-header handling, internal
endpoint isolation, the one-worker process model, and continued SEC-009
logging/cache behavior.

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

When an HTTPS public base is configured, checkout supplies all three Lava.top
return URLs with the persisted purchase language. The result page uses only
the exact returned `invoiceId` to read one payment status from the existing
provider/invoice index. Missing, malformed, or ambiguous identifiers skip the
database lookup. Browser `status` is ignored. The result has `no-store` and
`no-referrer`, and the language switch carries only `lang`. Access logging
continues to omit the query string.

Mocked checkout and local browser regressions cover the implemented return
flow. Release validation still needs the real hosted success, failure, and
cancellation behaviors and a refresh after authoritative confirmation. Verify
the customer journey under REL-001 in the deployed HTTPS environment.

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

Resend delivery monitoring uses webhooks. During release validation, verify
live webhook delivery and the Dashboard fallback separately from the
Better Stack scheduled-job heartbeat.

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

## G13D-3 operational monitoring target

G13D-3a implements the PostgreSQL outbox. G13D-3b adds the one-pass
Alert Dispatcher, which invokes materialization itself. G13D-3c prepares
repository-managed unit templates. Installation and live validation remain open.

```powershell
.\.venv\Scripts\python.exe -m scripts.dispatch_purchase_alerts --dry-run
```

Dry-run inspects existing outbox candidates without writing or sending. Live
dispatch uses the same command without `--dry-run` and requires
`PURCHASE_ALERT_DELIVERY_ENABLED=true`, which defaults to false. Telegram uses
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. SMTP uses the existing
`MAIL_SMTP_*` settings, `MAIL_FROM_EMAIL`, and `ADMIN_NOTIFICATION_EMAIL`.
SMTP alert delivery requires STARTTLS with certificate and hostname verification.
The dispatcher processes up to 20 incidents per pass and attempts each due
channel at most once per incident. It reports aggregate outcomes. Timeouts
can be ambiguous, so a subsequent retry or fallback can deliver a duplicate.

### G13D-3c systemd unit templates

The four pairs are in [deploy/systemd](../deploy/systemd). Calendar times are UTC.

| Job | Unit stem | Interval and offset | Start timeout |
| --- | --- | --- | --- |
| Incident Scanner | `smartbudget-incident-scanner` | Every 5 minutes at :00, starting at minute 0 | 60 seconds |
| Lava.top Recovery | `smartbudget-lava-top-recovery` | Every 5 minutes at :00, starting at minute 1 | 240 seconds |
| Purchase Email Recovery | `smartbudget-purchase-email-recovery` | Every 5 minutes at :00, starting at minute 2 | 300 seconds |
| Alert Dispatcher | `smartbudget-alert-dispatcher` | Every minute at :30 | 600 seconds |

The scanner is database-only. Lava.top recovery stops initiating lookups after
at most 120 seconds and can still finish a lookup and fulfillment with initial
email dispatch. Email recovery can attempt 20 sends per pass. Alert dispatch
can process 20 incidents with up to two channels each, including SMTP setup,
authentication, and message submission. The unit timeouts bound whole passes.
The same service then runs the capacity pass, which can attempt up to two
channels for each of five capacity episodes.
Network timeouts apply to individual operations. Validate these initial budgets
under deployed load, particularly when a pass can exceed its interval.

Each timer activates its matching oneshot. A running service is not started
again by its timer. `Restart=no` leaves the next activation to the calendar,
and `Persistent=false` prevents replay of calendar ticks missed while the timer
was inactive. Offsets separate start times, while different jobs may still
run concurrently. Each service has a 15-second stop timeout.

Resolve these placeholders in each `.service.in` during REL-002, then save it
with the `.service` suffix. The `.timer` files need no substitution.

| Placeholder | Deployment value |
| --- | --- |
| `@JOB_USER@` | Host service account authorized to run the chosen job command |
| `@JOB_WORKING_DIRECTORY@` | Absolute host directory from which the job command runs |
| `@PYTHON_COMMAND@` | Absolute Python executable for a host deployment, or the approved absolute container execution command and arguments through the container's Python executable |

Preserve the `-m scripts.…` suffix and use systemd command quoting. The
container option must run in the chosen application context and propagate
exit status and termination so timeout cleanup cannot leave a detached job.
REL-002 must also decide how the job receives server-owned settings, how
application and database readiness are established, and what dependencies
the rendered unit needs. Keep secrets outside unit files and Git. The
production app image includes the existing Python job modules. Compose
starts no job timers.

Before later installation, verify the selected runtime, account access,
working directory, migrated PostgreSQL database, and provider settings.
Run `systemd-analyze verify` on the rendered services and matching timers and
`systemd-analyze calendar` on each calendar expression. In an isolated release
validation environment, exercise safe CLI invocations and validate active-run
non-overlap, timeouts, and the next timer activation after failure or reboot.
Email recovery and alert dispatch support `--dry-run`. The scanner writes
incidents and Lava.top recovery has no dry run, so use a disposable database
and mocked provider transport for those checks.

During REL-002, install the verified pairs, reload systemd, and enable the
timers after prerequisites and operational safeguards are in place. Use
`systemctl list-timers`, `systemctl status`, and `journalctl -u` to check
activation, exit codes, and sanitized CLI summaries. For failed or missed
runs, check readiness, runtime permissions, configured delivery switches,
the service timeout, and the next calendar activation. The templates keep
the existing CLI safety switches and send stdout and stderr to the journal.

Stagger the scheduled runs, prevent overlapping executions of each job, and
keep their failures independent. Use Better Stack for external scheduled-job
heartbeats and a separate check for public HTTP/HTTPS availability. Verify
that missed-job and availability failures can be detected even when the local
Alert Dispatcher is unavailable.

Measure execution duration, last successful execution, failed, missed, and
overlapping executions, due and deferred work counts, backlog size and oldest
item age, retry and provider-error outcomes, and notification delivery
failures. Record execution outcomes and sanitized diagnostics.

| Surface | Required measurements |
| --- | --- |
| VPS | CPU, RAM and swap, free disk space, disk I/O and I/O wait |
| PostgreSQL | Active connections, long-running queries, locks and deadlocks, database growth |
| Public application | External HTTP/HTTPS availability, response latency, HTTP 5xx errors |

Use the [verified Vultr monitoring and pre-deployment baseline](#vultr-monitoring-and-pre-deployment-baseline)
as a starting point. Select additional tools and production thresholds during
REL-002 using the deployed environment and observed workload. Previously
discussed CPU, RAM, and disk thresholds are provisional examples.

### External monitoring provider

On 2026-11-26, the owner replaced Healthchecks.io with Better Stack for
external job heartbeats. Healthchecks.io registration and login emails did
not arrive across repeated attempts, including alternative registrations.
The owner sent a support request on 2026-11-24 and had received no response
when making the decision. The cause of the missing emails was unconfirmed.

The [production PostgreSQL backup heartbeat](#systemd-installation-and-monitoring)
is the first verified Better Stack integration. Other scheduled jobs and
public HTTP/HTTPS monitoring still require configuration and validation under
REL-002 and G13D-3.

The Telegram bot `@SmartBudgetOpsAlertBot` was created and a direct Bot API
message succeeded from the local environment. Application integration and
production validation remain open. Keep the bot token and chat ID in
server-owned configuration and out of documentation and Git.

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

Repeat this cutover procedure for migration `8c40f6a2e517` and the purchase
reference templates. Stop Sale creation and email workers before upgrading.
The migration backfills references and blocks upgrade while a delivery is
`sending`. On a populated database, keep the new schema and references
when recovering from an application deployment failure. Downgrade blocks
removal of assigned purchase references. Recovery code must still generate
references for new Sales because the column has no database default.

## G13B/G13C purchase access recovery

Apply Alembic revision `4a2d8c71ef36` before starting the updated web and
purchase-email workers. The revision refuses downgrade when recovery history
exists. Keep that history with the order data. If application rollback is
required after a recovery, disable purchase-email delivery in both environments
before running code that predates the recovery send guard.

On Admin Sale Detail, use the following procedure for a paid product-only Sale
with one product item and no refund operation:

1. Verify the original payment and the claimant's ownership independently
   using trusted payment-provider evidence. Match the provider payment ID
   and order details to the Sale. Treat the purchase reference and email as
   lookup details. Use the verification method and a short operational reason
   in Admin. Omit card details, identity documents, and capability links.
2. Use **Prepare recovery** with the corrected email if needed. This replaces
   the app download token, sets a fresh 24-hour window for the purchased
   release and saves the previous attempt summary. An original email still
   in `sending` must settle or reach reconciliation before preparation.
3. Check the recovery recipient and use **Send recovery email**. This uses
   the existing Resend settings and `PURCHASE_EMAIL_DELIVERY_ENABLED`.
   `accepted` records Resend acceptance. Check provider delivery separately.
   An ambiguous send can be retried only for the same recovery, within its
   safety window and while the grant is usable. A stalled send claim can be
   retried after its two-minute lease when those checks pass.
4. For `reconciliation_required`, inspect Resend using the available message
   ID, recovery correlation tag, recipient and attempt time. Record verified
   evidence in the support case and escalate unresolved cases. The workflow
   blocks replacement recovery while a send remains unresolved. G13D can
   still show incidents for the original delivery. Check the recovery status
   on Sale Detail and use the recovery-specific Resend evidence.

In production, verify the migration, both preparation paths, exact release
and attempt audit, old-token rejection, and separate Resend delivery and
original-retry suppression. Track evidence in the
[release checklist](release_readiness.md#g13c--reissue-download-access).

### Manual consultation support

For consultation-only or mixed Sales, independently verify the original payment
using provider evidence. Inspect the entitlement in `/admin/consultations`
and check the Calendly Share, any provisioning or revocation in progress, and the
actual booking or invitee state in Calendly. An existing booking capability or
Share keeps its own lifecycle when a customer reports an email correction.
Describe the actual access status to the customer.

Resolve the case individually through supported Admin and Calendly operations.
Use the [consultation cancellation procedure](#consultation-cancellation-in-admin-sale-detail)
when a cancellation or refund is appropriate. Escalate unresolved access,
Share, booking, or refund issues for operator review. Keep database changes
within supported operations and record only the needed provider reference and
outcome in the support case.

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
5. Return to the Sale, accept **I verified the full refund in Lava.top.** and
   select **Confirm verified full refund**. This records `original_provider`,
   changes the Sale to `refunded`, and revokes future access atomically.
6. If the Admin reports a conflict or persistence error, do not edit SQL or
   start another refund. Preserve the provider evidence and investigate the
   existing Sale/refund operation.

### Manual alternative full refund

Apply Alembic revision `1c6ea8b50d37` before starting the updated application.
Legacy confirmations retain an unknown method. Downgrade across this revision
is blocked once a confirmation method has been recorded, which protects refund
history.

1. If Lava.top cannot process the required full refund, review the payment and
   confirm that the original provider has executed no refund for the Sale.
   Use the same pending full-Sale operation. Escalate conflicting evidence
   before transferring funds. Apply the existing
   [consultation disposition checks](#consultation-cancellation-in-admin-sale-detail)
   when the Sale includes a consultation.
2. Obtain the customer's explicit agreement to the alternative method.
   Complete and verify the exact full refund externally using the agreed
   phone-number or card-based method. Keep the agreement, execution evidence,
   and any payment details outside SmartBudgetSite.
3. In Admin Sale Detail, acknowledge the customer's agreement, verified
   execution of the full transfer, external evidence retention, and the
   absence of an executed original-provider refund. Select **Confirm
   alternative refund**. If the consultation verification exception applies,
   acknowledge it and select the consultation reason.
4. Verify that the operation shows **Alternative transfer** and the Sale
   shows `refunded`. This records verification of execution. Confirm any bank
   or card settlement separately.

Rehearse the protected Admin flow in the release environment up to the
confirmation step. Record verified execution and confirm the alternative
refund on the first genuine case.

### Refund request customer receipt recovery

Apply `24d760e4bc31` before deploying R53-3. Run
`python -m scripts.recover_refund_request_receipts --dry-run` for a read-only
count of up to 20 due receipts, or omit `--dry-run` for one live pass using
the existing customer SMTP settings. Live recovery uses a PostgreSQL advisory
lock. The prepared `smartbudget-refund-receipt-recovery` timer runs each
minute at :15 UTC and remains pending installation and live validation.

After the initial attempt, temporary or ambiguous outcomes retry after
1, 2, 5, 15, 30 and 60 minutes, up to seven total attempts. Expired
two-minute sending leases are classified as ambiguous and enter the same
bounded retry schedule. Configuration and permanent failures stop retries.
The transport uses a five-second socket timeout and verifies the certificate
and hostname when STARTTLS is enabled. An ambiguous outcome may yield a
duplicate if SMTP accepted the message before acceptance was recorded.

Use the protected Refund Requests Admin list to review receipt status,
attempts, timestamps and sanitized failure classification. Investigate
failed receipts through the existing operator follow-up. SMTP acceptance
does not establish inbox delivery. Older requests have no receipt record.

### Refund request lifecycle

Apply Alembic revision `6e4f8c2a9b17` before starting R53-4A code. It adds
nullable UTC response and closure timestamps. Existing requests remain
`pending` with both timestamps empty. Downgrade is blocked once lifecycle
history exists.

In Admin Refund Requests, use **Mark first response sent** after sending a
substantive reply to the customer. Use **Close request** after completing review
and required follow-up. The actions record attestations, and their timestamps
remain unchanged on replay. Continue to handle refund execution in Sale Detail.
An automated receipt does not satisfy the first-response target.

### Refund request deadline reminders

Apply revision `9f3b1a7c2d84` before starting the reminder job. The migration
adds a separate outbox without backfilling delivery history. Downgrade is
blocked once reminder history exists. Leave
`REFUND_REQUEST_REMINDER_DELIVERY_ENABLED=false` until release validation.
Use `python -m scripts.dispatch_refund_request_reminders --dry-run` to
inspect up to 20 eligible requests without writing or sending. The live
one-pass command uses a PostgreSQL advisory lock and the existing operator
Telegram and administrative SMTP settings. The prepared timer runs every
minute at :50 UTC. A pass selects up to 20 requests and retires up to 20 old
or expired cycles. Each selected request allows at most one attempt per
channel in that pass.

The job calculates each weekday slot from the request's UTC submission time.
After downtime it starts with the current eligible weekday slot and skips
unsent older cycles. After a definitive temporary rejection, retry at
1, 2, 5, 15, 30 and 60 minutes, up to seven attempts per channel within the
same cycle. Confirmed configuration or permanent failures stop that channel.
An ambiguous result or a two-minute expired send lease ends that cycle as
unconfirmed. Investigate ambiguous and failed outcomes in the journal and
durable outbox. The next eligible weekday cycle starts with Telegram.
The job rechecks status before each claim. A provider call already in flight
can finish after an operator records a response or closes the request.

During release validation, provision a dedicated
[Better Stack heartbeat](#external-monitoring-provider) with the timer
cadence and a grace period that covers the validated runtime. Configure
the release job wrapper to report success only
after a live run exits successfully with `status=completed`. Exclude dry runs,
disabled passes and lock skips from success heartbeats. Deliver missed or
failed heartbeat alerts independently of the app host and its dispatchers.
Verify detection by stopping the job in the validation environment.
Use journal and outbox outcomes separately to verify provider acceptance,
fallback, and backlog age. Installation, enablement, and external monitoring
validation remain open.

### Pre-release refund operations

`REFUND_REQUEST_ALERT_DELIVERY_ENABLED` defaults to `false` and controls
operator delivery only. Apply `ae416d0f278b` before deploying R53-2 code.
Earlier requests have no outbox rows and remain visible for operator review.
Run `python -m scripts.dispatch_refund_request_alerts --dry-run` to read due
counts without sending or mutating rows. Live one-pass mode uses the existing
Telegram and administrative SMTP settings and selects up to 20 requests.

The PostgreSQL advisory lock prevents overlapping live passes. An interrupted
claim becomes ambiguous after its two-minute lease. Each channel allows one
initial attempt and up to six retries at 1, 2, 5, 15, 30 and 60 minutes.
Configuration and permanent failures stop that channel immediately.
Confirmed transport acceptance suppresses future sends. An ambiguous outcome
can result in duplicate alerts if a provider accepted a send before its result
could be recorded. Review terminal failures in Admin.

The prepared `smartbudget-refund-request-alerts` systemd units use the
existing job placeholders and schedule one pass each minute at :45 UTC.
Installation, activation and live delivery validation remain open.

Complete the bounded R42 refund and R53 request capabilities after G13D and
before public sales. The [approved refund rules](architecture/commerce_and_delivery.md#approved-refund-rules-and-customer-requests-d4)
govern eligibility, amounts, item access and customer confirmations.

1. Record the customer request, acknowledge receipt, and provide the operator
   with backend-owned purchase context and the status of the voluntary deadline.
   R53-2 persists the notification obligation at intake and uses Telegram
   with administrative SMTP fallback. Track pending request age
   and failed delivery evidence. Apply the policy targets of 3 business days
   for initial response and normally 5 for review, counting Monday–Friday
   without holiday exclusions. Mandatory deadlines take precedence.
2. Prepare the exact full-Sale refund amount for the applicable separate
   purchase. For an exceptional or historical case, review applicable rights,
   original item amounts and provider evidence under the
   [first-release amendment](architecture/commerce_and_delivery.md#first-release-sales-model-amendment).
   Use the documented exception procedure when the existing full-Sale path
   cannot execute the required outcome.
3. Have the operator execute the refund manually through the
   [original provider](#manual-lavatop-full-refund) or the approved
   [alternative procedure](#manual-alternative-full-refund) when the provider
   cannot process it. Verify execution and apply the
   [consultation disposition safeguards](architecture/consultations.md#cancellation-and-refund-coordination)
   before confirming the internal outcome.
4. Record the evidence and follow-up. Use the approved recovery procedure for
   conflicting evidence or a later required refund that the original provider
   path cannot process.

`SENT` is evidence of provider-side processing. Final bank or card settlement
requires separate evidence. The public estimate is up to 10 business days
after processing, subject to the bank and method. Authoritative machine-readable refund verification
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

### Vultr monitoring and pre-deployment baseline

Verified on 2026-11-12:

- Vultr Usage Graphs provide vCPU, Disk Operations, Network, and Monthly
  Bandwidth. CPU, disk, and network graphs appeared after refreshing the
  dashboard.
- Outage and Maintenance email notifications are enabled.
- Bandwidth email alerts are enabled at 75%, 90%, and 100%.
- Invoice email notification remains enabled.

The VPS measurements below were taken before application deployment.
Production sizing requires measurements under the deployed workload.

| Metric | Pre-deployment result |
| --- | --- |
| vCPU | 2 |
| Load average | 0.00 / 0.00 / 0.00 |
| RAM total | 3.8 GiB |
| RAM used | 434 MiB |
| RAM available | 3.4 GiB |
| Swap | 7.7 GiB, 0 used |
| Root filesystem | 75 GB, 12 GB used, 60 GB available (17%) |
| Running Docker containers | None reported by `docker ps` |
| System PostgreSQL service | Inactive |

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

The owner has verified PostgreSQL 16 provisioning, scheduled encrypted
backups, an isolated restore from an automated archive, and a production
heartbeat from a manually initiated backup. See the
[OPS-001 evidence and runbook](#automated-postgresql-backup-and-retention-ops-001).
The following work remains open:

- Production backup pruning, persistent catch-up, scheduled heartbeat and
  production backup failure monitoring validation.
- Application deployment and process lifecycle validation.
- Reverse proxy, DNS, HTTPS, and production perimeter validation.
- Production startup checks, monitoring for the other jobs and public
  availability, and full infrastructure recovery drills.
- End-to-end production payment and delivery validation.

Vultr instance backups alone are not considered sufficient evidence
of application/database recovery readiness.

Public application exposure remains deferred until the
applicable pre-deployment release gates are satisfied, as defined
in `release_readiness.md`.

This infrastructure preparation does not complete `REL-002`,
`OPS-001`, `SEC-012`, or any live integration validation gate.

## Deployment and external integration validation

Before production deployment, complete the production environment variables,
domain integration, startup validation, and operational logging review.

The first deployed public HTTPS environment must validate the existing
implementation before prompting architecture changes:

1. Configure Calendly Share access as described below. Create and validate the
   Calendly webhook subscription, capture a real `invitee.created` payload,
   and verify first-booking matching, replay and rescheduling. Validate
   cancellation and provider-side revocation in their separate release slices.
2. Validate Cloudflare R2 S3 connectivity, authenticated bucket access, real
   release upload, stored object metadata, `ProductRelease` persistence,
   identical retry behavior, compensation after a forced database failure, and
   read-only reconciliation against paginated production-like listings.

Use `current_state.md` to identify completed external validation and current
blockers. Test the existing implementation from the deployed environment before
introducing architecture changes or repeating local integration troubleshooting.

### Calendly Share configuration and recovery

Set `CALENDLY_CONSULTATION_EVENT_TYPE_URI` to the Calendly API URI of the
approved one-on-one Event Type. Configure `CALENDLY_PERSONAL_ACCESS_TOKEN` with
`shares:write` for creation, `shares:read` for recovery, `users:read` for
`/users/me`, and `scheduled_events:read` for Event and Invitee verification.
Calendly documents that `shares:write` includes `shares:read`. Event Type
discovery requires `event_types:read`. Webhook setup uses `webhooks:write`
and the event-family read scope. Set `CALENDLY_WEBHOOK_SIGNING_SECRET` for
transport verification. Keep `SECRET_KEY` stable across the lifetime of
outstanding signed Share URLs. Rotating it invalidates their correlation and
requires operational review before rollout.

R39-A persists the Share claim before contacting Calendly. Following a timeout
or failed local write, reopening the protected page and submitting again
attempts paginated recovery for the pinned Event Type and exact opaque name
marker. It does not issue another create request. If no single valid Share
can be recovered, inspect the Share in the owning Calendly account and escalate
the unresolved claim. Do not clear it or create a replacement based only on
an empty search. Migration downgrade is supported before claims exist. It is
blocked once claim history exists to avoid losing Share ownership.

Verify live Share provisioning, signed tracking, timely booking, replay and
rescheduling after the local window in the release environment.

### Calendly Share expiry revocation

`python -m scripts.revoke_calendly_shares --dry-run` selects due records
without writing to the database or contacting Calendly. Running without
`--dry-run` performs one bounded pass. The configured Calendly token needs
`shares:write` to delete and the Share listing and user scopes above to recover
unresolved claims or verify booking conflicts.

The paired `smartbudget-calendly-share-revocation` systemd units run every
minute at second 20 UTC. Prepare and verify the service placeholders during
REL-002. The selection includes overdue records from missed ticks. Each pass
selects at most 20 rows and stops starting new rows after 40 seconds. Provider
requests use a five-second HTTP timeout. Local access expiry is exact, while
provider deletion can lag because of timer granularity, backlog or outages.

Review the journal summary and unresolved outcome on Admin Sale Detail. An
attempt starts with a durable retry time and backs off from one minute to one
hour. A longer provider `Retry-After` takes precedence. If a crash occurs after
DELETE, a later 404 stays unconfirmed. Check the owning Calendly account using
the persisted Share identity or exact provisioning marker. Do not infer
deletion from an empty listing. A verified provider-booked outcome stops
deletion attempts and requires booking reconciliation or operator review.
Compare `calendly_revoked_at` against `expires_at` to measure confirmed
provider revocation lag. A null confirmation time leaves the outcome unresolved.
Downgrade is allowed before attempts exist and preserves evidence by refusing
to downgrade after revocation work starts.

Validate unit rendering, timer installation, a controlled unused Share DELETE
and a provider booking race in the release environment.

### Consultation sales capacity

Alembic revision `8e21d4f6ab93` seeds the single PostgreSQL capacity row with
sales unsuspended. An absent or unreadable row closes new consultation checkout.
Before a downgrade across this revision, close new consultation checkout at
the deployment perimeter and preserve any state or alert history needed for
recovery. The downgrade drops both capacity tables.

`/admin/consultation-offers` shows the current workload and has persistent
suspend and resume controls. Resume removes the manual pause and leaves the
workload limit in effect.

The existing `smartbudget-alert-dispatcher` runs the capacity pass once per
activation through `python -m scripts.dispatch_purchase_alerts`. The command
reports its result under `consultation_capacity` and uses a separate session
from purchase delivery alerts. `--dry-run` checks for due outbox entries
without observing new episodes, writing, or sending.

Both channels use the existing Telegram and administrative SMTP settings.
Telegram is tried first when both channels are due. An unconfirmed Telegram
attempt leaves SMTP eligible. The two-minute send lease supports recovery
after interruption. Temporary and ambiguous outcomes back off by 1, 2, 5,
15, 30, and 60 minutes, with up to seven attempts per channel. Configuration
and permanent failures terminate that channel. An accepted send suppresses
further attempts for the episode. Ambiguous acceptance can still produce a
duplicate through retry or fallback.

Observation is periodic, so a crossing that begins and ends between samples
can go unreported. Public checkout evaluates current workload on each initiation.

#### Consultation Capacity Management production deployment checklist

Steps 1–4 prepare configuration. Steps 5–6 deploy it. Steps 7–9 verify live
behavior and record production evidence.

1. Confirm the intended capacity limit (default `4`) and warning threshold
   (default `3`). The warning threshold must be a positive integer below the
   limit.
2. Set identical `CONSULTATION_CAPACITY_LIMIT` and
   `CONSULTATION_CAPACITY_WARNING_THRESHOLD` values in the web and dispatcher
   environments.
3. Prepare and verify the existing [Telegram and administrative SMTP settings](#g13d-3-operational-monitoring-target),
   including the destinations and SMTP STARTTLS requirements.
4. Once both transports are ready, explicitly set
   `CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED=true` in the dispatcher
   environment. The flag defaults to `false`.
5. Apply Alembic revision `8e21d4f6ab93` before starting the updated
   application or dispatcher.
6. Deploy or restart the application and alert dispatcher. Verify that the
   existing `smartbudget-alert-dispatcher.timer` is active and triggers a
   successful scheduled pass.
7. Verify the seeded capacity row, Admin suspend and resume, and persistence
   of a manual suspension across a restart. Check that RU/EN consultation
   checkout blocks at the limit and reopens below it. Confirm that a payment
   initiated before the limit was reached can still complete and grant the
   booking entitlement.
8. Verify live dispatch of both the warning and exhaustion alerts. Confirm
   Telegram delivery and use a controlled Telegram failure to verify that
   the alert reaches the administrative SMTP recipient.
9. Record production validation results, supporting evidence, and any
   remaining issues in the release readiness review.

### Consultation cancellation in Admin Sale Detail

A standalone consultation refund request permanently closes booking access.
Starting a founder-initiated full refund does the same for consultation
entitlements on that Sale. The revocation timer picks up unused Shares,
including those with time remaining in the original booking window.
If a meeting exists, use **Verify meeting and cancel if still upcoming**.
The Calendly credential needs `scheduled_events:write` for cancellation and
the read scopes for Event, Invitee and Event Type verification. If Calendly
times out, retry after the displayed time. Verification runs before any
repeat cancellation. Review unresolved ownership in the owning Calendly
account and never target a meeting by email alone.

An elapsed meeting with no outstanding successor is a verified provider
disposition. Review actual delivery and refund eligibility separately. When
provider verification is unavailable and a refund must proceed, acknowledge
the exception and record the reason without customer secrets. Always perform
and verify the refund manually in Lava.top. The confirmation stores the
reason and timestamp. Validate the live provider paths and race handling
before release.

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

Verify the [G13D-3 job schedules, measurements, and independent checks](#g13d-3-operational-monitoring-target),
bounded Lava.top polling, Resend webhook delivery and replay, safe recovery
and operator escalation, and independent SMTP and Telegram delivery. Validate
the 30-minute critical detection SLO
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
