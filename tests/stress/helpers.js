/**
 * helpers.js — Shared utilities for k6 stress tests
 *
 * Provides JWT-based authentication flows (register / login),
 * random data generators, and common assertion helpers.
 *
 * Usage (in your scenario):
 *   import { randomEmail, registerUser, getAuthHeaders } from './helpers.js';
 *
 * @module helpers
 */

import { check } from 'k6';
import http from 'k6/http';

// ---------------------------------------------------------------------------
// Random data generators
// ---------------------------------------------------------------------------

/** Generate a unique email using VU + iteration counters. */
export function randomEmail(vu = __VU, iter = __ITER) {
  const ts = Date.now();
  return `stress_${vu}_${iter}_${ts}@esg-test.local`;
}

/**
 * Generate a unique student ID.
 * Must be <= 50 chars (per the User model).
 */
export function randomStudentId(vu = __VU, iter = __ITER) {
  return `SID-${vu}-${iter}-${Date.now()}`;
}

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

/**
 * Register a new student user.
 *
 * @param {string} baseUrl  — e.g. "http://localhost"
 * @param {string} email
 * @param {string} password
 * @returns {{ token: string, refresh: string, user: object }} Auth payload
 * @throws {Error} If registration fails (non-201)
 */
export function registerUser(baseUrl, email, password) {
  const payload = JSON.stringify({
    email,
    full_name: `Stress Tester ${__VU}`,
    password,
    student_id: randomStudentId(),
    school: 'it_engineering',
  });

  const res = http.post(`${baseUrl}/api/auth/register/`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'register' },
  });

  check(res, {
    'register status is 201': (r) => r.status === 201,
  });

  if (res.status !== 201) {
    throw new Error(
      `Register failed (HTTP ${res.status}): ${res.body}`,
    );
  }

  const body = res.json();
  return { token: body.token, refresh: body.refresh, user: body.user };
}

/**
 * Log in with existing credentials.
 *
 * @param {string} baseUrl
 * @param {string} email
 * @param {string} password
 * @returns {{ token: string, refresh: string, user: object }}
 * @throws {Error} If login fails (non-200)
 */
export function loginUser(baseUrl, email, password) {
  const payload = JSON.stringify({ email, password });

  const res = http.post(`${baseUrl}/api/auth/login/`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'login' },
  });

  check(res, {
    'login status is 200': (r) => r.status === 200,
  });

  if (res.status !== 200) {
    throw new Error(
      `Login failed (HTTP ${res.status}): ${res.body}`,
    );
  }

  const body = res.json();
  return { token: body.token, refresh: body.refresh, user: body.user };
}

// ---------------------------------------------------------------------------
// Header helpers
// ---------------------------------------------------------------------------

/**
 * Return the `Authorization` header for a bearer token.
 *
 * @param {string} token — JWT access token
 * @returns {{ Authorization: string }}
 */
export function authHeader(token) {
  return { Authorization: `Bearer ${token}` };
}

/**
 * Common JSON headers combined with auth.
 *
 * @param {string} token
 * @returns {{ Authorization: string, 'Content-Type': string }}
 */
export function authJsonHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}
