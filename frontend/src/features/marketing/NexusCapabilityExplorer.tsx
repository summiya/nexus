import { useState } from "react";
import { Link } from "react-router-dom";

import "../../styles/nexus-capability-explorer.css";

type Stage = "live" | "building" | "roadmap";
type Filter = "all" | Stage;
type Category = "Workspace" | "Security" | "Knowledge" | "Agents";

interface Capability {
  id: string;
  icon: string;
  title: string;
  category: Category;
  stage: Stage;
  headline: string;
  description: string;
  highlights: readonly string[];
  destination?: "/conversations" | "/files" | "/settings/ai-providers" | "/settings/ai-models";
  action?: string;
}

const CAPABILITIES: readonly Capability[] = [
  {
    id: "models", icon: "◈", title: "Multi-model AI", category: "Workspace", stage: "live",
    headline: "Your models. Your conversation.",
    description: "Connect supported model providers, register available models, and select an organization default. Switch between configured chat models in the conversation workspace.",
    highlights: ["Organization model catalog", "Explicit model selection", "Streaming conversations"],
    destination: "/settings/ai-models", action: "Manage AI models",
  },
  {
    id: "byok", icon: "⌘", title: "Bring your own key", category: "Security", stage: "live",
    headline: "Your provider credentials remain yours.",
    description: "Administrators can configure supported AI providers with their own credentials. NEXUS handles secrets through a write-only configuration flow and validates provider readiness.",
    highlights: ["Write-only credential entry", "Provider validation", "Organization-scoped configuration"],
    destination: "/settings/ai-providers", action: "Configure providers",
  },
  {
    id: "tenants", icon: "⬡", title: "Multi-tenancy", category: "Security", stage: "live",
    headline: "One platform. Separate organizations.",
    description: "Organization ownership is enforced across core records, with tenant-aware API access and database relationships. Each organization controls its own model-provider configuration.",
    highlights: ["Tenant-bound records", "Organization context", "Composite integrity boundaries"],
  },
  {
    id: "rbac", icon: "◇", title: "RBAC & permissions", category: "Security", stage: "live",
    headline: "Control access, not just accounts.",
    description: "An implemented role-and-permission model checks the authenticated user and organization before protected operations. Fine-grained document-level access is still part of the retrieval roadmap.",
    highlights: ["Organization roles", "Permission-aware APIs", "Runtime access checks"],
  },
  {
    id: "chats", icon: "✳", title: "Conversations", category: "Workspace", stage: "live",
    headline: "Keep the context. Keep moving.",
    description: "Create and continue conversations, revisit history, stream supported model responses, stop generation, and select a configured model for a message.",
    highlights: ["Conversation history", "Streaming and cancellation", "Model-aware messages"],
    destination: "/conversations", action: "Open conversations",
  },
  {
    id: "files", icon: "▤", title: "Files & uploads", category: "Workspace", stage: "live",
    headline: "Bring the material that matters.",
    description: "The file library supports organization-scoped uploads, file management, and controlled storage. It provides the foundation for future knowledge and retrieval experiences.",
    highlights: ["Upload and manage files", "Tenant-aware metadata", "Controlled storage"],
    destination: "/files", action: "Open file library",
  },
  {
    id: "ingestion", icon: "⟡", title: "Document intelligence", category: "Knowledge", stage: "building",
    headline: "From documents to searchable context.",
    description: "Document-processing and chunking foundations are implemented; the pgvector embedding schema is ready. Embedding persistence, indexing, and end-to-end retrieval are being built next.",
    highlights: ["Document processing", "Versioned chunk contracts", "PostgreSQL embedding schema"],
  },
  {
    id: "rag", icon: "◎", title: "Retrieval + RAG", category: "Knowledge", stage: "building",
    headline: "Answers backed by your knowledge.",
    description: "The planned retrieval flow will match a user's question to authorized document passages, then provide relevant context and citations to a selected AI model.",
    highlights: ["Permission-aware retrieval", "Grounded responses", "Source references"],
  },
  {
    id: "projects", icon: "▦", title: "Projects & workspaces", category: "Workspace", stage: "roadmap",
    headline: "Give every initiative its own space.",
    description: "Dedicated project experiences will organize related conversations, files, and reusable knowledge. The customer-facing project workflow is not yet available.",
    highlights: ["Project organization", "Shared context", "Team collaboration"],
  },
  {
    id: "tools", icon: "⚙", title: "Tool calling", category: "Agents", stage: "roadmap",
    headline: "Let AI do more than respond.",
    description: "NEXUS is preparing for controlled tool use, where the model requests an action and the platform validates, executes, and records the result. Live execution is not yet enabled.",
    highlights: ["Authorized execution", "Structured tool inputs", "Execution history"],
  },
  {
    id: "mcp", icon: "⌁", title: "MCP integrations", category: "Agents", stage: "roadmap",
    headline: "Connect the tools your team already uses.",
    description: "Model Context Protocol integrations are planned for connecting supported external services and organization-approved capabilities. There is no active MCP connector gallery yet.",
    highlights: ["Connected capabilities", "Scoped permissions", "Reusable integrations"],
  },
  {
    id: "agents", icon: "✦", title: "Agentic workflows", category: "Agents", stage: "roadmap",
    headline: "From a goal to a verified result.",
    description: "Future agents will plan multi-step work, invoke permitted tools, request human approval, and report progress, errors, and outcomes within explicit limits.",
    highlights: ["Plan and execute", "Human checkpoints", "Bounded workflows"],
  },
];

