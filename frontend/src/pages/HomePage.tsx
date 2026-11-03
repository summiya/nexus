import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";

import { NexusCapabilityExplorer } from "../features/marketing/NexusCapabilityExplorer";
import { useAuthStore } from "../features/auth/store";

import "../styles/nexus-experience.css";

type PreviewView = "chat" | "files" | "models";
type JourneyView = "conversation" | "knowledge" | "agents";

const SAMPLE_MODELS = [
  { id: "claude", name: "Claude · example", provider: "Anthropic" },
  { id: "gpt", name: "GPT · example", provider: "OpenAI" },
  { id: "gemini", name: "Gemini · example", provider: "Google" },
] as const;

type SampleModelId = (typeof SAMPLE_MODELS)[number]["id"];

const SUGGESTIONS = [
  "Summarize this project",
  "Plan a product launch",
  "Explain retrieval-augmented generation",
] as const;

interface PreviewMessage {
  id: number;
  role: "assistant" | "user";
  text: string;
}

const STARTER_MESSAGES: PreviewMessage[] = [
  {
    id: 1,
    role: "assistant",
    text: "Welcome to NEXUS. Select a sample model, attach a file, or try a prompt. This is a local interface demo.",
  },
];

const JOURNEYS: Record<
  JourneyView,
  {
    label: string;
    status: string;
    title: string;
    description: string;
    steps: string[];
  }
> = {
  conversation: {
    label: "01 · Conversations",
    status: "Available now",
    title: "Move between models without moving your work.",
    description:
      "One conversation workspace with live streaming, history and organization-configured models.",
    steps: [
      "Choose a model",
      "Ask a question",
      "Stream the answer",
      "Continue the conversation",
    ],
  },
  knowledge: {
    label: "02 · Knowledge + RAG",
    status: "In development",
    title: "Answers grounded in your own knowledge.",
    description:
      "NEXUS is building a permission-aware retrieval layer that processes documents, finds relevant passages and provides sourced context to the AI model.",
    steps: [
      "Bring your files",
      "Process and embed",
      "Retrieve with permissions",
      "Generate with sources",
    ],
  },
  agents: {
    label: "03 · Agentic AI",
    status: "Planned",
    title: "From answers to actions, with you in control.",
    description:
      "A future execution layer for bounded multi-step tasks, connected tools, checkpoints and human approval when it matters.",
    steps: [
      "Define the goal",
      "Plan the workflow",
      "Call authorized tools",
      "Review the result",
    ],
  },
};

function NexusBrand() {
  return (
    <span className="nx-brand">
      <span className="nx-brand-mark" aria-hidden="true">
        N
      </span>
      <span className="nx-brand-text">
        <strong>NEXUS</strong>
        <small>AI WORKSPACE</small>
      </span>
    </span>
  );
}

