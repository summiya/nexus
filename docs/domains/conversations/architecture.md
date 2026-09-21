# Conversation Architecture

**Status:** Authoritative implemented Conversation architecture

## Purpose

This document describes the implementation boundaries that currently own Conversation creation and message streaming. Global architectural rules remain in `docs/04-architecture.md`; the public HTTP and LLM contracts remain in `docs/05-api-sdk.md`.

## Implemented structure

```text
backend/src/nexus/conversations/
├── api/          # FastAPI transport, schemas, and dependency wiring
├── application/  # Conversation use cases and stream lifecycle
├── domain/       # Provider- and persistence-independent records
└── ports/        # Application-facing persistence contract

backend/src/nexus/infrastructure/persistence/conversation.py
    # SQLAlchemy ConversationPersistence implementation

backend/src/nexus/llm/
├── domain/       # Provider-independent LLM requests, responses, and events
├── ports/        # LLMGateway
└── infrastructure/adapters/litellm/
    # LiteLLM provider adapter

backend/src/nexus/composition/root.py
    # Concrete object construction
```

The streaming dependency flow is:

```text
Conversation HTTP controller
        ↓
StreamConversationMessage
        ├── ConversationPersistence
        │       ↓
        │   SqlAlchemyConversationPersistence
        │
        └── LLMGateway
                ↓
            LiteLLMAdapter

Internal streaming:

StreamConversationMessage
        ↓
ConversationStreamLifecycle
        ↓
ConversationEventAssembler
```

Dependencies point inward toward application and domain contracts. Conversation application code depends on `ConversationPersistence` and `LLMGateway`, never on FastAPI, SQLAlchemy, LiteLLM, or their concrete adapters. The composition root supplies those implementations.

## Responsibilities

### Conversation HTTP controller

The API boundary owns transport and schema validation through its Pydantic request schemas. The controller owns HTTP request/response mapping, authenticated context extraction, FastAPI dependency resolution, and Conversation-event-to-SSE serialization. It passes validated schema values to application code and always closes the prepared normalized stream.

### `StreamConversationMessage`

This use case owns use-case validation, model-policy enforcement, Conversation authorization, and streaming orchestration. It creates the user Message and `RUNNING` Generation records, prepares bounded history, builds the provider-independent `LLMRequest`, and invokes `LLMGateway.stream()` directly. After receiving the normalized iterator, it transfers lifecycle ownership to `ConversationStreamLifecycle`.

### `ConversationPersistence`

This is the single application-facing persistence boundary for Conversation, Message, and Generation operations. Its methods use domain records and public UUIDs. Terminal methods report whether they authoritatively changed `RUNNING` to a terminal state.

### `SqlAlchemyConversationPersistence`

This adapter translates between domain records and SQLAlchemy models. Each operation owns a short-lived session, runs blocking database work in a worker thread, and commits or rolls back its transaction before returning. If an awaiting task is cancelled, it waits for the worker transaction to settle before propagating cancellation.

### `LLMGateway`

This provider-independent port accepts `LLMRequest` and exposes either a normalized `LLMResponse` or `AsyncIterator[LLMEvent]`. Application code sees only Nexus LLM contracts.

### `LiteLLMAdapter`

This adapter maps Nexus requests to LiteLLM and converts raw provider responses, chunks, errors, usage, tool calls, and completion signals into Nexus LLM contracts. It exclusively owns and closes the raw provider iterator exactly once.

### `ConversationStreamLifecycle`

The lifecycle component owns the normalized `AsyncIterator[LLMEvent]` after it is handed over by `StreamConversationMessage`. It preflights the first event, drives iteration, resolves completion/failure/cancellation, delegates event assembly, persists terminal state, and closes the normalized iterator exactly once.

### `ConversationEventAssembler`

The assembler converts normalized LLM events into Conversation events and accumulates the assistant text, usage, and finish reason needed for a valid completion. It rejects incomplete, empty, error, and unsupported tool-call streams. It performs no I/O and owns no transaction or iterator.

