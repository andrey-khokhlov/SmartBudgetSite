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

## 🛠 Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Docker
- Vanilla JS (frontend)

## ⚙️ Environment

Environment variables are configured via:

- `.env`
- `.env.dev`
- `.env.prod`
- `.env.example`

## Key variables:
```text
DATABASE_URL=
APP_HOST=127.0.0.1
APP_PORT=8800
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
SECRET_KEY=
UPLOAD_DIR=uploads
```

## ⚡ Quick Start

### 1. Clone repository
```bash
git clone https://github.com/<your-username>/SmartBudgetSite.git
cd SmartBudgetSite
```

### 2. Create virtual environment
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
copy .env.example .env
```

### 5. Run application
```bash
python run.py
```


## ▶️ Run locally

```bash
docker-compose up -d
```
```bash
docker-compose down
```

🔐 Validation rules
```text
Files Allowed:
.png
.jpg
.jpeg
.webp
.pdf
Max size: 20 MB per file
Max files: 5
```

📁 Storage

Current implementation:

Local disk (/uploads)
Unique filenames (UUID)

Future improvement:

S3-compatible storage (scalable & production-ready)
🧪 API
Create feedback

POST /v1/feedback

multipart/form-data
supports attachments
Check purchase

POST /v1/check-purchase

💡 Notes
Backend is designed with layered architecture (router → service → repository)
File handling is isolated and ready for migration to cloud storage

## 🔌 Example API usage

### Create feedback with attachments

```bash
curl -X POST "http://127.0.0.1:8800/v1/feedback" \
  -F "message_type=site_issue" \
  -F "subject=Test message" \
  -F "message=Something is broken" \
  -F "files=@screenshot.png"
```
### Check purchase
```bash
curl -X POST "http://127.0.0.1:8800/v1/check-purchase" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
```
