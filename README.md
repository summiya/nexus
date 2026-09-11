# 🚀 NEXUS

### AI Workspace · AI Control Layer · Agentic AI Platform

> **Use your knowledge. Connect your tools. Choose your AI. Delegate real work.**

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LLMs](https://img.shields.io/badge/LLMs-412991?style=for-the-badge)](https://openai.com/)
[![RAG](https://img.shields.io/badge/RAG-FF6F00?style=for-the-badge)](#)
[![Agentic AI](https://img.shields.io/badge/Agentic_AI-7B2CBF?style=for-the-badge)](#)
[![MCP](https://img.shields.io/badge/MCP-0A7B83?style=for-the-badge)](https://modelcontextprotocol.io/)
[![APIs](https://img.shields.io/badge/APIs-007ACC?style=for-the-badge)](#)
[![Cloud](https://img.shields.io/badge/Cloud-4285F4?style=for-the-badge)](#)
[![Git](https://img.shields.io/badge/Git-F05032?style=for-the-badge&logo=git&logoColor=white)](https://git-scm.com/)

**Python** → **LLMs** → **RAG / Knowledge** → **Agentic AI** → **MCP / Tools** → **Cloud**

---

## 📌 Project Overview

NEXUS is a **user-first AI workspace and AI control layer** that helps people and companies use AI with their own knowledge, tools, and systems.

The long-term goal is to move AI beyond simple chat:

**Conversation → Knowledge → RAG → Agents → Tools / MCP → Real Work**

NEXUS is designed as a horizontal platform that can be used across software engineering, product, sales, marketing, operations, finance, research, and other knowledge-work environments.

---

## 🎯 Product Vision

> **Build a place where people can use AI with their own knowledge and tools, and delegate real work to intelligent agents while keeping control over their data, permissions, models, and systems.**

NEXUS acts as a control layer between users, their knowledge, connected tools, MCP servers, agents, and AI models.

```text
                         USER
                           |
                           v
                    +-------------+
                    |    NEXUS    |
                    +------+------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
      KNOWLEDGE         AGENTS           TOOLS
          |                |                |
          v                v                v
         RAG          ORCHESTRATION       MCP
          |                |                |
          +----------------+----------------+
                           |
                           v
                         LLMs
                           |
                           v
                        RESULT
```

---

## ✨ Main Capabilities

### 🧠 Knowledge & RAG

NEXUS can work with personal and company knowledge through retrieval, permissions, and context management.

The goal is to keep knowledge under the user's control while sending only the relevant context to the selected model.

```text
Your Knowledge
      |
      v
    NEXUS
      |
      v
Permissions
      |
      v
RAG / Retrieval
      |
      v
Relevant Context
      |
      v
   LLM / Agent
```

### 🧠 LLMs

NEXUS is designed around a multi-model architecture rather than being permanently tied to one AI provider.

```text
                  NEXUS
                    |
          +---------+---------+
          |         |         |
          v         v         v
        LLM A     LLM B   Private LLM
```

NEXUS uses provider-independent interfaces so model providers can be added, replaced, or routed without coupling application-level agent logic to a specific vendor.

### 🤖 Agentic AI

Agents allow users to move from asking questions to delegating real work.

An agent can eventually:

- Understand a goal
- Plan multiple steps
- Retrieve knowledge
- Use approved tools
- Use MCP servers
- Perform actions
- Verify results
- Request human approval
- Report what it completed

Agents operate within explicit permissions, project boundaries, execution limits, and tool policies.

Example:

> "Check this GitHub issue, investigate the problem, fix it, run the tests, push the branch, and open a pull request."

### 🔗 MCP & Custom MCP

NEXUS is designed to support:

- Existing MCP servers
- Custom MCP servers
- Private MCP servers
- Self-hosted MCP servers

Companies can expose their own internal capabilities through MCP and allow NEXUS agents to use them under controlled permissions.

```text
Company Systems
      |
      +-- CRM
      +-- ERP
      +-- Internal APIs
      +-- Other Systems
              |
              v
      Custom / Private MCP
              |
              v
            NEXUS
              |
              v
          AI Agent
```

MCP integrations are subject to NEXUS authentication, authorization, tool permissions, project boundaries, and security policies.

### 🛠️ Tools & Integrations

NEXUS is designed to connect AI to the systems people already use, including:

- APIs
- Cloud services
- Databases
- Developer tools
- Business applications
- Internal systems
- External services

Tools are treated as controlled capabilities rather than unrestricted model actions.

### 🔐 Security & Permissions

NEXUS is designed around security and control from the beginning.

The platform controls:

- Identity
- Authentication
- Authorization
- Tenant isolation
- Project isolation
- Knowledge access
- Tool permissions
- Agent permissions
- MCP permissions
- Human approvals
- Audit logs
- Secret management

LLM output is never treated as the final security authority.

---

## 🧱 Technology Direction

| Layer | Direction |
|---|---|
| Frontend | **React + TypeScript** |
| Backend | **Python + FastAPI** |
| AI | **LLMs / Multi-model architecture** |
| Knowledge | **RAG / Retrieval / Embeddings** |
| Intelligence | **Agent orchestration** |
| Connectivity | **MCP + APIs + integrations** |
| Primary Database | **PostgreSQL** |
| Vector Search | **pgvector** |
| Object Storage | **Azure Blob Storage** |
| Cache / Transient Infrastructure | **Azure Managed Redis** |
| Secret Management | **Azure Key Vault** |
| Cloud Platform | **Microsoft Azure** |
| Security | **Authentication + Authorization + Permissions** |
| Quality | **Automated testing + linting + type checking** |
| Observability | **Logging + auditability** |
| Version Control | **Git / GitHub** |

NEXUS is designed to use provider-independent interfaces so infrastructure and AI providers can evolve without unnecessarily coupling the core platform to specific vendors.

---

## 🏗️ High-Level Architecture

```text
                              USER
                                |
                                v
                     +---------------------+
                     |        NEXUS        |
                     |                     |
                     | Workspace           |
                     | Projects            |
                     | Conversations       |
                     | Knowledge           |
                     | Agents              |
                     +----------+----------+
                                |
                         CONTROL LAYER
                                |
             +------------------+------------------+
             |                  |                  |
             v                  v                  v
         KNOWLEDGE           AGENTS              TOOLS
             |                  |                  |
             |                  |                  v
             |                  |                 MCP
             |                  |                  |
             +------------------+------------------+
                                |
                         LLM MODEL LAYER
                                |
                    +-----------+-----------+
                    |           |           |
                    v           v           v
                  LLM A       LLM B    Private LLM
                                |
                                v
                           AI RESPONSE
                                |
                                v
                              NEXUS
                                |
                                v
                              USER
```

The architecture separates:

```text
Frontend
   ↓
API / Transport
   ↓
Application Layer
   ↓
AI Platform / SDK
   ↓
AI Capabilities
   ↓
Infrastructure / External Providers
```

AI capabilities remain separated into clear boundaries such as:

- Models
- Retrieval
- Agents
- Tools
- MCP
- Memory
- Workflows
- Artifacts
- Evaluation
- Observability

Infrastructure and vendor-specific implementations remain behind appropriate abstractions.

---

## 🔒 Security Architecture

Security is enforced by trusted NEXUS components rather than relying on frontend checks or model instructions.

```text
User
  |
  v
Authentication
  |
  v
Tenant Membership
  |
  v
Project Authorization
  |
  v
Agent Authorization
  |
  v
Tool / MCP Authorization
  |
  v
Input Validation
  |
  v
Policy Enforcement
  |
  v
Execution Boundary
  |
  v
External Service
  |
  v
Output Validation
  |
  v
Audit Logging
```

Important security boundaries include:

- Tenant isolation
- Project isolation
- Role-based access control
- Least privilege
- Default deny
- Server-side authorization
- Tool permission enforcement
- MCP permission enforcement
- Prompt-injection resistance
- Secret isolation
- Auditability
- Execution limits

---

## 🗄️ Data & Persistence

NEXUS uses PostgreSQL as the authoritative system of record.

```text
                         PostgreSQL
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
       Domains            pgvector          Metadata
          |
          +-- Users
          +-- Organizations
          +-- Workspaces
          +-- Projects
          +-- Conversations
          +-- Messages
          +-- Files
          +-- Documents
          +-- Knowledge Bases
          +-- Agents
          +-- Tools
          +-- MCP Servers
          +-- Workflows
          +-- Artifacts
          +-- Audit Events
          +-- Usage Records
```

Large binary objects are stored in Azure Blob Storage.

Redis is used for transient infrastructure such as:

- Caching
- Rate limiting
- Distributed locks
- Idempotency
- Job coordination
- Temporary execution state

Redis is not the source of truth.

Production secrets are managed through Azure Key Vault or an equivalent managed secret system.

---

## 👥 Who Can Use NEXUS?

NEXUS is a general-purpose platform.

| User | Example |
|---|---|
| Software Engineers | GitHub, code, testing, CI/CD, and developer workflows |
| Product Teams | Requirements, feedback, research, and project information |
| Sales Teams | CRM data, customer research, and reports |
| Marketing Teams | Content, campaigns, research, and analytics |
| Operations | Internal systems and repetitive workflows |
| Finance | Approved financial data and reporting |
| Researchers | Knowledge retrieval, comparison, and analysis |
| Companies | Private systems, internal tools, and custom MCP servers |

---

## 📊 Development Status

### Current Stage

**Week 1 Foundation Complete — Ready for First Real AI Feature**

### Completed

#### Product & Architecture

- Product vision
- Target users
- Primary use cases
- Product goals
- Non-goals
- V1 boundary
- Success criteria
- Capability matrix
- System requirements
- System architecture
- Architecture review
- Security baseline
- Data model
- API / SDK design
- Domain ownership model
- Engineering principles

#### Engineering Foundation

- Repository foundation
- Python 3.12+ backend foundation
- FastAPI application foundation
- Pydantic configuration
- Centralized logging foundation
- React + TypeScript frontend foundation
- Frontend routing
- Frontend API client foundation
- PostgreSQL local development service
- Redis local development service
- Docker Compose development environment
- Service health checks
- Persistent local volumes
- Backend unit tests
- Integration test foundation
- Ruff linting
- mypy type checking
- pre-commit hooks
- GitHub Actions CI
- Docker build validation

### Current Development Foundation

```text
React + TypeScript
        |
        v
     FastAPI
        |
        v
 Application Layer
        |
        v
 AI Platform / SDK
        |
        +----------------+
        |                |
        v                v
   PostgreSQL          Redis
        |
      pgvector
```

The development environment can run the core local services together through Docker Compose.

---

## 🗺️ Next

The project is now moving from architecture and foundation work into implementation of the first real AI capabilities.

The next development stage includes:

1. Authentication and identity foundation
2. Model/provider integration
3. Core AI conversation execution
4. Streaming AI responses
5. Knowledge and RAG foundation
6. Continued V1 capability implementation
7. Testing, evaluation, security hardening, and observability as capabilities are implemented

Detailed implementation sequencing is governed by the project plan, capability matrix, system requirements, architecture, API/SDK specification, data model, security requirements, and engineering principles.

---

## 📚 Documentation

Detailed technical and product documentation lives in the `docs/` directory.

| Document | Purpose |
|---|---|
| [`00-project-plan.md`](docs/00-project-plan.md) | Product definition, scope, goals, non-goals, V1 boundary, and success criteria |
| [`01-capability-matrix.md`](docs/01-capability-matrix.md) | Detailed NEXUS capabilities, feature breakdown, V1/V1.5/V2 classification, and usage |
| [`01-market-analysis.md`](docs/01-market-analysis.md) | UAE market, competitors, positioning, and differentiation |
| [`03-system-requirements.md`](docs/03-system-requirements.md) | Functional and non-functional system requirements |
| [`04-architecture.md`](docs/04-architecture.md) | Canonical system architecture and architectural boundaries |
| [`05-api-sdk.md`](docs/05-api-sdk.md) | Canonical API and Python SDK interfaces |
| [`06-data-model.md`](docs/06-data-model.md) | Canonical data model and persistence architecture |
| [`07-security.md`](docs/07-security.md) | Security requirements and security architecture |
| [`08-engineering-principles.md`](docs/08-engineering-principles.md) | Canonical engineering and implementation principles |
| [`domain-map.md`](docs/domain-map.md) | Domain ownership and documentation routing |

### AI Coding Agent Guidance

AI coding agents should begin with:

```text
AGENTS.md
    ↓
INVARIANTS.md
    ↓
docs/08-engineering-principles.md
    ↓
docs/domain-map.md
    ↓
Relevant domain documentation
```

Agents should load only the documentation relevant to the task and must preserve the documented architecture, contracts, security requirements, data boundaries, and invariants.

---

## 🌍 Product Principles

| Principle | Meaning |
|---|---|
| **User Control** | Users control their knowledge, tools, permissions, and AI usage |
| **Useful AI** | AI should help complete real work, not only answer questions |
| **Controlled Agents** | Agents operate within explicit permissions |
| **Open Architecture** | Avoid unnecessary dependence on one model or vendor |
| **Simple Experience** | Hide infrastructure complexity behind a simple interface |
| **Platform Thinking** | Support different users, teams, and industries |
| **Security by Default** | Security boundaries are enforced by trusted platform components |
| **Reliable AI** | AI operations should have explicit limits, failures, and observable outcomes |

---

## 💡 Why NEXUS?

Modern AI is moving from:

```text
"Ask AI a question"
```

toward:

```text
"Give AI a goal and let it help get the work done."
```

NEXUS is being built around that transition.

```text
Python
   |
   v
LLMs
   |
   v
RAG / Knowledge
   |
   v
Agentic AI
   |
   v
MCP / Tools
   |
   v
Security & Control
   |
   v
Cloud
   |
   v
NEXUS
```

NEXUS is designed to give users access to increasingly capable AI while keeping control over:

```text
Knowledge
    +
Models
    +
Tools
    +
Agents
    +
Permissions
    +
Data
    +
Execution
```

---

## 🚀 NEXUS

**AI that understands your context.**  
**AI that can use your tools.**  
**AI that can help do the work.**

**Status:** Early Development — Week 1 Foundation Complete
