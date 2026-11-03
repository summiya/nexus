import { useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { NexusCapabilityExplorer } from "../features/marketing/NexusCapabilityExplorer";
import { NexusWorkspacePreview } from "../features/marketing/NexusWorkspacePreview";
import { useAuthStore } from "../features/auth/store";

import "../styles/nexus-experience.css";

type JourneyView = "conversation" | "knowledge" | "agents";

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
          <div className="nx-container nx-hero-grid nx-hero-grid-next">
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
            <div className="nx-hero-preview nx-hero-preview-next">
              <NexusWorkspacePreview />
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

        <NexusCapabilityExplorer
          authenticated={authStatus === "authenticated"}
        />

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
