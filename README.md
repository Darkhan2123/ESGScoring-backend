# ESG Community Platform — Backend

REST API for a university platform that motivates students to take part in ESG
(Environmental, Social, Governance) activities. Students earn points for completing
events and projects and for a daily educational quiz, then spend those points in an
in-app shop. The backend serves native Android and iOS clients.

Points are the single in-app currency. "ESG" describes the subject matter of the
activities and quiz content; the system is a gamified participation tracker, not an
ESG-rating engine.

## Stack

- Python 3.12
- Django 5.1 and Django REST Framework 3.15
- PostgreSQL (SQLite is supported for local development)
- JWT authentication via `djangorestframework-simplejwt`
- OpenAPI schema and Swagger UI via `drf-spectacular`

## Getting Started

### Prerequisites

- **Python 3.12**
- **Docker** (optional, for Postgres database or full-stack containerized execution)

### 1. Clone the Repository

Clone the project to your local machine:
```bash
git clone https://github.com/Darkhan2123/ESGScoring-backend.git
cd ESGScoring-backend
```

### 2. Configure Environment Variables

Copy the template environment file to create your own configuration:
```bash
cp .env.example .env
```
By default, the settings are configured to use an SQLite database (`db.sqlite3`) for quick local setup.

---

### Local Development

This setup runs the Django server on your host machine.

#### 1. Setup Virtual Environment


```bash
# Create
python -m venv .venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

#### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3. Select Database Choice

* **Using SQLite (Default)**:
  Ensure your `.env` has:
  ```env
  DB_ENGINE=django.db.backends.sqlite3
  DB_NAME=db.sqlite3
  ```

* **Using PostgreSQL via Docker**:
  If you want to use a real PostgreSQL database, spin up the local development db container:
  ```bash
  docker-compose -f docker-compose.dev.yml up -d
  ```
  And update your `.env` database block to:
  ```env
  DB_ENGINE=django.db.backends.postgresql
  DB_NAME=esg_scoring
  DB_USER=postgres
  DB_PASSWORD=postgres
  DB_HOST=localhost
  DB_PORT=5432
  ```

#### 4. Run Migrations & Setup

```bash
# Run migrations
python manage.py migrate

# Create a superuser to access /admin/
python manage.py createsuperuser
```

#### 5. Start Development Server

```bash
python manage.py runserver
```
The API and documentation will be available at:
- Dev server: http://127.0.0.1:8000/
- Docs: http://127.0.0.1:8000/api/docs/
- Django Admin: http://127.0.0.1:8000/admin/

---

### Running the Full Stack with Docker

If you prefer to run the entire backend stack (Django web container + PostgreSQL + Nginx reverse proxy) in Docker:

#### 1. Setup Environment Configuration
Ensure you configure appropriate DB settings in `.env` (the Django and DB containers use the same file to coordinate credentials):
```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=esg_scoring
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=db
DB_PORT=5432
```

#### 2. Build and Run Containers
```bash
docker-compose up --build -d
```
The entrypoint script will automatically wait for the database and apply migrations. 

#### 3. Access Services
- Nginx Gateway / API: http://localhost/
- Interactive docs: http://localhost/api/docs/
- Django Admin: http://localhost/admin/

To create a superuser inside the running web container:
```bash
docker-compose exec web python manage.py createsuperuser
```
To seed data inside the running web container:
```bash
docker-compose exec web python manage.py seed
```

## Running Tests

The project uses Django's built-in test framework (`unittest`-based). Tests live in each app under `apps/<app>/tests/` and are split into `test_views.py` (endpoint tests) and `test_services.py` (service/business logic tests).

### Run all tests

```bash
python manage.py test
```

### Run tests for a specific app

```bash
python manage.py test apps.users
python manage.py test apps.events
python manage.py test apps.quizzes
```

### Run a specific test class or method

```bash
# Single test class
python manage.py test apps.users.tests.test_views.UserAPITestCase

