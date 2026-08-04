# SmartBudget

SmartBudget is a forecasting-first personal financial decision-support product
that helps people understand likely financial outcomes before making decisions.

It combines forward-looking financial planning, deterministic calculations,
business intelligence, automation, and application engineering in one evolving
system.

## Purpose

Personal finance tools often focus on recording what has already happened.
SmartBudget is designed around a different question:

> What is likely to happen next, and what does that mean for the decision I am
> considering now?

The product is intended to help users evaluate affordability, sustainability,
future cash-flow pressure, and the consequences of changing a plan as new
financial information becomes available.

SmartBudget is not positioned as merely an expense tracker, an accounting
system, or an opaque AI adviser. Its purpose is to provide a structured,
inspectable basis for personal financial decisions while keeping the user in
control of the plan.

## Current status

SmartBudget is in active development.

The repository currently represents the public application and supporting
infrastructure around the product. It includes the web application, API,
database layer, migrations, tests, localisation, feedback workflows, purchase
verification, and operational safeguards.

The product is not yet presented here as a completed commercial release.
Functionality, architecture, and documentation continue to evolve as the system
moves toward a production-ready public version.

## What the system supports

The current application provides the public and operational infrastructure
required to present, distribute, and support SmartBudget.

### Product presentation

- bilingual English and Russian web interface;
- public product catalogue and product-specific landing pages;
- FAQ and supporting product information;
- structured product, edition, price, and availability data.

### Purchase and delivery workflows

- purchase verification;
- product releases linked to eligible purchases;
- controlled download entitlements;
- expiring download links and attempt limits;
- signed delivery URLs backed by external object storage;
- support references for purchase and download issues.

### Feedback and customer support

- structured feedback for site, product, purchase, and download issues;
- optional supporting attachments with validation;
- administrative review, resolution, reply, and publication workflows;
- public product reviews where publication has been explicitly approved.

### Product operations

- administrative management of products, prices, releases, and sales;
- release upload and publication workflows;
- consultation entitlement handling;
- database migrations and automated tests supporting continued evolution.

### Operational safeguards

- protected administrative routes;
- rate limiting for sensitive workflows;
- validation of uploaded files and product archives;
- explicit handling of unavailable storage, invalid entitlements, and expired
  download access.

## Product and engineering principles

### Forecasting before recording

SmartBudget is designed primarily to support forward-looking decisions rather
than only document past transactions.

### Deterministic calculations

Core financial results should be derived from explicit, reproducible rules.
The same inputs should produce the same outputs, and important calculations
should remain inspectable.

### User control

The system should help users understand consequences and alternatives without
taking control of the financial plan away from them.

### Maintainable architecture

Business rules, data access, application services, and presentation concerns are
kept separate so that the system can be tested, reviewed, and changed safely.

### Progressive automation

Repetitive operational work should be automated where this improves reliability,
but automation should not hide important decisions or weaken accountability.

### Responsible use of AI

Future AI capabilities may support explanation, navigation, and interpretation.
They should not replace deterministic financial logic or present uncertain
outputs as authoritative financial advice.

## Architecture

SmartBudgetSite is structured as a layered web application rather than a
collection of independent endpoints.

### Presentation layer

Server-rendered Jinja2 pages provide the public website, product catalogue,
product landing pages, feedback flows, download pages, and administrative
interfaces. English and Russian content is resolved through the application
localisation layer.

### Web and API routing

Public web routes, administrative routes, and versioned API endpoints are kept
separate. Administrative routes require explicit authentication, while
sensitive public workflows are protected by request validation and rate
limiting.

### Application services

Business workflows are implemented in dedicated services rather than directly
inside route handlers. These services coordinate feedback processing, purchase
verification, consultation entitlements, product releases, and controlled
downloads.

### Data access and persistence

SQLAlchemy models represent the application data, while repositories isolate
database access from business logic. Alembic migrations provide controlled
schema evolution for PostgreSQL.

### Product delivery

Product releases are associated with eligible purchases and exposed through
time-limited download entitlements. Release files are stored in S3-compatible
object storage and delivered through signed URLs rather than directly from the
application server.

### Quality and operational controls

Automated tests cover application behaviour and evolving workflows. Validation,
rate limiting, protected administrative access, explicit error handling, and
configuration checks support safer operation across development and production
environments.

## Technology

**Application:** Python, FastAPI, Uvicorn  
**Data and persistence:** PostgreSQL, SQLAlchemy, Alembic  
**Validation and configuration:** Pydantic, pydantic-settings  
**Web interface:** Jinja2, HTML, CSS, Vanilla JavaScript  
**Storage and delivery:** S3-compatible object storage, boto3  
**Testing:** pytest, pytest-asyncio, HTTPX  
**Packaging and local development:** Docker, Docker Compose

## Scope and limitations

This repository contains SmartBudgetSite: the public web application and the
operational infrastructure used to present, distribute, and support
SmartBudget.

It does not contain the complete SmartBudget financial model or the
distributable product files themselves.

The application is still under active development and should not be treated as
a completed commercial release or as a production deployment template.

Some workflows depend on external services and valid credentials, including
mail delivery, Calendly integration, PostgreSQL, and S3-compatible object
storage. A basic local application instance can be started without exercising
all external integrations, but the corresponding workflows will remain
unavailable until they are configured.

Security, deployment, backup, monitoring, and operational procedures must be
reviewed for the target environment before production use.

## Development setup

### 1. Clone the repository

```bash
git clone https://github.com/andrey-khokhlov/SmartBudgetSite.git
cd SmartBudgetSite
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux or macOS:

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the environment

Copy the example configuration.

Windows:

```powershell
Copy-Item .env.example .env
```

Linux or macOS:

```bash
cp .env.example .env
```

Then replace the example values with local development credentials.

The application reads `.env` by default. A different configuration file can
be selected through the `ENV_FILE` environment variable.

Configuration covers:

- application environment, host, port, and CORS;
- PostgreSQL connection and credentials;
- application secrets and administrative access;
- mail delivery and administrator notifications;
- Calendly consultation integration;
- Cloudflare R2 product-release storage;
- download token lifetime, signed URL lifetime, and attempt limits;
- upload and rate-limiting safeguards.

Do not commit real credentials or production secrets.

### 5. Start PostgreSQL

Docker Compose currently provisions the local PostgreSQL service:

```bash
docker compose up -d
```

To stop it:

```bash
docker compose down
```

The Compose configuration does not start the FastAPI application itself.

### 6. Apply database migrations

```bash
alembic upgrade head
```

### 7. Run the application

```bash
python run.py
```

The default example configuration exposes the application at:

```text
http://127.0.0.1:8800
```

### 8. Verify the local instance

```bash
curl http://127.0.0.1:8800/v1/health
```

Expected response:

```json
{"status": "ok"}
```

### 9. Run the test suite

```bash
pytest
```

## License

Copyright © Andrey Khokhlov.

No license is granted to use, copy, modify, distribute, or create derivative
works from this source code unless explicit written permission is provided.

