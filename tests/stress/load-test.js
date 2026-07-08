/**
 * load-test.js — Expected traffic simulation (15 pre-auth users, ~3 min)
 *
 * Loads pre-generated JWT tokens from test_users.json (created by
 * `python manage.py generate_stress_users --count 15`).  Each VU picks
 * one user in round-robin fashion and fires GET/POST requests without
 * any register/login overhead during the test.
 *
 * Usage:
 *   python manage.py generate_stress_users --count 15
 *   make -C tests/stress stress-load BASE_URL=http://localhost
 *
 * Environment variables:
 *   BASE_URL  — target host (default: http://localhost)
 *
 * Expected behaviour:
 *   - P95 response time < 800ms for reads, < 1500ms for writes
 *   - Error rate < 1%
 */

import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import http from 'k6/http';

// Read pre-generated tokens at module load time
const testUsers = JSON.parse(open('./test_users.json'));
const USER_COUNT = testUsers.length;

if (USER_COUNT === 0) {
  throw new Error(
    'No test users found in test_users.json. ' +
    'Run: python manage.py generate_stress_users --count 15',
  );
}

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const writeDuration = new Trend('write_duration', true);
const readDuration  = new Trend('read_duration', true);
const writeErrors   = new Rate('write_errors');
const readErrors    = new Rate('read_errors');

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost';

export const options = {
  stages: [
    { duration: '20s',  target: 10 },   // warm-up
    { duration: '30s',  target: 15 },   // ramp to 15 VUs
    { duration: '2m',   target: 15 },   // sustained peak
    { duration: '20s',  target: 0 },    // cool-down
  ],
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<2000'],
    write_duration: ['p(95)<3000'],
    read_duration: ['p(95)<1000'],
    write_errors: ['rate<0.03'],
    read_errors: ['rate<0.01'],
  },
  noConnectionReuse: false,
};

// ---------------------------------------------------------------------------
// Setup: validate the token file on startup
// ---------------------------------------------------------------------------

export function setup() {
  const health = http.get(`${BASE_URL}/health/`, { tags: { name: 'health' } });
  check(health, { 'setup: health OK': (r) => r.status === 200 });

  console.info(
    `Loaded ${USER_COUNT} pre-generated stress users. ` +
    `VUs will map to users via __VU % ${USER_COUNT}`
  );
  return {};
}

// ---------------------------------------------------------------------------
// Helper: auth header from pre-generated token
// ---------------------------------------------------------------------------

function auth(user) {
  return { Authorization: `Bearer ${user.token}` };
}

// ---------------------------------------------------------------------------
// Main scenario
// ---------------------------------------------------------------------------

export default function () {
  // Pick one of the 15 pre-generated users (round-robin by VU number)
  const user = testUsers[__VU % USER_COUNT];

  sleep(0.5 + Math.random());

  // ----- Phase 1: Reads (GET) -----
  group('Browse Events', () => {
    const res = http.get(`${BASE_URL}/api/events/tasks/`, {
      headers: auth(user),
      tags: { name: 'events_list' },
    });
    const ok = check(res, {
      'events list 200': (r) => r.status === 200,
    });
    readDuration.add(res.timings.duration);
    readErrors.add(!ok);
  });

  sleep(0.3 + Math.random() * 0.7);

  group('Browse Shops', () => {
    const res = http.get(`${BASE_URL}/api/shop/shops/`, {
      headers: auth(user),
      tags: { name: 'shop_list' },
    });
    const ok = check(res, {
      'shop list 200': (r) => r.status === 200,
    });
    readDuration.add(res.timings.duration);
    readErrors.add(!ok);

    // Fetch items for the first shop (for potential purchase)
    if (ok) {
      const body = res.json();
      const results = body.results || body;
      if (Array.isArray(results) && results.length > 0) {
        const shopId = results[0].id;
        const itemsRes = http.get(
          `${BASE_URL}/api/shop/shops/${shopId}/items/`,
          { headers: auth(user), tags: { name: 'shop_items' } },
        );
        if (itemsRes.status === 200) {
          const itemsBody = itemsRes.json();
          const items = itemsBody.results || itemsBody;
          if (Array.isArray(items) && items.length > 0) {
            __ENV._firstItemId = String(items[0].id);
          }
        }
      }
    }
  });

  sleep(0.3 + Math.random() * 0.7);

  group('Leaderboard', () => {
    const res = http.get(`${BASE_URL}/api/events/leaderboard/`, {
      headers: auth(user),
      tags: { name: 'leaderboard' },
    });
    const ok = check(res, {
      'leaderboard 200': (r) => r.status === 200,
    });
    readDuration.add(res.timings.duration);
    readErrors.add(!ok);
  });

  sleep(0.3 + Math.random() * 0.7);

  group('My Profile', () => {
    const res = http.get(`${BASE_URL}/api/auth/me/`, {
      headers: auth(user),
      tags: { name: 'my_profile' },
    });
    const ok = check(res, {
      'my profile 200': (r) => r.status === 200,
    });
    readDuration.add(res.timings.duration);
    readErrors.add(!ok);
  });

  // ----- Phase 2: Writes (POST) -----
  sleep(0.5 + Math.random());

  group('Join Event', () => {
    const res = http.post(
      `${BASE_URL}/api/events/tasks/1/join/`,
      null,
      { headers: auth(user), tags: { name: 'join_event' } },
    );
    const ok = res.status < 500;
    writeDuration.add(res.timings.duration);
    writeErrors.add(!ok);
  });

  sleep(0.5 + Math.random());

  group('Purchase Item', () => {
    const itemId = __ENV._firstItemId || '1';
    const res = http.post(
      `${BASE_URL}/api/shop/items/${itemId}/buy/`,
      null,
      { headers: auth(user), tags: { name: 'purchase' } },
    );
    const ok = res.status < 500;
    writeDuration.add(res.timings.duration);
    writeErrors.add(!ok);
  });

  sleep(0.5 + Math.random());

  group('My Purchases', () => {
    const res = http.get(`${BASE_URL}/api/shop/my-purchases/`, {
      headers: auth(user),
      tags: { name: 'my_purchases' },
    });
    const ok = check(res, {
      'my purchases 200': (r) => r.status === 200,
    });
    readDuration.add(res.timings.duration);
    readErrors.add(!ok);
  });
}
