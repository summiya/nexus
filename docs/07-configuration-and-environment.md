# Configuration & Environment Variable Conventions

**Document Type:** Engineering Convention  
**Applies To:** Backend, frontend, tests, Docker, CI/CD, migrations, local development  
**Status:** Canonical project guidance

## 1. Purpose

NEXUS uses environment variables as the source of truth for environment-specific configuration.

Application code, tests, migrations, Docker configuration, and frontend code MUST NOT duplicate or hard-code environment-specific values that already belong in environment configuration.

Examples of values that MUST come from environment configuration include:

- database URLs
- Redis URLs
- API base URLs
- hostnames
- ports
- usernames
- passwords
- tokens
- secrets
- allowed origins
- environment names
- feature/configuration values that vary by environment

The goal is to keep configuration centralized and avoid conflicting values across Python, TypeScript, tests, Docker, and CI.

---

## 2. Source of truth

Local development configuration is defined in the repository root `.env` file.

Example structure:

```text
nexus/
├── .env
├── .env.example
├── docker-compose.yml
├── backend/
├── frontend/
└── docs/
```

`.env` is local/private configuration and MUST NOT be committed if it contains secrets.

`.env.example` documents required variable names and safe example values.

Never copy the same environment values into multiple source files.

---

## 3. Backend configuration

Backend code MUST use the existing centralized settings implementation:

```text
backend/src/nexus/config/settings.py
```

The backend `Settings` class is responsible for loading configuration.

Application code should consume configuration through the settings object:

```python
from nexus.config.settings import settings

database_url = settings.database_url
redis_url = settings.redis_url
```

Do NOT add code like this to application modules:

```python
DATABASE_URL = "postgresql://user:password@localhost:5432/nexus"
REDIS_URL = "redis://localhost:6379/0"
```

Do NOT create a second settings/configuration implementation.

Do NOT add another `.env` loader if the existing `pydantic-settings` configuration already handles the root `.env`.

---

## 4. Backend tests

Tests MUST NOT become a second configuration source.

Avoid hard-coded test configuration like:

```python
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test",
)
```

or:

```python
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
```

Tests should use the existing settings/configuration boundary.

If a test requires isolation, it may derive an isolated temporary database/schema from the configured database connection, but it MUST NOT hard-code separate credentials in Python.

Migration or destructive tests MUST never run against an arbitrary production or developer database.

Use isolated test databases/schemas and make the isolation explicit.

---

## 5. Alembic and migrations

Alembic MUST use the same backend configuration boundary as the application.

Do not hard-code a connection URL in:

```text
alembic.ini
migrations/env.py
migration scripts
```

The migration environment should obtain the database URL from the existing backend settings/environment configuration.

Conceptually:

```text
.env / environment variables
        ↓
backend Settings
        ↓
Alembic env.py
        ↓
PostgreSQL
```

Migration scripts themselves should describe schema changes only and should not contain environment-specific credentials.

---

## 6. Docker and Docker Compose

Docker Compose should pass environment values into containers.

The application code inside a container should still read configuration through the normal settings layer.

Do not hard-code Docker-specific hostnames in Python application code.

Remember that hostnames can differ by execution environment:

```text
From the host machine:
localhost

From another Docker Compose service:
postgres
redis
backend
```

Those differences belong in environment configuration, not source code.

---

## 7. Frontend configuration

Frontend environment-specific configuration MUST come from Vite environment variables.

Client-exposed variables MUST use the `VITE_` prefix.

Example:

```env
VITE_APP_NAME=NEXUS
VITE_APP_ENV=development
VITE_API_BASE_URL=http://localhost:8000
```

Frontend code should read them through:

```ts
import.meta.env.VITE_API_BASE_URL
```

or through the project's existing frontend environment/configuration wrapper if one exists.

Do NOT hard-code:

```ts
const API_URL = "http://localhost:8000";
```

inside components, hooks, services, API clients, or tests when the value is environment-dependent.

---

## 8. Frontend secret rule

Anything exposed through `VITE_*` becomes available to browser-side code.

Therefore:

**Never put secrets in frontend environment variables.**

Do NOT expose:

- database credentials
- API secrets
- private tokens
- signing secrets
- service credentials
- internal-only secrets

Frontend configuration is public runtime/build configuration.

Secrets belong on the backend or in a managed secret store.

---

## 9. CI/CD configuration

CI must provide configuration through CI environment variables, service containers, or secret management.

Do NOT modify Python or TypeScript source code just to make CI pass.

For example, CI may provide:

```text
DATABASE_URL
REDIS_URL
APP_ENV
VITE_API_BASE_URL
```

through the workflow environment.

Sensitive values should use the CI platform's secret mechanism.

CI-specific configuration should not become hard-coded fallback configuration inside application code.

---

## 10. Local, test, staging, and production

Different environments may provide different values, but the application code should remain the same.

```text
Local
  ↓
environment values

Test
  ↓
environment values

Staging
  ↓
environment values / secret store

Production
  ↓
environment values / managed secret store
```

The code should consume configuration through the same interface regardless of environment.

---

## 11. Required engineering rules

When adding a new configuration value:

1. Add the variable to `.env.example` with a safe example.
2. Add it to the existing backend or frontend configuration boundary.
3. Read it through the centralized configuration layer.
4. Pass it through Docker/CI where necessary.
5. Do not duplicate it in tests.
6. Do not hard-code environment-specific URLs, hosts, ports, credentials, or secrets.
7. Do not create a second configuration system.
8. Keep secrets out of frontend code and committed files.

---

## 12. AI coding agent instructions

AI coding agents working in this repository MUST follow these rules.

Before adding configuration:

- inspect the existing backend `Settings` implementation
- inspect existing frontend environment/configuration handling
- inspect `.env.example`
- inspect `docker-compose.yml`
- inspect CI workflow configuration

Agents MUST NOT:

- create another backend settings class without an architecture decision
- add `python-dotenv` only to duplicate existing `pydantic-settings` behavior
- hard-code database or Redis URLs in Python
- hard-code API base URLs in frontend application code
- hard-code credentials in tests
- add environment-specific fallback values just to make tests pass
- commit secrets
- create separate conflicting `.env` loaders in multiple parts of the codebase

Agents SHOULD extend the existing configuration mechanism instead.

---

## 13. Preferred configuration flow

### Backend

```text
.env / deployment environment / CI secrets
                  ↓
        nexus.config.settings
                  ↓
          backend application
          Alembic migrations
          tests and tooling
```

### Frontend

```text
.env / build environment / CI configuration
                  ↓
             VITE_* values
                  ↓
     frontend environment wrapper
                  ↓
        components / API client
```

The configuration source may differ by environment, but application code should consume it consistently.

---

## 14. Review checklist

Before merging code that introduces configuration, verify:

- [ ] No environment-specific URL is hard-coded in application code.
- [ ] No credentials are hard-coded in application code or tests.
- [ ] Backend uses the existing `Settings` configuration.
- [ ] Frontend uses existing Vite environment handling.
- [ ] `.env.example` documents new variables.
- [ ] Docker receives configuration through environment variables.
- [ ] CI receives configuration through workflow environment/secrets.
- [ ] Tests do not duplicate `.env` values.
- [ ] Database tests are safely isolated.
- [ ] No frontend variable contains a secret.
- [ ] No duplicate configuration subsystem was introduced.