# Single test method
python manage.py test apps.quizzes.tests.test_services.DailyQuizServiceTest.test_daily_quiz_credits_points
```

### Test‑aware settings

When you run tests, `config/settings.py` automatically detects `test` in `sys.argv` and overrides these settings — **no manual configuration needed**:

| Setting | Override for tests | Benefit |
|---------|-------------------|---------|
| Database | `:memory:` SQLite | No test database to create/destroy |
| Password hasher | `MD5PasswordHasher` | Faster user creation in test setup |
| Cache backend | `LocMemCache` | No Redis dependency required |

### Testing strategy

Each endpoint test follows a **1 good case + 2 bad cases** pattern:

1. **Happy path** — verify a valid request returns `200`/`201` and the correct response body.
2. **Authentication / permission checks** — unauthenticated or wrong-role requests return `401`/`403`.
3. **Validation errors** — invalid payloads return `400` with descriptive error details.

This includes tests that deliberately trigger **"already taken" errors** — for example, attempting to create a shop or organization with a duplicate name to verify the unique constraint is enforced (`400` response). Seeing these tests pass is expected; they confirm business rules work correctly.

### Performance tests

The project includes k6-based stress tests for concurrency and performance validation (points spending, caching, throttling). See [`tests/stress/README.md`](tests/stress/README.md) for detailed instructions.

```bash
# Quick smoke test (1 user, end-to-end)
k6 run tests/stress/smoke-test.js -e BASE_URL=http://localhost

# Full load test (after generating test users)
make -C tests/stress stress-setup
make -C tests/stress stress-load-json
```

## Architecture

The project follows a layered structure:

```
URL (config/urls.py -> apps/<app>/urls.py)
  -> APIView            parses input, selects a serializer by role
  -> Permission class   role check (apps/users/permissions.py)
  -> Serializer         input validation
  -> Service layer      business logic, points accounting, state transitions
  -> Models / ORM       database access
  -> Exception handler  domain errors mapped to a consistent JSON envelope
  -> JSON response
```

Views are intentionally thin. All operations that touch the points balance or move an
entity through a state machine live in a per-app `services.py`, wrapped in a database
transaction with row locking (`select_for_update`) and atomic `F()` updates, so the
balance stays correct under concurrent requests.

### Applications

| App | Responsibility |
| --- | --- |
| `core` | Shared utilities: domain exceptions, the custom exception handler, pagination and filtering helpers, health check. No models. |
| `users` | Custom user model (email login, roles, points balance), JWT auth, profile, admin user management, role-based permission classes. |
| `organizations` | Organizations that publish events, projects and quiz questions. Each organization is owned by one user. |
| `events` | Tasks/events with a points reward and a verification code; participation requests with a status state machine. Credits points on completion. Includes the leaderboard. |
| `projects` | Lightweight project listings linked to a Google Form; students claim points with a verification code. |
| `quizzes` | Daily quiz: question pool, daily quiz, per-student attempts (one per day), served questions and answers. Credits points for participation and correct answers. |
| `shop` | Shops, items and purchases. Debits and refunds points. Supports internal shops (owner confirmation) and external shops (promo codes). |

## Project layout

```
config/            settings, root URL configuration, WSGI/ASGI
apps/
  core/            utilities (no models)
  users/           authentication and user management
  organizations/   organizations
  events/          events and participation
  projects/        projects
  quizzes/         daily quiz
  shop/            shop and purchases
  rewards/         reserved, not currently wired into URLs