const FILTERS: readonly { id: Filter; label: string }[] = [
  { id: "all", label: "Everything" },
  { id: "live", label: "Available now" },
  { id: "building", label: "In development" },
  { id: "roadmap", label: "On the roadmap" },
];

const STAGE_LABELS: Record<Stage, string> = {
  live: "Available now",
  building: "In development",
  roadmap: "On the roadmap",
};

const ORGANIZATIONS = {
  northstar: { name: "Northstar Studio", file: "Brand strategy.pdf", provider: "OpenAI" },
  horizon: { name: "Horizon Research", file: "Research brief.pdf", provider: "Anthropic" },
} as const;

type ExampleOrg = keyof typeof ORGANIZATIONS;
type ExampleRole = "admin" | "member";

function WorkspaceBoundaryPreview() {
  const [org, setOrg] = useState<ExampleOrg>("northstar");
  const [role, setRole] = useState<ExampleRole>("admin");
  const selected = ORGANIZATIONS[org];

  return (
    <div className="nx-boundary-demo">
      <div className="nx-boundary-heading">
        <span className="nx-boundary-eyebrow">INTERACTIVE SECURITY ILLUSTRATION</span>
        <h3>See the boundaries in action.</h3>
        <p>Change the sample organization and role to explore the principle behind NEXUS access controls. No live account data is used.</p>
      </div>
      <div className="nx-boundary-controls">
        <label htmlFor="nx-demo-organization">Example organization</label>
        <select id="nx-demo-organization" value={org} onChange={(event) => setOrg(event.target.value as ExampleOrg)}>
          <option value="northstar">Northstar Studio</option>
          <option value="horizon">Horizon Research</option>
        </select>
        <label htmlFor="nx-demo-role">Example role</label>
        <select id="nx-demo-role" value={role} onChange={(event) => setRole(event.target.value as ExampleRole)}>
          <option value="admin">Administrator</option>
          <option value="member">Member</option>
        </select>
      </div>
      <div className="nx-boundary-view" aria-live="polite">
        <div className="nx-boundary-view-head">
          <span className="nx-boundary-org-avatar" aria-hidden="true">{selected.name.charAt(0)}</span>
          <div><strong>{selected.name}</strong><small>{role === "admin" ? "Administrator example" : "Member example"}</small></div>
          <span className="nx-boundary-protected">◈ Tenant scoped</span>
        </div>
        <div className="nx-boundary-resource">
          <span className="nx-boundary-resource-icon" aria-hidden="true">▤</span>
          <span><strong>{selected.file}</strong><small>Example file · current organization only</small></span>
          <span className="nx-boundary-check" aria-hidden="true">✓</span>
        </div>
        <div className="nx-boundary-resource">
          <span className="nx-boundary-resource-icon" aria-hidden="true">◇</span>
          <span><strong>Provider management</strong><small>{role === "admin" ? "Illustrative " + selected.provider + " configuration access" : "Illustrative restricted administrator capability"}</small></span>
          <span className="nx-boundary-check">{role === "admin" ? "✓" : "—"}</span>
        </div>
        <div className="nx-boundary-denied"><span aria-hidden="true">⊘</span><span>Other organizations' private resources remain outside this scope.</span></div>
      </div>
      <p className="nx-boundary-footnote">Illustration only. Actual roles and permissions are resolved from NEXUS authentication and authorization policies; no permissions change here.</p>
    </div>
  );
}

