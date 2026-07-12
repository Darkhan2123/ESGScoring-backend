# Contributing to ESG Community Platform — Backend

Thank you for considering contributing! This document outlines the guidelines for contributing to this project.

## Table of Contents

- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Code Conventions](#code-conventions)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Questions?](#questions)

## Getting Started

1. Ensure you have **Python 3.12** installed.
2. Follow the [README](README.md#getting-started) instructions to clone, set up a virtual environment, install dependencies, and configure your database.
3. Verify your setup by running the test suite (see below).

## How to Contribute

1. **Fork** the repository on GitHub.
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
   Use prefixes like `feat/`, `fix/`, `refactor/`, `docs/`, `chore/` for clarity.
3. **Make your changes**, following the [code conventions](#code-conventions).
4. **Write or update tests** for your changes. Follow the project's [testing strategy](#testing).
5. **Run the full test suite** to ensure nothing is broken:
   ```bash
   python manage.py test
   ```
6. **Commit your changes** with clear, descriptive commit messages (see [Conventional Commits](https://www.conventionalcommits.org/) style preferred):
   ```
   feat: add organisation event filter by date range
   fix: correct points deduction on purchase refund
   docs: update README with test instructions
   ```
7. **Push your branch** to your fork and open a **Pull Request** against the `main` branch.

## Code Conventions

### Python & Django

- Follow [PEP 8](https://peps.python.org/pep-0008/) for code style.
- Use **type hints** everywhere (the project uses `from __future__ import annotations`).
- Formatting: use [ruff](https://docs.astral.sh/ruff/) (or similar) — run it before committing.
- Keep views **thin**: business logic goes in per-app `services.py`.
- Use `select_for_update()` + `F()` expressions for any operation that modifies the points balance, to avoid race conditions.
- Prefer `update_or_create()` for seed/idempotent operations.

### App structure

```
apps/<app_name>/
├── models.py
├── views.py
├── serializers.py
├── services.py          # Business logic layer
├── urls.py
├── admin.py
├── tests/
│   ├── __init__.py
│   ├── test_views.py    # API endpoint tests
│   └── test_services.py # Service/business logic tests
```

### Git conventions

- Keep commits small and focused on a single concern.
- Use present tense ("Add feature", not "Added feature").
- Reference issue numbers when applicable: `fix: resolve login redirect (#42)`.

## Testing

All contributions **must** include tests.

- Tests use Django's built-in `TestCase` and DRF's `APITestCase`.
- Place tests in `apps/<app>/tests/` as `test_views.py` or `test_services.py`.
- Follow the **1 good case + 2 bad cases** pattern:
  1. A happy-path test verifying the expected success response.
  2. An authentication/permission test (unauthenticated or wrong role).
  3. A validation error test (invalid payload, duplicate name, etc.).
- Run the full suite before opening a PR:
  ```bash
  python manage.py test
  ```
- See the [Running Tests](README.md#running-tests) section in the README for details on test-aware settings and stress testing.

## Pull Request Process

1. Ensure your PR description clearly describes the problem and solution.
2. Verify all tests pass and there are no merge conflicts.
3. A maintainer will review your PR. They may request changes or ask questions.
4. Once approved, your PR will be merged by a maintainer.

### PR checklist

- [ ] Tests pass (`python manage.py test`)
- [ ] New code includes tests following the 1 good + 2 bad pattern
- [ ] Type hints are added for all new functions/methods
- [ ] No linting errors
- [ ] Documentation (README, docstrings) is updated if needed
- [ ] Commit messages follow conventional commits format

## Questions?

If you have questions or need help, feel free to open a Discussion or an Issue on GitHub.