# SmartBudget API

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.1-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14-blue)
![Docker](https://img.shields.io/badge/Docker-enabled-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Backend for SmartBudget application built with FastAPI, PostgreSQL and Docker.

---

## 🔍 Health Check

```bash
curl http://127.0.0.1:8800/v1/health
```

Response:
```json
{"status": "ok"}
```

## 📦 Project Structure

```text
app/
  api/             # API endpoints (routers)
  core/            # Config, logging, i18n, dependencies
  db/              # Database setup
  models/          # SQLAlchemy models
  repositories/    # Data access layer
  schemas/         # Pydantic schemas
  static/          # CSS, JS
  templates/       # HTML (Jinja2)
  web/             # Web routes (HTML pages)
  main.py          # FastAPI entrypoint

alembic/           # Migrations
tests/             # Tests
uploads/           # Stored files (local storage)
docs/              # Dev notes

.env*
docker-compose.yml
requirements.txt
alembic.ini
pytest.ini
```

## 🚀 Features

### Feedback system
- Multiple message types:
  - Site issue
  - General question
  - Product feedback
- Purchase verification for product feedback
- Dynamic form behavior on frontend

### Attachments
- Multiple file upload (max 5 files)
- Drag & drop support
- File picker fallback
- Client-side validation (file type)
- Server-side validation:
  - file type
  - file size (max 20 MB)
  - max files count
- Files stored locally with unique names
- Metadata stored in database

### Internationalization
- English / Russian UI support

---

## 🛠 Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Docker
- Vanilla JS (frontend)

---

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