## Provider boundary and iterator ownership

Raw provider objects never cross the LiteLLM adapter. The ownership chain is explicit:

```text
LiteLLMAdapter
    owns raw provider iterator
        ↓ normalized LLMEvent stream
ConversationStreamLifecycle
    owns normalized iterator
        ↓ ConversationEvent stream
Conversation HTTP controller
    owns HTTP/SSE consumption and closes the prepared lifecycle
```

Each owner closes only its own iterator and makes repeated close requests idempotent. A cleanup failure is logged and must not leave the Generation `RUNNING` or cause a second close attempt.

## Persistence and transaction boundaries

Initial persistence is committed before external streaming begins:

```text
authorize Conversation
    ↓
transaction: persist user Message + RUNNING Generation and read history
    ↓ commit and close database session
build LLMRequest
    ↓
start and await external LLM stream
```

No SQLAlchemy session or database transaction remains open while Nexus waits for provider events.

PostgreSQL enforces at most one `RUNNING` Generation per Conversation with
the explicitly named partial unique index
`uq_generations_one_running_per_conversation`. A competing preparation rolls
back both its user Message and Generation before the provider is invoked and
is returned as a safe conflict. Only a violation of this known index is
translated to the active-generation conflict; unrelated integrity failures
remain persistence failures.

The message endpoint also supports optional at-most-once submission through a
UUID `Idempotency-Key`. The key is persisted with the Generation and protected
by `uq_generations_conversation_idempotency_key`. A repeated key for the same
Conversation returns a conflict without another Message, Generation, or
provider call, including after the original Generation is terminal. This is
request deduplication, not SSE replay or resumption. Because the key is scoped
by organization and Conversation, the same key may be used for a different
Conversation.

Terminal persistence uses a separate short transaction:

- completion atomically inserts the assistant Message and changes the Generation to `COMPLETED`;
- failure changes the Generation to `FAILED` without an assistant Message;
- cancellation changes the Generation to `CANCELLED` without an assistant Message.

If a completion transaction fails, its assistant insert is rolled back. The lifecycle then attempts the safe `persistence_failure` terminal path; it never reports a successful completion for a failed database transition.

## Terminal-state rules

`ConversationStreamLifecycle` owns terminal intent, while the database transition result is authoritative. Terminal persistence locks the Generation and changes it only while its stored status is `RUNNING`. Therefore:

- the first committed `COMPLETED`, `FAILED`, or `CANCELLED` transition wins;
- later transitions return `False` and cannot overwrite the winner;
- the application emits a terminal outcome only when its corresponding database transition succeeds;
- an assistant Message exists only when `COMPLETED` wins;
- early close and request cancellation resolve to `CANCELLED`;
- provider errors, incomplete EOF, invalid event sequences, and processing failures resolve to `FAILED` with stable error kinds;
- a real provider completion event and non-empty assistant content are required before completion.

## Tenant and authorization boundaries

Organization and user identities come from authenticated server context, not the request body. Application authorization currently permits a standalone Conversation only for its creating user and rejects workspace-scoped streaming until workspace authorization is implemented.

Persistence operations scope Conversation, Message, and Generation references by organization and Conversation. Public UUIDs cross application boundaries; internal integer database identifiers remain inside SQLAlchemy infrastructure. Cross-tenant and same-tenant cross-Conversation references are rejected without persisting partial state.

## Safe error boundaries

Provider-specific exceptions and payloads do not escape the LLM adapter. Failures before SSE establishment are translated into safe HTTP errors. Failures after streaming starts use `generation.error` with a stable kind and the client-safe message `The generation could not be completed.` Unexpected internal exceptions are logged with their underlying exception but are represented to clients as `stream_processing_failure`.

Cancellation remains cancellation and is never classified as a processing failure. If terminal persistence loses a race, the lifecycle does not emit or claim the losing terminal outcome.
