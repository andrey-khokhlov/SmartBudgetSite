# Operations

This is the authoritative source for local development commands, environment
configuration rules, deployment preparation, and operational validation.

## Development commands

## Run application

```bash
python run.py
```

The application is available at `http://127.0.0.1:8800` by default. This is the
authoritative local development startup method; avoid documenting or running
parallel startup commands that can create duplicate application processes.

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

## Deployment and external integration validation

Before production deployment, complete the production environment variables,
domain integration, startup validation, and operational logging review.

The first deployed public HTTPS environment must validate the existing
implementation before prompting architecture changes:

1. Create and validate the Calendly webhook subscription, capture a real
   `invitee.created` payload, confirm initial reconciliation, and verify replay
   and cancellation edge cases.
2. Validate Cloudflare R2 S3 connectivity, authenticated bucket access, real
   release upload, stored object metadata, and `ProductRelease` persistence.

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
- JavaScript initialization and error-free execution;
- the intended customer interaction from entry point through confirmation;
- behavior after a normal refresh with previously cached static assets.

Playwright is a development/test-only layer and is not a production runtime
dependency. Browser tests remain separate from ordinary pytest discovery, use
Chromium as the supported browser, and should capture page errors and console
errors while exercising dynamic behavior and critical journeys. The single
source for local Playwright setup and browser-test commands is
`../browser_tests/README.md`; do not duplicate those installation instructions
here. The ordinary non-browser suite continues to run with `python -m pytest`.

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
