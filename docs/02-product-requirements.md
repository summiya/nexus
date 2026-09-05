# Nexus — Product Requirements

**Status:** Draft
**Version:** 0.3
**Issue:** #26 (W1-04 — Write Product Requirements)
**Companion document:** `PROJECT_PLAN.md`
**Primary audience:** implementing agents

---

## Table of Contents

1. [How to use this document](#1-how-to-use-this-document)
2. [Purpose](#2-purpose)
3. [Definitions](#3-definitions)
4. [Users and roles](#4-users-and-roles)
5. [Conversations](#5-conversations)
6. [Model selection and switching](#6-model-selection-and-switching)
7. [File uploads](#7-file-uploads)
8. [Document Q&A](#8-document-qa)
9. [Citations](#9-citations)
10. [Agents](#10-agents)
11. [Tools](#11-tools)
12. [MCP connections](#12-mcp-connections)
13. [Artifacts](#13-artifacts)
14. [Cross-cutting requirements](#14-cross-cutting-requirements)
15. [Out of scope](#15-out-of-scope)
16. [Traceability](#16-traceability)
17. [Decisions](#17-decisions)

---

## 1. How to use this document

This section is binding. It applies to every agent that reads this document as part of building Nexus.

**1.1 — This document defines scope.** If a behaviour is not specified here, it is not in scope. Do not add capability because it seems obviously useful, because a comparable product has it, or because it would be easy. Unrequested work is a defect.

**1.2 — This document and the plan have different jobs.** `PROJECT_PLAN.md` describes *how* to build: stack, schema, module boundaries, build order. This document describes *what* to build: observable behaviour. Where the two appear to conflict on behaviour, this document is authoritative. Where they appear to conflict on structure, the plan is authoritative. Do not treat descriptive passages in the plan as requirements.

**1.3 — Priorities are ordered, not advisory.** Implement every P0 in a capability before any P1 in that capability. Do not implement P2 requirements. A P2 is recorded so the decision to defer is explicit; building one is out-of-scope work.

**1.4 — Acceptance criteria are the tests.** Each criterion is written to be checkable. A requirement is complete when every one of its criteria has either an automated test or a recorded manual verification. Partial satisfaction is not satisfaction.

**1.5 — Reference requirement IDs.** Use the ID in branch names, commit messages, PR descriptions, and test names. `CNV-03` is the unit of work, not "the stop button."

**1.6 — Numbers are requirements.** Where a criterion states a threshold, that threshold is the specification. Do not substitute your own judgement about what is fast enough or large enough.

**1.7 — Terms have exact meanings.** §3 defines the vocabulary. Do not substitute synonyms in code, API responses, or UI copy. `Turn` and `Message` are different things, and using them interchangeably will produce a confused data model.

**1.8 — Deferred decisions are binding constraints.** §17 records two decisions that have been deliberately postponed. Each states when it must be made and what must not be built before then. Those conditions are not advisory. A deferral stays cheap only if nothing is built that presumes an answer. If work requires a deferred decision, halt and request it from the Owner. Do not select a default, and do not implement both branches.

**1.9 — Report ambiguity.** If a requirement admits more than one reasonable implementation with materially different user-visible behaviour, that is a defect in this document. Raise it rather than resolving it silently.

---

## 2. Purpose

Nexus is a self-hosted AI workspace. This document specifies its user-facing behaviour across nine capabilities: conversations, model selection and switching, file uploads, document Q&A, citations, agents, tools, MCP connections, and artifacts.

The specification covers what a user can observe: what they see, what they can do, what the system guarantees. It does not specify implementation.

---

## 3. Definitions

These terms carry the meanings below throughout the document. They are not interchangeable with their everyday senses.

| Term | Meaning |
|---|---|
| **Workspace** | The top-level isolation boundary. All data belongs to exactly one workspace. Nothing crosses this boundary under any circumstance. |
| **Owner** | The role with administrative rights over a workspace. |
| **Member** | A role with usage rights but not administrative rights. |
| **Conversation** | An ordered sequence of turns between one user and the system. |
| **Turn** | One user submission and the complete system response to it. A turn may contain multiple tool calls and multiple content blocks. A turn is the unit of cancellation and the unit of cost accounting. |
| **Message** | One record within a turn, attributed to either the user or the assistant. |
| **Content block** | A typed unit within a message: text, reasoning, tool call, tool result, image, or document. A message contains an ordered list of content blocks, never a single string. |
| **Project** | A named container holding documents, custom instructions, and conversations. |
| **Document** | A file uploaded to a project and processed into searchable form. |
| **Chunk** | A retrievable segment of a document. |
| **Retrieval** | Selecting chunks relevant to a query and supplying them to the model. |
| **Citation** | A reference from a specific claim in a response to the source that supports it. |
| **Tool** | A named capability the model can invoke, with a declared input schema. |
| **Tool call** | One invocation of one tool within a turn. |
| **Agentic turn** | A turn in which the system executes two or more tool calls without further user input between them. |
| **MCP server** | An external process or endpoint providing tools over the Model Context Protocol. |
| **Artifact** | A substantial, self-contained piece of generated content displayed outside the conversation flow and versioned across turns. |
| **Artifact version** | One complete snapshot of an artifact's content, produced by one turn. |
| **Normal conditions** | Single active user; provider responding within its typical latency; no active rate limiting; warm database connection pool. All performance thresholds assume these conditions unless stated otherwise. |
| **Plain language** | User-facing text containing no stack trace, no internal identifier, no provider error payload, and no term requiring knowledge of the implementation to understand. |
| **Visible** | Rendered on screen without the user taking an action. |
| **Inspectable** | Reachable within one user action from where the relevant content is displayed. |
| **Persists** | Survives a full page reload and remains identical in content and order. |

**Priority levels**

| Level | Meaning |
|---|---|
| **P0** | Required. The capability is not complete until every P0 passes. |
| **P1** | Expected in v1. The capability is usable without it. May slip one phase with Owner approval. |
| **P2** | Deferred. Do not implement. Recorded so the deferral is a decision rather than an omission. |

---

## 4. Users and roles

Nexus launches as a small-team product. A workspace has one Owner and zero or more Members. There is no anonymous or public access tier, and no unauthenticated surface other than the sign-in page.

| Role | Rights |
|---|---|
| **Owner** | Everything a Member can do, plus: invite and remove Members, register and remove MCP servers, configure available models, view workspace-wide usage and cost. |
| **Member** | Create and use conversations, projects, documents, and artifacts within the workspace. View their own usage. |

Every requirement in this document is available to Members unless the requirement explicitly restricts it to the Owner.

**Primary jobs, in priority order:**

1. Hold a long, streaming, multi-turn conversation that persists and stays responsive.
2. Put a document or image in front of the model and ask about it.
3. Ask questions against a body of project documents and receive answers that cite their sources.
4. Have the model take multi-step action through tools without supervision at each step.
5. Generate substantial content as a versioned, re-editable artifact.
6. Extend capability through external MCP servers.

---

## 5. Conversations

**Non-goals for this capability:** real-time multi-user editing of a single conversation; public sharing; voice input or output; conversation templates.

### CNV-01 — Start and continue a conversation · P0

A user can start a conversation and exchange an unbounded number of turns.

- **Given** an authenticated user, **when** they submit a message in a new conversation, **then** an assistant reply is produced and both messages are visible in order.
- **Given** a conversation with prior turns, **when** the user sends another message, **then** the reply demonstrably reflects the content of earlier turns.
- **Given** any conversation, **when** the user reloads the page, **then** the full history persists, including message order, content block order, and formatting.

### CNV-02 — Responses stream · P0

Assistant output appears progressively as it is generated.

- **Given** a submitted message, **when** the model begins responding, **then** the first visible text appears within 2 seconds under normal conditions.
- **Given** a response in progress, **when** text is being generated, **then** no gap between successive visible updates exceeds 1 second, absent an upstream stall.
- **Given** a response in progress, **when** the user scrolls up, **then** the scroll position is retained and does not return to the bottom until the user scrolls back down.
- **Given** a completed response, **when** it is rendered, **then** the result is byte-identical to a non-streamed render of the same content.

### CNV-03 — Stop a response in progress · P0

- **Given** a streaming response, **when** the user activates Stop, **then** visible generation ceases within 1 second.
- **Given** a stopped response, **when** the conversation is reloaded, **then** the partial content persists and is visibly marked incomplete.
- **Given** a stopped response, **when** the user sends a follow-up, **then** the conversation continues normally from that partial turn.
- **Given** a streaming response, **when** the user closes the browser tab, **then** generation stops server-side within 5 seconds rather than running to completion.

The final criterion is a cost requirement. A turn that continues generating after its audience has left is billed and discarded.

### CNV-04 — Reasoning is visible and separable · P0

- **Given** a conversation with extended thinking enabled, **when** the model produces reasoning, **then** it renders in a visually distinct, collapsible region positioned before the answer.
- **Given** a reasoning region, **when** the user collapses it, **then** the collapsed state applies to subsequent turns in that conversation and persists.
- **Given** a completed turn containing reasoning, **when** the conversation is reloaded, **then** the reasoning persists and remains distinguishable from the answer.

### CNV-05 — Conversations are listed and identifiable · P0

- **Given** a user with multiple conversations, **when** they open the workspace, **then** conversations are listed in descending order of last activity, each showing a title and a timestamp.
- **Given** a new conversation, **when** its first turn completes, **then** it has a title derived from that turn's content rather than a placeholder.
- **Given** any conversation, **when** the user edits its title, **then** the change persists and appears in the list.

### CNV-06 — Conversations can be archived and deleted · P1

- **Given** a conversation, **when** the user archives it, **then** it is removed from the default list and remains reachable under an archived filter.
- **Given** a conversation, **when** the user requests deletion, **then** confirmation is required, and on confirmation the conversation and all its messages become unretrievable through any API path.

### CNV-07 — Long conversations continue to function · P0

- **Given** a conversation whose accumulated history exceeds the selected model's context window, **when** the user sends a message, **then** a coherent reply is produced and no error is shown.
- **Given** such a conversation, **when** the reply is produced, **then** the user is informed that earlier context has been condensed.
- **Given** such a conversation, **when** the user scrolls back, **then** the complete original history remains readable in the interface.

The last criterion establishes that displayed history and transmitted context are distinct. The user's record is never truncated, only what is sent to the model.

### CNV-08 — Errors are legible and recoverable · P0

- **Given** a provider rate limit, **when** it occurs, **then** the user is shown that the system is waiting and retrying, expressed in plain language.
- **Given** an error that cannot be retried, **when** it occurs, **then** the user is shown a plain-language explanation and their submitted text is preserved and resubmittable.
- **Given** any error, **when** it is displayed, **then** it satisfies the definition of plain language in §3.

### CNV-09 — Branch from an earlier turn · P2

Editing an earlier message forks the conversation rather than overwriting it. Do not implement. The data model reserves `messages.parent_id` for this.

---

## 6. Model selection and switching

**Non-goals:** custom model hosting; fine-tuning; automatic model routing based on query content.

### MDL-01 — Choose a model per conversation · P0

- **Given** a conversation, **when** the user opens the model picker, **then** every configured model is listed with its name and context window size.
- **Given** a selected model, **when** the user sends a message, **then** that model produces the reply.
- **Given** a conversation, **when** it is reloaded, **then** the selected model persists.

### MDL-02 — Switch models mid-conversation · P0

- **Given** a conversation with existing history, **when** the user switches models and sends a message, **then** the new model receives the prior history and produces a coherent reply.
- **Given** a conversation where models were switched, **when** the user views any assistant message, **then** the model that produced it is inspectable.

### MDL-03 — Capabilities gate the interface · P1

The interface must not offer what the selected model cannot do.

- **Given** a model without vision support, **when** it is selected, **then** image attachment is disabled and the reason is visible.
- **Given** a model without extended thinking, **when** it is selected, **then** the thinking budget control is not rendered.
- **Given** a model with a smaller context window, **when** it is selected, **then** any context usage indicator reflects that model's limit.

### MDL-04 — Per-conversation generation settings · P1

- **Given** a conversation, **when** the user adjusts temperature or thinking budget, **then** the change applies to subsequent turns in that conversation only and does not affect other conversations.
- **Given** adjusted settings, **when** the conversation is reloaded, **then** the settings persist.

### MDL-05 — Cost is visible · P1

- **Given** a completed turn, **when** the user inspects it, **then** input tokens, output tokens, cache read tokens, cache write tokens, and estimated cost for that turn are shown.
- **Given** a conversation, **when** the user views its details, **then** cumulative token usage and estimated cost are shown.
- **Given** the Owner, **when** they view workspace usage, **then** totals are available grouped by conversation, by project, and by day.

---

## 7. File uploads

Distinct from Document Q&A: uploads attach a file to a single message. Documents in a project are processed into durable, searchable knowledge. See §8.

**Non-goals:** file editing; file versioning; a general-purpose file manager; video or audio processing.

### UPL-01 — Attach files to a message · P0

- **Given** the message composer, **when** the user drags a file onto it, pastes a file, or selects one through a file picker, **then** the file attaches and its name, size, and type are visible.
- **Given** an attached file, **when** the user removes it before sending, **then** it is discarded and not transmitted.
- **Given** an upload in progress, **when** the user observes it, **then** progress is visible and the send action is disabled until the upload completes.

### UPL-02 — Images are processed · P0

- **Given** an attached PNG, JPEG, GIF, or WebP image, **when** the user asks a question about it, **then** the reply demonstrates the image content was processed.
- **Given** an image exceeding provider size limits, **when** it is attached, **then** it is resized automatically and processed successfully without user action.
- **Given** a conversation containing an image, **when** it is reloaded, **then** the image persists and renders inline.

### UPL-03 — PDFs are processed · P0

- **Given** an attached PDF, **when** the user asks about its contents, **then** the reply reflects text drawn from the document.
- **Given** a multi-page PDF, **when** the user asks about a specific page, **then** the reply is accurate for that page.
- **Given** a PDF that cannot be processed, **when** it is attached, **then** the reason is shown in plain language and the message is not sent without it silently.

### UPL-04 — Text and code files are processed · P0

- **Given** an attached `.txt`, `.md`, `.csv`, or recognised source file, **when** the user asks about it, **then** its contents are available to the model with the original filename preserved.
- **Given** a code file, **when** it appears in conversation history, **then** it renders with syntax highlighting matching its type.

### UPL-05 — Uploads are validated · P0

- **Given** a file above the configured size limit, **when** the user attaches it, **then** it is rejected before upload begins and the limit is stated.
- **Given** a file whose actual content type does not match its extension, **when** it is uploaded, **then** it is rejected.
- **Given** a file type not on the allowlist, **when** the user attaches it, **then** it is rejected and the accepted types are listed.

### UPL-06 — Multiple attachments per message · P1

- **Given** the composer, **when** the user attaches several files, **then** all are transmitted with the message and all are available to the model.
- **Given** the configured per-message attachment limit, **when** the user exceeds it, **then** further attachments are refused and the limit is stated.

---

## 8. Document Q&A

**Non-goals:** document editing; collaborative annotation; OCR of handwriting; automatic document classification or tagging.

### DOC-01 — Projects hold documents · P0

- **Given** an authenticated user, **when** they create a project with a name and description, **then** it appears in the project list.
- **Given** a project, **when** the user uploads documents to it, **then** those documents are listed with their processing status.
- **Given** a project, **when** the user starts a conversation within it, **then** the conversation is associated with the project and listed under it.

### DOC-02 — Project instructions apply throughout the project · P0

- **Given** a project with custom instructions, **when** a user converses within it, **then** the model's behaviour reflects those instructions.
- **Given** edited instructions, **when** the next message is sent, **then** the change takes effect without requiring a new conversation.

### DOC-03 — Ingestion is transparent · P0

- **Given** an uploaded document, **when** processing begins, **then** its status is visible and updates through to completion or failure.
- **Given** a document that fails processing, **when** the user views it, **then** the failure reason is stated in plain language and a retry action is available.
- **Given** a document still processing, **when** the user asks a question in that project, **then** they are told that document is not yet searchable.

The final criterion is not optional. A system that answers from partial knowledge without saying so is worse than one that refuses.

### DOC-04 — Answers are grounded in project documents · P0

- **Given** a project with processed documents, **when** the user asks a question answerable from them, **then** the reply draws on the relevant document content.
- **Given** a question not answerable from the project's documents, **when** the user asks it, **then** the model states that it cannot answer from the available documents rather than producing an unsupported answer.
- **Given** a question containing an exact term, identifier, product name, or proper noun, **when** the user asks it, **then** the document containing that exact term is retrieved even when it is not the nearest semantic match.

The third criterion is why lexical and semantic search are both required at baseline. Semantic search alone reliably fails on identifiers.

### DOC-05 — Retrieval quality is measured · P0

- **Given** a fixed evaluation set of at least 20 questions with known correct source documents, **when** the evaluation is run, **then** recall@5 is at or above 0.8.
- **Given** any change to chunking, embedding, or retrieval logic, **when** it is submitted for review, **then** the evaluation has been run and its result recorded in the submission.

### DOC-06 — Retrieved context is inspectable · P1

- **Given** a grounded answer, **when** the user opens the context inspector, **then** the exact chunks supplied to the model are shown.
- **Given** an incorrect answer, **when** the user inspects the retrieved context, **then** they can determine whether the failure occurred in retrieval or in generation.

### DOC-07 — Documents can be removed and re-indexed · P1

- **Given** a document in a project, **when** the user deletes it, **then** it no longer appears in retrieval results for subsequent questions.
- **Given** a document that has been updated, **when** the user re-uploads it, **then** content from the previous version no longer appears in retrieval results.

Deletion semantics depend on decision **D-05** in §17, which is deferred. Do not implement this requirement before that decision is made.

---

## 9. Citations

**Non-goals:** citation formatting styles; bibliography generation; export to reference managers.

### CIT-01 — Grounded claims carry sources · P0

- **Given** an answer drawn from project documents, **when** it is displayed, **then** each claim sourced from a document carries a visible citation marker.
- **Given** an answer produced without supporting documents, **when** it is displayed, **then** no citation markers appear.

### CIT-02 — Citations resolve to a location · P0

- **Given** a citation marker, **when** the user activates it, **then** the source document opens at the cited passage.
- **Given** a cited PDF, **when** the source opens, **then** the page number is visible.
- **Given** a cited passage, **when** it is displayed, **then** the specific supporting span is highlighted within surrounding context.

### CIT-03 — Citations survive persistence · P0

- **Given** a conversation containing citations, **when** it is reloaded, **then** every citation still resolves correctly.
- **Given** a citation whose source document has been deleted, **when** the user activates it, **then** they are told the source is unavailable, in plain language, with no error state.

### CIT-04 — Sources are listed per answer · P1

- **Given** an answer citing multiple documents, **when** the user views it, **then** a consolidated list of distinct sources for that answer is inspectable.

### CIT-05 — Web search results are cited · P1

- **Given** an answer informed by a web search tool call, **when** it is displayed, **then** the source URLs are visible and followable.

---

## 10. Agents

**Scope, per decision D-03 in §17.** "Agents" means the bounded agentic turn: the system executing a multi-step sequence of tool calls within a single turn, observable and interruptible. There is no user-facing agent object. Nothing in this capability is named, saved, configured, or reused. An agentic turn begins when the user sends a message and ends when that turn ends.

**Non-goals:** user-defined or named agents; persistent agent configurations; per-agent instructions, tool permissions, or document scope; agent-to-agent delegation; scheduled or background autonomous execution; any agent state that outlives a single turn. These are excluded by decision, not by omission. See §15.

### AGT-01 — Multi-step execution within one turn · P0

- **Given** a request requiring several dependent steps, **when** the user submits it, **then** the system executes those steps and returns one coherent answer without further user input.
- **Given** an agentic turn in progress, **when** the user observes it, **then** each step is visible as it occurs, identified by name and status.

### AGT-02 — Execution is bounded · P0

A user request must never be able to initiate unbounded execution.

- **Given** a turn that reaches the maximum step count, **when** the limit is reached, **then** execution halts, the user is told the limit was reached, and any partial result is shown.
- **Given** a turn that exceeds its wall-clock budget, **when** the budget is exhausted, **then** execution halts with a plain-language explanation.
- **Given** any bounded halt, **when** it occurs, **then** the user can send a follow-up message that continues from the halted state.

### AGT-03 — Execution is interruptible · P0

- **Given** an agentic turn in progress, **when** the user activates Stop, **then** no further steps begin, in-flight steps are abandoned, and the partial result persists.

### AGT-04 — Failed steps do not terminate the turn · P0

- **Given** a step that returns an error, **when** the failure occurs, **then** the error is returned to the model, which may recover or take an alternative path.
- **Given** a turn that recovered from a failed step, **when** the user views it, **then** both the failure and the recovery are inspectable.
- **Given** a failure the model cannot recover from, **when** the turn ends, **then** the user is told in plain language what failed.

### AGT-05 — Independent steps execute concurrently · P1

- **Given** a turn requiring several independent operations, **when** they are executed, **then** they run concurrently rather than sequentially.
- **Given** concurrent steps where one fails, **when** results are collected, **then** the successful results are still used.

### AGT-06 — The execution trace is reviewable · P1

- **Given** a completed agentic turn, **when** the conversation is reloaded, **then** the full sequence of steps, their inputs, and their outcomes persist and remain inspectable.

---

## 11. Tools

**Non-goals:** user-authored tools; a tool marketplace; tools that modify Nexus's own configuration.

### TOL-01 — Tool activity is visible · P0

- **Given** a tool call, **when** it begins, **then** a card appears naming the tool and showing a running status.
- **Given** a completed tool call, **when** the user views the card, **then** the input and result are inspectable, collapsed by default.
- **Given** a failed tool call, **when** the user views the card, **then** the error is shown in plain language.

### TOL-02 — Web search · P0

- **Given** a question requiring current information, **when** the user submits it, **then** the model performs a web search and the answer reflects the results.
- **Given** a web-search-informed answer, **when** it is displayed, **then** its sources are visible, satisfying CIT-05.

### TOL-03 — Code execution · P1

- **Given** a request requiring computation, **when** the user submits it, **then** code is executed and the result incorporated into the answer.
- **Given** a code execution, **when** the user inspects the tool card, **then** both the executed code and its output are visible.

### TOL-04 — Tools can be enabled and disabled · P0

- **Given** a conversation, **when** the user disables a tool, **then** it is not offered to the model for subsequent turns in that conversation.
- **Given** every tool disabled, **when** the user converses, **then** the model responds without tool use and no error occurs.

### TOL-05 — Tool calls cannot hang a turn · P0

- **Given** a tool that does not respond, **when** its timeout elapses, **then** the call is abandoned, the model is informed, and the turn proceeds.
- **Given** a slow tool call, **when** it is running, **then** elapsed time is visible.

### TOL-06 — Tool activity is auditable · P1

- **Given** any tool call, **when** the Owner reviews history, **then** the tool name, input, output, status, and duration persist and are retrievable.

---

## 12. MCP connections

**Scope constraint.** v1 supports Owner-registered servers only. User-supplied servers are out of scope (§15). Do not build registration paths that accept arbitrary user-supplied server configuration, even as a convenience.

**Non-goals:** an MCP server directory or marketplace; automatic server discovery; Nexus acting as an MCP server.

### MCP-01 — Register a server · P0

- **Given** an Owner, **when** they register a server with its transport and configuration, **then** it appears in the workspace's server list with a connection status.
- **Given** an invalid configuration, **when** it is submitted, **then** it is rejected with a specific, actionable reason.
- **Given** a registered server, **when** any user views it through any path, **then** its credentials are never displayed, in whole or in part, in any form.

### MCP-02 — Discover tools · P0

- **Given** a connected server, **when** discovery runs, **then** its tools are listed with names and descriptions.
- **Given** a server whose tool set has changed, **when** the Owner re-runs discovery, **then** the listed tools update to match.

### MCP-03 — MCP tools behave as built-in tools · P0

- **Given** a discovered MCP tool, **when** the model calls it, **then** the user-visible behaviour is identical to a built-in tool call: same card, same status states, same result display.
- **Given** an MCP tool card, **when** the user inspects it, **then** the originating server is identified.

### MCP-04 — Failure is graceful and contained · P0

- **Given** an unreachable server, **when** a turn begins, **then** its tools are excluded and the turn proceeds with the remaining tools.
- **Given** a turn where a server was excluded, **when** it completes, **then** the user is told which capability was unavailable.
- **Given** a server whose failures exceed the configured threshold, **when** the threshold is crossed, **then** the server is circuit-broken and the Owner is notified.
- **Given** a circuit-broken server that recovers, **when** recovery is detected, **then** it returns to service without Owner action.

### MCP-05 — Connection health is visible · P0

- **Given** the server list, **when** the Owner views it, **then** each server shows its current status and the time of its last successful health check.
- **Given** a failing server, **when** the Owner inspects it, **then** diagnostic detail sufficient to identify the cause is available.

### MCP-06 — Sensitive tools require approval · P1

- **Given** a tool configured to require approval, **when** the model calls it, **then** execution pauses and the tool name and inputs are shown before the user approves or denies.
- **Given** a denied call, **when** denial occurs, **then** the model is informed and the turn continues without that result.
- **Given** an approval prompt that goes unanswered past its timeout, **when** the timeout elapses, **then** it is treated as a denial.

### MCP-07 — Servers are workspace-scoped · P0

- **Given** a server registered in one workspace, **when** a user in another workspace converses, **then** its tools are neither offered to the model nor callable through any path.

---

## 13. Artifacts

An artifact is substantial generated content displayed outside the conversation flow and versioned across turns. The defining behaviour is that a follow-up request modifies the existing artifact rather than producing a new one.

**Non-goals:** collaborative real-time editing; public sharing or publishing; artifact-to-artifact imports; a hosted runtime for generated applications; user-uploaded artifacts.

### ART-01 — Artifacts are created and displayed separately · P0

- **Given** a request producing substantial self-contained content, **when** the model responds, **then** the content is displayed in a dedicated panel rather than inline in the conversation.
- **Given** a created artifact, **when** it is displayed, **then** it shows a title and a type.
- **Given** a conversation containing an artifact, **when** it is reloaded, **then** the artifact persists and remains openable from the turn that produced it.

### ART-02 — Artifacts render as they generate · P0

- **Given** an artifact being generated, **when** content streams, **then** it appears progressively in the panel rather than only on completion.
- **Given** a partially generated artifact, **when** the user views it, **then** the incomplete state is evident and the artifact is not presented as finished.

### ART-03 — Each type renders correctly · P0

- **Given** a Markdown artifact, **when** it is displayed, **then** it renders as formatted text.
- **Given** a code artifact, **when** it is displayed, **then** it renders with syntax highlighting matching its declared language.
- **Given** an SVG artifact, **when** it is displayed, **then** it renders as an image.
- **Given** a Mermaid artifact, **when** it is displayed, **then** it renders as a diagram.
- **Given** an HTML artifact, **when** it is displayed, **then** it renders as a live page subject to ART-06.
- **Given** an artifact whose content is invalid for its declared type, **when** rendering fails, **then** the failure is contained to the artifact panel, the raw content remains viewable, and the conversation continues to function.

### ART-04 — Refinement updates in place · P0

This is the requirement that distinguishes an artifact from a formatted code block. It is the highest-risk requirement in this section.

- **Given** a displayed artifact, **when** the user requests a modification in a following turn, **then** the existing artifact is updated and a new version is created.
- **Given** such a modification, **when** it completes, **then** no duplicate artifact has been created.
- **Given** three consecutive modification turns, **when** they complete, **then** the artifact has four versions and the panel shows the latest.

### ART-05 — Version history is available · P1

- **Given** an artifact with multiple versions, **when** the user opens its history, **then** every version is listed with its sequence number and the time it was created.
- **Given** a listed version, **when** the user selects it, **then** its full content is displayed.
- **Given** a previous version, **when** the user restores it, **then** the restored content becomes a new version rather than deleting the intervening ones.

### ART-06 — Executable artifacts are isolated · P0

**This is a security requirement. Every criterion must pass before any HTML or script-executing artifact type is enabled in any environment, including local development.**

- **Given** an HTML artifact, **when** it is rendered, **then** it is served from an origin distinct from the application origin.
- **Given** the rendering frame, **when** its attributes are inspected, **then** it carries `sandbox="allow-scripts"` and does **not** carry `allow-same-origin`.
- **Given** an artifact containing script that attempts to read application cookies, session storage, or local storage, **when** it executes, **then** the attempt fails.
- **Given** an artifact containing script that attempts to read or modify the parent document, **when** it executes, **then** the attempt fails.
- **Given** an artifact containing script that attempts a network request to an origin not permitted by the frame's content security policy, **when** it executes, **then** the request is blocked.
- **Given** a deliberate attempt to exfiltrate a session token from inside an artifact, **when** it is performed as a manual verification, **then** it fails, and the result is recorded.

`sandbox="allow-scripts allow-same-origin"` on the application's own origin provides no isolation. If both attributes appear together, this requirement has failed regardless of other controls.

### ART-07 — Artifacts are usable outside Nexus · P1

- **Given** a displayed artifact, **when** the user copies it, **then** the complete current version content is placed on the clipboard.
- **Given** a displayed artifact, **when** the user downloads it, **then** a file is produced with an extension matching the artifact type.

### ART-08 — Artifacts are findable · P1

- **Given** a workspace containing artifacts, **when** the user opens the artifact library, **then** all artifacts are listed with title, type, and last modified time.
- **Given** the library, **when** the user filters by conversation or by project, **then** only matching artifacts are listed.

---

## 14. Cross-cutting requirements

These apply to every capability. They are not owned by any single phase.

### XC-01 — Performance · P0

Under normal conditions as defined in §3:

- Time to first streamed token: under 2 seconds at p95.
- Conversation history load for a 100-message conversation: under 1 second at p95.
- Retrieval for a project of 10,000 chunks: under 500ms at p95.
- A 500-message conversation scrolls at a sustained 50 frames per second or better.

### XC-02 — Workspace isolation · P0

- **Given** a user in one workspace, **when** they attempt to access any resource belonging to another workspace by direct identifier reference, **then** access is refused.
- This applies without exception to conversations, messages, projects, documents, chunks, artifacts, artifact versions, tool call records, MCP servers, and usage records.
- **Given** any query against workspace-scoped data, **when** it executes, **then** the workspace constraint is enforced structurally rather than by the correctness of each call site.

### XC-03 — Data handling · P0

- **Given** any log output, **when** it is inspected, **then** it contains no credential, API key, or document content.
- **Given** any API response, **when** it is inspected, **then** it contains no stored credential in any form.
- **Given** a deleted document, **when** deletion completes, **then** derived data is removed according to the retention policy established by decision **D-05** in §17. This criterion is not implementable before that decision is made.

### XC-04 — Membership · P0

- **Given** the Owner, **when** they invite a user by email, **then** that user can join the workspace as a Member.
- **Given** the Owner, **when** they remove a Member, **then** that user immediately loses access to all workspace resources.
- **Given** a Member, **when** they attempt an Owner-restricted action, **then** it is refused.

### XC-05 — Session and authentication · P0

- **Given** an expired session, **when** the user takes an action, **then** they are returned to sign-in and, on success, to their prior location.
- **Given** a session that expires during a streaming turn, **when** expiry occurs, **then** the in-flight turn completes rather than being dropped.

### XC-06 — Accessibility · P1

- Every interactive element is reachable and operable by keyboard.
- Streaming responses are announced through an assistive-technology live region without re-reading the full response on each update.
- No status is conveyed by colour alone.
- Text meets WCAG AA contrast against its background in both light and dark themes.

---

## 15. Out of scope

Recorded so that each omission is a decision. Do not implement anything in this table.

| Excluded | Reason |
|---|---|
| User-defined or persistent agents | Excluded by decision D-03. "Agents" means the bounded agentic turn only (§10). |
| User-supplied MCP servers | Security surface and effort disproportionate to value at this stage. |
| Conversation branching | Reserved in the data model; deferred (CNV-09). |
| Real-time collaboration within a conversation or artifact | One editor per resource is sufficient for a small team. |
| Public sharing or publishing of conversations and artifacts | No anonymous access tier exists. |
| Mobile-native applications | Responsive web only. |
| Voice input or output | Not required by #26. |
| Fine-tuning or self-hosted model weights | Provider models only. |
| Multi-provider model support | The provider abstraction permits it; a second provider is not a v1 requirement. |
| A hosted runtime for generated applications | Artifacts render in a sandbox; they are not deployed. |

---

## 16. Traceability

Ordered by build sequence. Each capability maps to a phase in `PROJECT_PLAN.md` §9.

| Phase | Capability | Requirements |
|---|---|---|
| 1 | Conversations | CNV-01 … CNV-09 |
| 1 | Model selection and switching | MDL-01 … MDL-05 |
| 2 | File uploads | UPL-01 … UPL-06 |
| 3 | Tools | TOL-01 … TOL-06 |
| 3 | Agents | AGT-01 … AGT-06 |
| 4 | Artifacts | ART-01 … ART-08 |
| 5 | Document Q&A | DOC-01 … DOC-07 |
| 5 | Citations | CIT-01 … CIT-05 |
| 6 | MCP connections | MCP-01 … MCP-07 |
| 1–8 | Cross-cutting | XC-01 … XC-06 |

A phase is not complete until every P0 requirement mapped to it passes every one of its acceptance criteria.

---

## 17. Decisions

There are no open questions in this document. Every scope question raised during drafting has either been settled or deliberately deferred with a stated deadline and a stated constraint.

### Settled

| ID | Decision | Resolution | Consequence |
|---|---|---|---|
| **D-01** | Are artifacts in scope? | Yes. | Specified in §13 as the ninth capability. Phase 4 proceeds as planned in `PROJECT_PLAN.md`. |
| **D-02** | Single user or small team at launch? | Small team. | The Owner/Member split (§4), membership (XC-04), and workspace isolation (XC-02) are all P0 for v1. Isolation is not deferrable; retrofitting it is substantially harder than building it in. |
| **D-03** | What does "Agents" mean? | The bounded agentic turn only. | §10 stands as written. There is no agent object, no agent configuration, and no agent persistence. Phase 3 keeps its existing three-week budget. User-defined agents are listed in §15 as out of scope and must not be built. |

### Deferred

Both deferrals carry a condition. The conditions are binding, per §1.8. A deferral only stays cheap if nothing is built that presumes an answer.

**D-04 — Which embedding model? · Decide before Phase 5 begins.**

DOC-05 sets a recall target that cannot be evaluated without a chosen model, so the choice must be made at the start of Phase 5.

*Condition:* **No table storing embeddings may be created before Phase 5.** The chosen model fixes the vector dimension, and changing that dimension after chunks exist requires re-embedding every chunk in every project. Any agent working in Phases 0 through 4 that finds itself about to define an embedding column has exceeded its scope and must halt.

**D-05 — What is the retention policy for derived data and tool records? · Decide before DOC-07 is implemented.**

Two parts. First: when a user deletes a document, is the derived data — extracted text, chunks, embeddings — deleted immediately, deleted on a schedule, or retained? Second: how long are tool call records kept, given that their inputs and outputs can contain document content and would otherwise outlive the document they were drawn from?

*Condition:* **No deletion path may ship before the policy is set.** A delete action that silently leaves derived content in place is worse than no delete action at all, because it makes a promise the system does not keep and the discrepancy is invisible until someone goes looking. Until the policy exists, DOC-07 and the third criterion of XC-03 remain unimplemented rather than partially implemented.

---

*Version 0.3. Changes from 0.2: resolved the Agents scope question as the bounded agentic turn (D-03) and removed the implementation hold on §10; added user-defined agents to §15 as an explicit exclusion; replaced the open questions section with §17 Decisions, recording three settled decisions and two deferrals with binding conditions; updated §1.8 to govern deferred decisions rather than open questions.*

*Requirements are frozen once their phase begins. Changes after that point are raised as new issues, not edits to this document.*