export function NexusCapabilityExplorer({ authenticated }: { authenticated: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState("byok");

  const filtered = CAPABILITIES.filter((feature) => filter === "all" || feature.stage === filter);
  const selected = filtered.find((feature) => feature.id === selectedId) ?? filtered[0];
  const count = (stage: Stage) => CAPABILITIES.filter((feature) => feature.stage === stage).length;

  return (
    <section className="nx-capability-section" id="capabilities" aria-labelledby="nx-capability-title">
      <div className="nx-container">
        <div className="nx-capability-heading">
          <div>
            <span className="nx-capability-kicker">EXPLORE THE NEXUS PLATFORM</span>
            <h2 id="nx-capability-title">Built for today.<br /><span>Designed for what's next.</span></h2>
            <p>Go deeper than a feature list. Explore the real NEXUS foundation and the capabilities being developed on top of it.</p>
          </div>
          <div className="nx-capability-metrics" aria-label="Capability status summary">
            <div><strong>{count("live")}</strong><span>Available</span></div>
            <div><strong>{count("building")}</strong><span>Building</span></div>
            <div><strong>{count("roadmap")}</strong><span>Roadmap</span></div>
          </div>
        </div>

        <div className="nx-capability-browser">
          <div className="nx-capability-toolbar">
            <span>THE CAPABILITY EXPLORER <span aria-hidden="true">↗</span></span>
            <div className="nx-capability-filters" role="group" aria-label="Filter capabilities">
              {FILTERS.map((option) => (
                <button type="button" key={option.id} aria-pressed={filter === option.id} className={filter === option.id ? "is-active" : ""} onClick={() => setFilter(option.id)}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="nx-capability-layout">
            <div className="nx-capability-grid" aria-label="Explore NEXUS capabilities">
              {filtered.map((feature) => (
                <button key={feature.id} type="button" className={"nx-capability-tile" + (selected.id === feature.id ? " is-selected" : "")} onClick={() => setSelectedId(feature.id)} aria-pressed={selected.id === feature.id}>
                  <span className="nx-capability-tile-top">
                    <span className="nx-capability-symbol" aria-hidden="true">{feature.icon}</span>
                    <span className={"nx-capability-stage nx-stage-" + feature.stage}>{STAGE_LABELS[feature.stage]}</span>
                  </span>
                  <strong>{feature.title}</strong>
                  <span className="nx-capability-tile-caption">{feature.category}</span>
                  <span className="nx-capability-tile-arrow" aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
            <div className="nx-capability-inspector" aria-live="polite">
              <div className="nx-inspector-topline"><span>CAPABILITY / {selected.category.toUpperCase()}</span><span>✧ NEXUS</span></div>
              <span className={"nx-inspector-status nx-inspector-" + selected.stage}><span aria-hidden="true">●</span> {STAGE_LABELS[selected.stage]}</span>
              <div className="nx-inspector-symbol" aria-hidden="true">{selected.icon}</div>
              <h3>{selected.headline}</h3>
              <p>{selected.description}</p>
              <div className="nx-inspector-list">
                <span>WHAT THIS INCLUDES</span>
                {selected.highlights.map((highlight) => <div key={highlight}><span aria-hidden="true">✓</span> {highlight}</div>)}
              </div>
              {selected.destination ? (
                <Link className="nx-inspector-action" to={authenticated ? selected.destination : "/login"}>
                  {authenticated ? selected.action : "Sign in to explore"} <span aria-hidden="true">↗</span>
                </Link>
              ) : (
                <div className="nx-inspector-nonlink">
                  {selected.stage === "live" ? "Core platform foundation · no separate page yet" : "Preview only · not enabled in the workspace yet"}
                </div>
              )}
            </div>
          </div>
          <div className="nx-capability-browser-footer"><span>01 / EXPLORE</span><span>Real capabilities, clearly distinguished from the roadmap</span></div>
        </div>
        <WorkspaceBoundaryPreview />
      </div>
    </section>
  );
}