function PreviewWorkspace() {
  const [view, setView] = useState<PreviewView>("chat");
  const [modelId, setModelId] = useState<SampleModelId>("claude");
  const [prompt, setPrompt] = useState("");
  const [attachment, setAttachment] = useState<File | null>(null);
  const [messages, setMessages] = useState<PreviewMessage[]>(STARTER_MESSAGES);
  const attachmentInput = useRef<HTMLInputElement>(null);
  const messageId = useRef(2);
  const selectedModel =
    SAMPLE_MODELS.find((model) => model.id === modelId) ?? SAMPLE_MODELS[0];

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setAttachment(event.target.files?.[0] ?? null);
  }

  function clearFile() {
    setAttachment(null);
    if (attachmentInput.current) {
      attachmentInput.current.value = "";
    }
  }

  function sendPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question) {
      return;
    }

    const answer = /agent|plan|workflow/i.test(question)
      ? "NEXUS is designed to grow into tool-enabled, human-approved agent workflows. That execution layer is on the roadmap."
      : /rag|retriev|document|file|knowledge/i.test(question)
        ? "The retrieval foundation will connect document chunks, embeddings, authorized search and source-grounded answers. End-to-end RAG is in development."
        : "NEXUS brings model choice, conversations and files into one workspace. This is a sample response, not a live model completion.";

    const nextId = messageId.current;
    messageId.current += 2;
    setMessages((current) => [
      ...current.slice(-5),
      { id: nextId, role: "user", text: question },
      {
        id: nextId + 1,
        role: "assistant",
        text:
          selectedModel.name +
          " · simulated\n" +
          answer +
          (attachment ? "\nSelected locally: " + attachment.name : ""),
      },
    ]);
    setPrompt("");
  }

  function choosePrompt(value: string) {
    setView("chat");
    setPrompt(value);
  }

  return (
    <div
      className="nx-product-window"
      aria-label="Interactive NEXUS product preview"
    >
      <div className="nx-window-bar">
        <div className="nx-window-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <span>NEXUS / INTERACTIVE PRODUCT PREVIEW</span>
        <span aria-hidden="true">•••</span>
      </div>
      <div className="nx-preview-layout">
        <aside className="nx-preview-sidebar" aria-label="Preview navigation">
          <span className="nx-mini-caption">WORKSPACE</span>
          {(
            [
              ["chat", "✧", "Chat"],
              ["files", "▤", "Files"],
              ["models", "◈", "AI models"],
            ] as const
          ).map(([item, symbol, label]) => (
            <button
              key={item}
              type="button"
              className={
                "nx-preview-nav-item" + (view === item ? " is-selected" : "")
              }
              onClick={() => setView(item)}
              aria-pressed={view === item}
            >
              <span aria-hidden="true">{symbol}</span> {label}
            </button>
          ))}
          <span className="nx-mini-caption nx-preview-recent">YOUR SPACE</span>
          <span className="nx-preview-sidebar-detail">
            One place for work, knowledge and models.
          </span>
        </aside>
        <div className="nx-preview-main">
          {view === "chat" ? (
            <>
              <div className="nx-preview-title-row">
                <strong>✧ Ask NEXUS anything</strong>
                <span className="nx-preview-label">DEMO</span>
              </div>
              <p className="nx-preview-hint">Start somewhere inspiring...</p>
              <div className="nx-suggestion-row">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => choosePrompt(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
              <div
                className="nx-preview-messages"
                aria-live="polite"
                aria-label="Sample messages"
              >
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={"nx-message nx-message-" + message.role}
                  >
                    {message.text}
                  </div>
                ))}
              </div>
              <form className="nx-demo-composer" onSubmit={sendPreview}>
                {attachment ? (
                  <div className="nx-attached-file">
                    <span>▤ {attachment.name}</span>
                    <button
                      type="button"
                      onClick={clearFile}
                      aria-label="Remove sample file"
                    >
                      ×
                    </button>
                  </div>
                ) : null}
                <label className="nx-visually-hidden" htmlFor="nx-demo-prompt">
                  Demo message
                </label>
                <textarea
                  id="nx-demo-prompt"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Ask anything, attach a file, build an idea..."
                  rows={2}
                />
                <div className="nx-composer-actions">
                  <select
                    aria-label="Demo AI model"
                    value={modelId}
                    onChange={(event) =>
                      setModelId(event.target.value as SampleModelId)
                    }
                  >
                    {SAMPLE_MODELS.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                  <div className="nx-composer-buttons">
                    <input
                      ref={attachmentInput}
                      className="nx-visually-hidden"
                      type="file"
                      aria-label="Choose a sample file"
                      onChange={chooseFile}
                    />
                    <button
                      type="button"
                      className="nx-icon-button"
                      aria-label="Attach sample file"
                      onClick={() => attachmentInput.current?.click()}
                    >
                      +
                    </button>
                    <button
                      type="submit"
                      className="nx-send-button"
                      aria-label="Send demo message"
                    >
                      ↗
                    </button>
                  </div>
                </div>
              </form>
            </>
          ) : view === "files" ? (
            <div className="nx-preview-subscreen">
              <span className="nx-preview-label">YOUR FILES</span>
              <h3>Knowledge starts with your files.</h3>
              <p>
                Keep documents together and make them available to future
                knowledge workflows.
              </p>
              <div className="nx-demo-file-row">
                <span aria-hidden="true">▤</span>
                <span>
                  <strong>
                    {attachment ? attachment.name : "Product-brief.pdf"}
                  </strong>
                  <small>
                    {attachment
                      ? "Selected locally · not uploaded"
                      : "Illustrative file"}
                  </small>
                </span>
              </div>
              <button
                type="button"
                className="nx-mini-action"
                onClick={() => attachmentInput.current?.click()}
              >
                Choose a sample file ↗
              </button>
              <input
                ref={attachmentInput}
                className="nx-visually-hidden"
                type="file"
                aria-label="Choose a sample file"
                onChange={chooseFile}
              />
            </div>
          ) : (
            <div className="nx-preview-subscreen">
              <span className="nx-preview-label">MODEL CONTROL</span>
              <h3>Your models, your choice.</h3>
              <p>
                Switch the sample model here and continue in the chat preview.
              </p>
              <div className="nx-model-options">
                {SAMPLE_MODELS.map((model) => (
                  <button
                    key={model.id}
                    type="button"
                    className={modelId === model.id ? "is-current" : ""}
                    aria-pressed={modelId === model.id}
                    onClick={() => setModelId(model.id)}
                  >
                    <span className="nx-model-dot" aria-hidden="true" />
                    <span>
                      <strong>{model.name}</strong>
                      <small>{model.provider}</small>
                    </span>
                    <span aria-hidden="true">
                      {modelId === model.id ? "✓" : "↗"}
                    </span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="nx-mini-action"
                onClick={() => setView("chat")}
              >
                Back to chat ↗
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="nx-preview-disclaimer">
        Interactive UI preview · Model responses are simulated · Files never
        leave your browser
      </div>
    </div>
  );
}

function JourneyExplorer() {
  const [active, setActive] = useState<JourneyView>("knowledge");
  const selected = JOURNEYS[active];

  return (
    <div className="nx-journey-explorer">
      <div
        className="nx-journey-tabs"
        role="tablist"
        aria-label="Explore platform workflows"
      >
        {(
          Object.entries(JOURNEYS) as [
            JourneyView,
            (typeof JOURNEYS)[JourneyView],
          ][]
        ).map(([key, value]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active === key}
            aria-controls="nx-journey-panel"
            id={"nx-journey-tab-" + key}
            onClick={() => setActive(key)}
          >
            {value.label}
          </button>
        ))}
      </div>
      <div
        className="nx-journey-panel"
        role="tabpanel"
        id="nx-journey-panel"
        aria-labelledby={"nx-journey-tab-" + active}
      >
        <div className="nx-journey-copy">
          <span className="nx-status-pill">{selected.status}</span>
          <h3>{selected.title}</h3>
          <p>{selected.description}</p>
        </div>
        <div className="nx-journey-steps">
          {selected.steps.map((step, index) => (
            <div className="nx-journey-step" key={step}>
              <span>{"0" + (index + 1)}</span>
              <strong>{step}</strong>
              {index < selected.steps.length - 1 ? (
                <span className="nx-journey-arrow" aria-hidden="true">
                  →
                </span>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function HomePage({
  showForAuthenticated = false,
}: {
  showForAuthenticated?: boolean;
}) {
  const authStatus = useAuthStore((state) => state.status);
  const workspaceDestination =
    authStatus === "authenticated" ? "/conversations" : "/login";

  if (authStatus === "authenticated" && !showForAuthenticated) {
    return <Navigate to="/conversations" replace />;
  }

  return (
    <div className="nexus-landing">
      <div className="nx-top-accent" />
      <header className="nx-site-header">
        <div className="nx-container nx-header-inner">
          <a href="#top" aria-label="NEXUS homepage">
            <NexusBrand />
          </a>
          <nav aria-label="Site navigation" className="nx-site-nav">
            <a href="#capabilities">Explorer</a>
            <a href="#how-it-works">How it works</a>
            <a href="#knowledge">RAG &amp; agents</a>
            <a href="#security">Security</a>
          </nav>
          <div className="nx-header-actions">
            {authStatus === "authenticated" ? (
              <Link className="nx-header-login" to="/conversations">
                My workspace
              </Link>
            ) : (
              <Link className="nx-header-login" to="/login">
                Log in
              </Link>
            )}
            <Link
              className="nx-button nx-button-primary"
              to={workspaceDestination}
            >
              Open workspace <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </div>
      </header>

      <main id="top">
        <section className="nx-hero">
          <div className="nx-container nx-hero-grid">
            <div className="nx-hero-copy">
              <div className="nx-eyebrow">
                <span className="nx-spark" /> A MORE INTELLIGENT WAY TO WORK
              </div>
              <h1>
                Every idea.
                <br />
                Every model.
                <br />
                <span>One intelligent space.</span>
              </h1>
              <p>
                Your AI models, conversations and files—beautifully brought
                together. Start with a question. Grow into knowledge-driven and
                agentic work.
              </p>
              <div className="nx-hero-actions">
                <Link
                  className="nx-button nx-button-primary nx-button-large"
                  to={workspaceDestination}
                >
                  Try the workspace <span aria-hidden="true">↗</span>
                </Link>
                <a
                  className="nx-button nx-button-secondary nx-button-large"
                  href="#capabilities"
                >
                  Explore the platform <span aria-hidden="true">→</span>
                </a>
              </div>
              <div className="nx-hero-proof">
                <span className="nx-proof-icons" aria-hidden="true">
                  <i>AI</i>
                  <i>UX</i>
                  <i>↗</i>
                </span>
                <strong>Different models. One flow.</strong>
                <span>Built around your control.</span>
              </div>
            </div>
            <div className="nx-hero-preview">
              <span className="nx-glow-orbit" aria-hidden="true" />
              <PreviewWorkspace />
              <span className="nx-float-label nx-float-top">
                ✦ Your models, your choice
              </span>
              <span className="nx-float-label nx-float-bottom">
                ◈ Files meet AI
              </span>
            </div>
          </div>
        </section>

        <div className="nx-container">
          <div className="nx-trust-strip">
            <span>BUILT AROUND YOUR CONTROL</span>
            <div>
              <strong>✧ Multi-model AI</strong>
              <strong>▣ Private organizations</strong>
              <strong>◈ Bring your own keys</strong>
              <strong>◇ RBAC &amp; permissions</strong>
            </div>
          </div>
        </div>

        <section className="nx-section nx-container" id="platform">
          <div className="nx-section-heading">
            <span className="nx-kicker">THE PLATFORM</span>
            <h2>
              Everything in its place.
              <br />
              Nothing in your way.
            </h2>
            <p>
              A single workspace for today’s AI conversations and tomorrow’s
              knowledge-powered, tool-enabled experiences.
            </p>
          </div>
          <div className="nx-feature-grid">
            <article className="nx-feature-card">
              <span className="nx-feature-icon">✧</span>
              <span className="nx-feature-status">Available now</span>
              <h3>One home for every model</h3>
              <p>
                Choose from your organization’s configured AI models while
                keeping a consistent conversation experience.
              </p>
            </article>
            <article className="nx-feature-card">
              <span className="nx-feature-icon">▤</span>
              <span className="nx-feature-status">Available now</span>
              <h3>Conversations and files</h3>
              <p>
                Keep conversation history and manage uploaded files in a
                connected, purposeful workspace.
              </p>
            </article>
            <article className="nx-feature-card">
              <span className="nx-feature-icon">◈</span>
              <span className="nx-feature-status nx-status-building">
                In development
              </span>
              <h3>Knowledge that answers back</h3>
              <p>
                RAG will ground responses in relevant company documents, with
                source context and permission checks.
              </p>
            </article>
            <article className="nx-feature-card">
              <span className="nx-feature-icon">⌁</span>
              <span className="nx-feature-status nx-status-planned">
                Planned
              </span>
              <h3>Agents that do the work</h3>
              <p>
                Multi-step execution, authorized tools and human approval for
                consequential actions.
              </p>
            </article>
            <article className="nx-feature-card">
              <span className="nx-feature-icon">◇</span>
              <span className="nx-feature-status">Foundation available</span>
              <h3>Enterprise-minded security</h3>
              <p>
                Organization-aware identity, roles and permissions, with
                sensitive provider credentials handled separately.
              </p>
            </article>
            <article className="nx-feature-card">
              <span className="nx-feature-icon">↗</span>
              <span className="nx-feature-status nx-status-planned">
                Expanding
              </span>
              <h3>Integrations and developer tools</h3>
              <p>
                Extensible APIs and future tool connections designed to bring
                NEXUS into existing products and workflows.
              </p>
            </article>
          </div>
        </section>

        <NexusCapabilityExplorer authenticated={authStatus === "authenticated"} />

        <section className="nx-section nx-process-section" id="how-it-works">
          <div className="nx-container">
            <div className="nx-section-heading">
              <span className="nx-kicker">SEE THE BIGGER PICTURE</span>
              <h2>
                From a simple question
                <br />
                to an intelligent workflow.
              </h2>
              <p>
                Explore how the platform is evolving. Choose a capability to see
                its flow and current status.
              </p>
            </div>
            <JourneyExplorer />
          </div>
        </section>

        <section
          className="nx-section nx-container nx-knowledge-section"
          id="knowledge"
        >
          <div className="nx-knowledge-copy">
            <span className="nx-kicker">KNOWLEDGE + RAG · IN DEVELOPMENT</span>
            <h2>
              Your knowledge.
              <br />
              <span>Smarter answers.</span>
            </h2>
            <p>
              Retrieval-augmented generation (RAG) finds relevant information in
              your documents and adds it as context to an AI response. NEXUS is
              building this on a tenant-safe retrieval foundation—not by
              treating the language model as your document database.
            </p>
            <div className="nx-knowledge-points">
              <div>
                <span>01</span>
                <strong>Process documents and create embeddings</strong>
              </div>
              <div>
                <span>02</span>
                <strong>Search relevant, authorized content</strong>
              </div>
              <div>
                <span>03</span>
                <strong>Answer using grounded context and citations</strong>
              </div>
            </div>
          </div>
          <div
            className="nx-rag-diagram"
            aria-label="Illustrative future retrieval workflow"
          >
            <span className="nx-diagram-caption">
              RAG WORKFLOW · CONCEPT PREVIEW
            </span>
            <div className="nx-rag-card nx-rag-source">
              <span aria-hidden="true">▤</span>
              <div>
                <strong>Company knowledge</strong>
                <small>Documents &amp; files</small>
              </div>
            </div>
            <div className="nx-rag-connector" aria-hidden="true">
              ↓
            </div>
            <div className="nx-rag-card">
              <span aria-hidden="true">◈</span>
              <div>
                <strong>Embedding + retrieval</strong>
                <small>Relevant passages</small>
              </div>
            </div>
            <div className="nx-rag-connector" aria-hidden="true">
              ↓
            </div>
            <div className="nx-rag-card nx-rag-output">
              <span aria-hidden="true">✧</span>
              <div>
                <strong>Grounded AI answer</strong>
                <small>Context and source references</small>
              </div>
            </div>
            <div className="nx-rag-policy">
              ◉ Tenant and document authorization boundary
            </div>
          </div>
        </section>

        <section className="nx-agent-section">
          <div className="nx-container nx-agent-grid">
            <div>
              <span className="nx-agent-label">
                AGENTIC AI · PRODUCT ROADMAP
              </span>
              <h2>
                Go beyond answers.
                <br />
                <span>Make progress.</span>
              </h2>
              <p>
                The future NEXUS agent layer is designed to turn goals into
                controlled execution: plan work, use approved tools, request
                human confirmation and report what happened.
              </p>
              <a href="#security" className="nx-agent-link">
                Built with guardrails in mind →
              </a>
            </div>
            <div className="nx-agent-board" aria-label="Planned agent workflow">
              <div className="nx-agent-board-title">
                <span>✧</span> Agent execution preview <small>ROADMAP</small>
              </div>
              <div className="nx-agent-step">
                <span>01</span>
                <strong>Understand the objective</strong>
                <i>Goal</i>
              </div>
              <div className="nx-agent-step">
                <span>02</span>
                <strong>Plan and select tools</strong>
                <i>Plan</i>
              </div>
              <div className="nx-agent-step">
                <span>03</span>
                <strong>Request human approval</strong>
                <i>Review</i>
              </div>
              <div className="nx-agent-step">
                <span>04</span>
                <strong>Execute and verify</strong>
                <i>Result</i>
              </div>
            </div>
          </div>
        </section>

        <section
          className="nx-section nx-container nx-security-section"
          id="security"
        >
          <div className="nx-section-heading">
            <span className="nx-kicker">DESIGNED WITH BOUNDARIES</span>
            <h2>
              Intelligence that respects
              <br />
              your workspace.
            </h2>
            <p>
              NEXUS separates organizations, validates permissions and gives
              teams control over model-provider configuration. Retrieval and
              agent permissions are being expanded as those features are built.
            </p>
          </div>
          <div className="nx-security-grid">
            <div>
              <span>01 /</span>
              <h3>Organization separation</h3>
              <p>
                Tenant-linked records and authorization checks establish the
                data boundary.
              </p>
            </div>
            <div>
              <span>02 /</span>
              <h3>Roles &amp; permissions</h3>
              <p>
                Access decisions are connected to authenticated users and
                current roles.
              </p>
            </div>
            <div>
              <span>03 /</span>
              <h3>Your provider credentials</h3>
              <p>
                Configure supported model providers without exposing their
                secrets in the UI.
              </p>
            </div>
          </div>
        </section>

        <section className="nx-container nx-final-cta">
          <div>
            <span className="nx-kicker">START WITH NEXUS</span>
            <h2>
              Ideas move faster
              <br />
              when everything connects.
            </h2>
          </div>
          <Link
            className="nx-button nx-button-primary nx-button-large"
            to={workspaceDestination}
          >
            Enter NEXUS <span aria-hidden="true">↗</span>
          </Link>
        </section>
      </main>

      <footer className="nx-site-footer">
        <div className="nx-container">
          <NexusBrand />
          <span>One intelligent space. Designed to evolve.</span>
          <a href="#top">Back to top ↑</a>
        </div>
      </footer>
    </div>
  );
}
