/**
 * smoke-test.js — Quick sanity check (1–2 VUs, ~30s)
 *
 * Validates that all critical endpoint groups are reachable and
 * return the expected status codes.  Run this BEFORE any larger
 * load test to catch deployment or config issues early.
 *
 * Usage:
 *   k6 run tests/stress/smoke-test.js -e BASE_URL=http://localhost
 *
 * Environment variables:
 *   BASE_URL  — target host (default: http://localhost)
 *   PASSWORD  — password used for test users (default: StressTest123!)
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import {
  randomEmail,
  registerUser,
  loginUser,
  authHeader,
  authJsonHeaders,
} from './helpers.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_failed: ['rate<0.01'], // No more than 1% errors
    http_req_duration: ['p(95)<3000'], // 95% of requests under 3s
  },
};

// ---------------------------------------------------------------------------
// Main scenario
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost';
const PASSWORD = __ENV.PASSWORD || 'StressTest123!';

export default function () {
  // ---- Step 1: Health check ----
  group('Health check', () => {
    const res = http.get(`${BASE_URL}/health/`, {
      tags: { name: 'health' },
    });
    check(res, {
      'health returns 200': (r) => r.status === 200,
    });
    sleep(0.5);
  });

  // ---- Step 2: Register a new user ----
  group('Register', () => {
    const email = randomEmail();
    const result = registerUser(BASE_URL, email, PASSWORD);
    check(result, {
      'register returns access token': (r) => typeof r.token === 'string' && r.token.length > 0,
      'register returns refresh token': (r) => typeof r.refresh === 'string' && r.refresh.length > 0,
      'register returns user object': (r) => typeof r.user === 'object' && r.user.id > 0,
    });
    // Save for subsequent steps
    __ENV._token = result.token;
    __ENV._refresh = result.refresh;
    __ENV._userId = String(result.user.id);
    sleep(0.5);
  });

  const token = __ENV._token;

  // ---- Step 3: Events ----
  group('Events list', () => {
    const res = http.get(`${BASE_URL}/api/events/tasks/`, {
      headers: authHeader(token),
      tags: { name: 'events_list' },
    });
    check(res, {
      'events list returns 200': (r) => r.status === 200,
      'events list has results key': (r) => {
        const body = r.json();
        return body.results !== undefined || Array.isArray(body);
      },
    });
    sleep(0.5);
  });

  group('Leaderboard', () => {
    const res = http.get(`${BASE_URL}/api/events/leaderboard/`, {
      headers: authHeader(token),
      tags: { name: 'leaderboard' },
    });
    check(res, {
      'leaderboard returns 200': (r) => r.status === 200,
    });
    sleep(0.5);
  });

  // ---- Step 4: Shops ----
  group('Shop list', () => {
    const res = http.get(`${BASE_URL}/api/shop/shops/`, {
      headers: authHeader(token),
      tags: { name: 'shop_list' },
    });
    check(res, {
      'shop list returns 200': (r) => r.status === 200,
      'shop list has results': (r) => {
        const body = r.json();
        return body.results !== undefined || Array.isArray(body);
      },
    });

    // Save the first shop ID for detail/items requests
    const body = res.json();
    const results = body.results || body;
    if (Array.isArray(results) && results.length > 0) {
      __ENV._shopId = String(results[0].id);
    }
    sleep(0.5);
  });

  // ---- Step 5: Auth refresh ----
  group('Token refresh', () => {
    const payload = JSON.stringify({ refresh: __ENV._refresh });
    const res = http.post(`${BASE_URL}/api/auth/token/refresh/`, payload, {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'token_refresh' },
    });
    check(res, {
      'token refresh returns 200': (r) => r.status === 200,
      'token refresh returns new access': (r) => {
        const body = r.json();
        return typeof body.token === 'string';
      },
    });
    sleep(0.5);
  });

  // ---- Step 6: Profile ----
  group('My profile', () => {
    const res = http.get(`${BASE_URL}/api/auth/me/`, {
      headers: authHeader(token),
      tags: { name: 'my_profile' },
    });
    check(res, {
      'my profile returns 200': (r) => r.status === 200,
      'profile has email': (r) => typeof r.json().email === 'string',
    });
    sleep(0.5);
  });

  // ---- Step 7: Logout ----
  group('Logout', () => {
    const payload = JSON.stringify({ refresh: __ENV._refresh });
    const res = http.post(`${BASE_URL}/api/auth/logout/`, payload, {
      headers: authJsonHeaders(token),
      tags: { name: 'logout' },
    });
    check(res, {
      'logout returns 200': (r) => r.status === 200,
    });
  });
}
