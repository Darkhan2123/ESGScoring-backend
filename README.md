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

## Eco-Challenge

Eco-Challenge is a backend feature for student ESG activities.
It allows users to complete daily and weekly eco-tasks, earn XP, maintain streaks, receive badges, and appear in the leaderboard.

Main features

* Daily and weekly ESG challenges
* Challenge completion with XP rewards
* Photo or screenshot evidence for selected challenges
* Streak system
* XP multiplier based on active streak
* Eco levels based on total XP
* Achievement badges
* Personal Eco-Challenge profile
* Leaderboard
* Admin panel support

Seed initial data

To create default levels, challenges and badges, run:

```bash
python manage.py seed_challenges
```

This command creates:

* Eco-Challenge levels
* Daily challenges
* Weekly challenges
* Basic achievement badges

API endpoints

Eco-Challenge endpoints are available under:

```text
/api/challenges/
```

Available endpoints:

```text
GET  /api/challenges/daily/
GET  /api/challenges/weekly/
POST /api/challenges/{challenge_id}/complete/
GET  /api/challenges/profile/
GET  /api/challenges/completions/
GET  /api/challenges/badges/
GET  /api/challenges/badges/all/
GET  /api/challenges/leaderboard/
GET  /api/challenges/stats/
```

Most endpoints require JWT authentication.

Testing

Run the server:

```bash
python manage.py runserver
```

Open Swagger:

```text
http://127.0.0.1:8000/api/docs/
```

Use JWT authentication to test protected endpoints.

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
