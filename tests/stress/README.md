# Stress Testing — ESGScoring Backend

[k6](https://k6.io/) load tests for the ESG Community Platform backend.
Designed to validate behaviour under concurrent traffic, especially around
`select_for_update()` point-spending, Redis caching, and DRF throttling.

## Prerequisites

### Install k6

```bash
# Linux (Debian/Ubuntu)
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 \
  --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6

# macOS
brew install k6

# Docker
docker pull grafana/k6
```

Verify: `k6 version`

### Seed test data

The stress tests assume the database has **at least 1 active event (task)
and 1 active shop with items**. Use the built-in seed command:

```bash
python manage.py seed
```

> **Note:** The seed command creates sample organizations, events, shops,
> and items. Re-run it after a DB reset.

## Running the tests

### 1. Start the target stack

Point k6 at **the Docker production-like stack** (Nginx + Gunicorn), not
`manage.py runserver`. The single-process dev server cannot simulate
realistic worker contention.

```bash
docker-compose up --build -d
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py seed
```

### 2. Run smoke test (quick sanity)

```bash
k6 run tests/stress/smoke-test.js -e BASE_URL=http://localhost
```

Expect: ~5–10s, 1 VU, all checks pass.

### 3. Generate test users for load test

The load test requires pre-generated JWT tokens for test users. Generate them inside the Docker container and copy the file to your local repository:

```bash
# Generate test users inside the container
docker-compose exec web python manage.py generate_stress_users --count 15

# Copy the generated file from container to local repository
docker-compose cp web:/app/tests/stress/test_users.json tests/stress/test_users.json
```

> **Important:** This step is necessary because docker-compose.yml doesn't mount the source code as a volume, so files created inside the container aren't accessible on the host.

### 4. Run load test (15 concurrent users)

```bash
# Using Makefile
make -C tests/stress stress-load-json

# Or using k6 directly
k6 run tests/stress/load-test.js \
  -e BASE_URL=http://localhost \
  --out json=reports/load-test-report.json
```

Expect: ~3 minutes, gradual ramp-up to 15 VUs.

> **Note:** During load tests you may see `400` responses with errors like **"already exists"** or **"already taken"** (e.g., duplicate shop names, organization names, or student IDs). These are expected — concurrent requests hit the unique constraint validation before the first request commits. They confirm the business rules work correctly, not a backend failure. It can be changed if it's inconsistent.

> **Note:** HTML output may not be available in older k6 versions. Use JSON or CSV output instead.

### 5. (Optional) Output formats

| Format | Command flag | Use case |
|--------|-------------|----------|
| **JSON** | `--out json=report.json` | Programmatic analysis |
| **CSV** | `--out csv=report.csv` | Spreadsheets |
| **web-dashboard** | `--out web-dashboard` | Visual dashboard (live) |
| **None** | _(omit)_ | Terminal summary only |

> **Note:** HTML output is not available in older k6 versions. Use JSON/CSV or web-dashboard instead.



## Test scenarios

| Script | VUs | Duration | Focus |
|--------|-----|----------|-------|
| `smoke-test.js` | 1 | ~30s | Full end-to-end flow validation |
| `load-test.js` | 10→15→0 | ~3 min | Sustained expected traffic (15 pre-generated users) |

### Endpoints exercised

| Endpoint | Method | Category |
|----------|--------|----------|
| `/health/`        | GET    | Health check |
| `/api/auth/register/`  | POST | Auth (write) |
| `/api/auth/login/`     | POST | Auth (write) |
| `/api/auth/token/refresh/` | POST | Auth (write) |
| `/api/auth/logout/`    | POST | Auth (write) |
| `/api/auth/me/`        | GET  | Profile (read) |
| `/api/events/tasks/`   | GET  | Events list (cached read) |
| `/api/events/leaderboard/` | GET | Leaderboard (read) |
| `/api/events/tasks/{id}/join/` | POST | Event join (write, `select_for_update`) |
| `/api/shop/shops/`     | GET  | Shop list (cached read) |
| `/api/shop/shops/{id}/items/` | GET | Shop items (cached read) |
| `/api/shop/items/{id}/buy/` | POST | Purchase (write, `select_for_update`) |
| `/api/shop/my-purchases/` | GET | Purchase history (read) |

## Interpreting results

### Key metrics

| Metric | What it measures | Good | Warning |
|--------|-----------------|------|---------|
| `http_req_duration p(95)` | 95th percentile response time | < 800ms | > 2s |
| `http_req_failed` | % of failed requests | < 1% | > 2% |
| `read_duration p(95)` | GET request latency | < 500ms | > 1s |
| `write_duration p(95)` | POST/PATCH latency | < 1.5s | > 3s |
| `write_errors` | % of write failures | < 1% | > 3% |
| `http_reqs` | Throughput (req/s) | Depends on hardware | — |

### What to look for

1. **P95 latency spikes** — Gunicorn worker contention or DB query degradation.
2. **429 Too Many Requests** — Throttling limits are being hit (expected at
   high concurrency; track the rate).
3. **5xx errors** — Real backend bugs exposed under load.
4. **`select_for_update()` deadlocks** — Watch for `40P01` PostgreSQL errors
   in the logs.
5. **Redis connection errors** — The cache backend may be overwhelmed.

## Disabling throttling (for load tests)

DRF throttles `auth` at 5 requests/minute. With 50 VUs registering/logging
in, you will hit this quickly. **For load tests**, temporarily raise or
remove throttling:

```python
# config/settings.py — override for testing
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['auth'] = '1000/minute'
```

Or use environment variables:
```python
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': os.getenv('THROTTLE_ANON', '60/minute'),
    'user': os.getenv('THROTTLE_USER', '1000/hour'),
    'auth': os.getenv('THROTTLE_AUTH', '1000/minute'),
    'quiz': os.getenv('THROTTLE_QUIZ', '10/minute'),
    'purchases': os.getenv('THROTTLE_PURCHASES', '100/minute'),
}
```

## File layout

```
tests/stress/
├── helpers.js          # Shared: randomEmail, registerUser, loginUser, authHeader
├── smoke-test.js       # 1 VU full-flow sanity check
├── load-test.js        # 15 VU sustained load simulation
├── test_users.json     # Pre-generated test users (created by generate_stress_users)
└── README.md           # This file
```

## Next steps (v2 ideas)

- [ ] **Soak test** — 80 VUs for 30 minutes to detect memory leaks
- [ ] **Stress test** — Ramp up to 200+ VUs to find the breaking point
- [ ] **Redis burst test** — Invalidate cache families under load
- [ ] **Points race test** — 20 concurrent purchase requests on 1 user
- [ ] **CI integration** — Run smoke test as part of the CI pipeline


### If you see failures

| Symptom | Likely cause | How to fix |
|---------|-------------|------------|
| `test_users.json not found` | Load test requires pre-generated test users | Run `docker-compose exec web python manage.py generate_stress_users --count 15` then copy the file: `docker-compose cp web:/app/tests/stress/test_users.json tests/stress/test_users.json` |
| 429 on auth | `auth` throttle (5/min) too low for 50 VUs | Disable or raise throttle for tests |
| 500 on purchase | `select_for_update()` deadlock | Check DB lock timeouts |
| Slow event list | Cache miss stampede | Verify Redis is running and connected |
| Connection refused | Gunicorn workers saturated | Increase `--workers` in entrypoint.sh |
| `invalid output type 'html'` | Older k6 version doesn't support HTML output | Use JSON or CSV output instead |
| 400 / **"already exists"** errors | Multiple concurrent requests try to create entities with the same name / ID, hitting unique constraint validation | Expected under concurrency — these validate business rules, not a backend bug. Check they remain below ~5 % of write requests. May be changed to keep consistency. |

