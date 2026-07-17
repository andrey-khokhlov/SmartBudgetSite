# Operations

This is the authoritative source for local development commands, environment
configuration rules, deployment preparation, and operational validation.

## Development commands

## Run application

```bash
# Start FastAPI app with auto-reload (dev mode)
uvicorn app.main:app --reload
```

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

Perform the Release Readiness Review before any public product release.
