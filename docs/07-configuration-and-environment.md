# Configuration & Environment Variable Conventions

**Document Type:** Engineering Convention  
**Applies To:** Backend, frontend, tests, Docker, CI/CD, migrations, and local development
**Status:** Canonical project guidance

## 1. Purpose

NEXUS uses environment variables as the source of truth for environment-specific configuration.

Application code, tests, migrations, Docker configuration, and frontend code MUST NOT duplicate or hard-code environment-specific values that belong in configuration. This includes database and Redis URLs, API endpoints, credentials, secrets, allowed origins, environment names, model allowlists, and feature limits.

The goal is one configuration boundary and one explicit application composition path.

---

## 2. Source of truth

Local development configuration is defined in the repository root `.env` file.

```text
nexus/
├── .env
├── .env.example
├── docker-compose.yml
├── backend/
├── frontend/
└── docs/
```

`.env` is private local configuration and MUST NOT be committed when it contains secrets. `.env.example` documents every supported variable using safe values.

Deployment platforms and CI may supply the same variables directly or through a managed secret store.

---

## 3. Backend settings boundary

Backend configuration is defined by:

```text
backend/src/nexus/config/settings.py
```

`Settings` is the typed configuration value object. `load_settings()` is the explicit loader for application and CLI entrypoints.

```python
from nexus.config.settings import load_settings

settings = load_settings()
```

Ordinary runtime modules MUST NOT import a module-global settings object. Instead, the application entrypoint loads settings once and passes that exact object through composition.

```text
.env / process environment
          ↓
     load_settings()
          ↓
      create_app(settings)
          ↓
 database / authentication / LLM / conversations
```

Do not add another settings implementation or another `.env` loader.

---

## 4. Composition root

`create_app()` is the application composition root. It owns construction of application-scoped dependencies from one `Settings` instance.

The resulting dependencies are stored in one `AppContainer`. FastAPI exposes only
`app.state.container`; transport dependencies resolve database, authentication,
LLM, Conversation, and event capabilities from that container.

```text
create_app(settings)
        ├── logging
        ├── SQLAlchemy engine and session factory
        ├── Redis-backed rate limiter
        ├── email provider
        ├── token services
        ├── LLM gateway and model policy
        ├── Conversation services
        └── event publisher
```

Application services MUST NOT silently reconstruct these dependencies from global environment state.

Use ordinary constructors and FastAPI dependencies. A separate dependency-injection framework or service locator is not required.

---

## 5. Dependency lifetimes

Dependencies must have an intentional lifetime.

| Dependency | Lifetime |
|---|---|
| `Settings` | Application |
| SQLAlchemy engine/session factory | Application |
| Redis client/rate limiter | Application |
| Access-token verifier | Application |
| LLM gateway/model policy | Application |
| Email provider | Application |
| SQLAlchemy `Session` | Request or short operation |
| Repositories using a session | Request or short operation |
| Use cases using request repositories | Request |

Application startup/shutdown owns shared resources. Database operations own short-lived sessions and transactions.

---

## 6. Backend tests

Tests MUST NOT depend on the production module-level ASGI application.

API tests should construct a fresh app with explicit settings:

```python
settings = Settings(_env_file=None, ...)
app = create_app(settings, ...)
```

FastAPI dependency overrides may replace request-level services. Constructor injection may replace application-level dependencies such as the LLM gateway, rate limiter, email provider, or database resource.

A required isolation test must prove that two applications created with different settings keep separate:

- database engines/session factories;
- Redis/rate-limiter configuration;
- token signing and verification configuration;
- model/provider configuration.

Persistence tests may load the configured administrative database URL at the test entrypoint, but must create isolated temporary databases or schemas. They must never target an arbitrary production or developer database.

---

## 7. Alembic and migrations

Alembic uses the same `Settings` loader at its CLI entrypoint.

```text
environment / root .env
          ↓
     load_settings()
          ↓
    migrations/env.py
          ↓
       PostgreSQL
```

Tests may inject `config.attributes["database_url"]` for an isolated database. Migration scripts must contain schema changes only, never credentials or environment-specific URLs.

---

## 8. Docker and Docker Compose

Docker Compose passes environment values into containers. The backend still consumes them through `Settings`; Docker-specific hostnames must not appear in Python source.

```text
Host process: localhost
Compose service: postgres / redis / backend
```

When a backend setting is added, update all of the following where applicable:

1. `Settings`;
2. `.env.example`;
3. `docker-compose.yml`;
4. CI environment configuration;
5. tests for parsing and propagation.

Model allowlists and Conversation limits are configuration and must be forwarded to the backend container just like database and authentication values.

---

## 9. Frontend configuration

Frontend environment-specific configuration comes from Vite variables using the `VITE_` prefix.

```env
VITE_APP_NAME=NEXUS
VITE_APP_ENV=development
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Frontend code should read these values through the existing environment wrapper. Do not hard-code API endpoints in components, hooks, stores, or API clients.

Anything exposed through `VITE_*` is public browser configuration. Database credentials, API secrets, signing keys, service tokens, and other secrets must never use the `VITE_` prefix.

---

## 10. CI/CD configuration

CI supplies configuration through workflow environment variables, service containers, and secret management. Source code must not be changed merely to make CI pass.

Sensitive production values belong in the deployment platform's secret manager. Safe deterministic CI values may be declared in workflow configuration.

Local, test, staging, and production should run the same application code with different configuration inputs.

---

## 11. Required engineering rules

When adding a configuration value:

1. Add it to the existing `Settings` model.
2. Add it to `.env.example` with a safe example.
3. Pass the `Settings` value through the composition root.
4. Forward it through Docker and CI where necessary.
5. Add parsing and propagation tests.
6. Do not read environment variables directly from business/application modules.
7. Do not create a second configuration subsystem.
8. Do not log secrets or complete connection strings.
9. Do not put secrets in frontend configuration.

---

## 12. Prohibited patterns

Agents and engineers MUST NOT introduce:

- a second backend settings class without an architecture decision;
- `python-dotenv` to duplicate `pydantic-settings` behavior;
- module-import-time database engines or Redis clients;
- module-global production ASGI applications used by tests;
- service locators or DI frameworks for ordinary FastAPI construction;
- hard-coded database, Redis, API, or provider URLs;
- hard-coded credentials in source or tests;
- frontend secrets;
- environment-specific fallback values added only to bypass validation.

---

## 13. Preferred configuration flow

### Backend

```text
.env / deployment environment / CI secrets
                  ↓
             Settings
                  ↓
             create_app
                  ↓
       explicit component builders
                  ↓
     request-scoped FastAPI dependencies
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

---

## 14. Review checklist

Before merging configuration or composition changes, verify:

- [ ] One explicit `Settings` instance configures the app.
- [ ] No runtime module imports global settings.
- [ ] Database and Redis resources are not created at module import time.
- [ ] Shared resources have shutdown behavior.
- [ ] Database sessions remain short-lived.
- [ ] Authentication signing and verification use the same app configuration.
- [ ] Two differently configured app instances remain isolated.
- [ ] `.env.example` documents new variables.
- [ ] Docker and CI forward the variables.
- [ ] Tests create fresh app instances.
- [ ] No secrets are exposed to logs or frontend code.
- [ ] No duplicate configuration or DI framework was introduced.