requirements.txt
manage.py
```

## API

All endpoints are served under `/api/`. Authentication uses JWT bearer tokens: send
`Authorization: Bearer <access token>` with each request. Obtain tokens from the login
endpoint and refresh them through the token refresh endpoint.

| Area | Base path |
| --- | --- |
| Authentication and users | `/api/auth/` |
| Organizations | `/api/organizations/` |
| Projects | `/api/projects/` |
| Events | `/api/events/` |
| Quizzes | `/api/quizzes/` |
| Shop | `/api/shop/` |

Supporting endpoints:

- `GET /health/` — service and database health check.
- `GET /admin/` — Django admin panel.
- `GET /api/schema/` — OpenAPI schema.
- `GET /api/docs/` — Swagger UI.

Interactive documentation at `/api/docs/` lists every endpoint with request and
response shapes.

### Authentication flow

1. `POST /api/auth/register/` creates a student account and returns a token pair.
2. `POST /api/auth/login/` exchanges email and password for an access and refresh token.
3. `POST /api/auth/token/refresh/` exchanges a valid refresh token for a new pair.
4. `POST /api/auth/logout/` blacklists a refresh token.

Access tokens are valid for 30 minutes; refresh tokens for 7 days and are rotated on
use.

### Roles

The platform defines four roles, stored on the user record:

- `admin` — full management across the platform.
- `organization` — owns an organization; publishes events, projects and quiz questions.
- `student` — earns and spends points.
- `shop_owner` — owns a shop; manages items and confirms purchases.

Public registration always creates a student. Privileged accounts are created by an
administrator.

## Notes

- Records are deactivated with an `is_active` flag rather than deleted, to preserve
  participation history and referential integrity.
- The configured time zone is `Asia/Almaty`; timestamps are stored in UTC.
- The `rewards` app is a placeholder and is not routed.


## Deployment & Infrastructure

The production stack runs on a single VPS with Docker Compose:

```
nginx:80 → gunicorn:8000 → Django → PostgreSQL + Redis
```
> **Note:** We'll migrate to university's servers soon

### Services

| Service | Image / Runtime | Role |
|---------|----------------|------|
| **nginx** | `nginx:1.25-alpine` | Reverse proxy, serves static & media files|
| **web** | Python 3.12 / Gunicorn | Django application server (3 workers, 120 s timeout) |
| **db** | `postgres:16-alpine` | Primary database |
| **redis** | `redis:7-alpine` | Cache backend (`django-redis`) |

### Container orchestration

All services are defined in [`docker-compose.yml`](docker-compose.yml) and connected through a shared `esg_network` bridge network. Persistent data is stored in named volumes:

- `postgres_data` — database files
- `static_files` — collected Django static assets
- `media_files` — user uploads (avatars, shop photos)

### Deployment

Deployment is configured through a GitHub Actions workflow ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)) triggered on pushes to `main`. The workflow SSHs into the VPS, pulls the latest code, rebuilds the web container, applies migrations, and restarts the stack.

> **Note:** The GitHub Actions deploy workflow is currently not operational (secrets and VPS access are not configured ask about that from collaborators).

### Key files for operations

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the Django web container |
| `entrypoint.sh` | Container startup: waits for DB, runs migrations, starts Gunicorn |
| `nginx/nginx.conf` | Reverse proxy rules, static/media serving |
| `.env` | Environment variables (database, Redis, secrets) — **not committed** |
| `.env.example` | Template for local development |

## Known Limitations & Future Work

| Area | Current State | Desired Improvement |
|------|--------------|-------------------|
| **Student ID validation** | `student_id` is a free-text field — only uniqueness is checked. No integration with a university API to validate that the ID belongs to a real enrolled student. | Integrate with a university platform API to verify student IDs, sync enrollment status, and auto-populate name / school on registration. |
| **Forgot / reset password** | Only `POST /api/auth/change-password/` exists, which requires the user to be logged in. | Add a full forgot-password flow with email-based reset token (send email → verify token → set new password). Requires an SMTP or transactional email service. |
| **Background / async tasks** | All operations run synchronously in the request-response cycle. No task queue, no periodic jobs. | Introduce Celery (or Django Q / Huey) for email sending, cache warming, periodic cleanup of expired quizzes, and background points recalculation. |
| **Student search for shop owners** | No dedicated endpoint for shop owners to look up a student by name / ID / email when confirming an internal purchase. | Add a `GET /api/shop/students/?q=...` endpoint (admin or shop-owner only) that searches users with `role=student`. |
| **QR code scanning** | External shops use manually typed 8-character promo codes — error-prone and slow. | Generate QR codes for promo codes on the purchase receipt; add a scan endpoint that accepts a QR payload. |
| **Events / projects automation** | Events and projects must be created manually through the API or seed command. | Add optional auto-publish scheduling, recurring event support, and an approval workflow before an event goes live. |
| **Notifications** | No notification system — students are not informed when a purchase is confirmed, an event is approved, or a quiz is available. | Implement push notifications (Firebase Cloud Messaging) and / or an in-app notification feed. |