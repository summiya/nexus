import { useState } from "react";
import { Link } from "react-router-dom";

import { DashboardIcon, type DashboardIconName } from "../components/dashboard/DashboardIcon";
import { useConversationsQuery } from "../features/conversations/queries";

type ConceptId = "projects" | "knowledge-bases" | "artifacts" | "agents" | "tools" | "incidents";

interface ConceptItem {
  id: string;
  title: string;
  description: string;
  symbol: DashboardIconName;
  category: string;
  detail: string;
}

interface ConceptConfig {
  label: string;
  eyebrow: string;
  introduction: string;
  action: string;
  emptyTitle: string;
  icon: DashboardIconName;
  items: readonly ConceptItem[];
}

const concepts: Record<ConceptId, ConceptConfig> = {
  projects: {
    label: "Projects",
    eyebrow: "WORKSPACE / PROJECTS",
    introduction: "Everything connected to a goal. Organize conversations, files and knowledge in dedicated workspaces.",
    action: "New project",
    emptyTitle: "Untitled project",
    icon: "projects",
    items: [
      { id: "launch", title: "Product launch", description: "Coordinate milestones, deliverables and knowledge", symbol: "projects", category: "Project example", detail: "A project can bring conversations, artifacts and supporting material together, so the team works from shared context." },
      { id: "engineering", title: "Engineering hub", description: "Architecture reviews, API plans and design decisions", symbol: "artifacts", category: "Project example", detail: "A dedicated space for technical decisions, reusable project context and work across development teams." },
      { id: "research", title: "Research library", description: "Collect findings, questions and source material", symbol: "knowledge", category: "Project example", detail: "Keep research material organized and ready to inform future retrieval-augmented conversations." },
    ],
  },
  "knowledge-bases": {
    label: "Knowledge bases",
    eyebrow: "KNOWLEDGE / COLLECTIONS",
    introduction: "Create reusable collections of trusted content. Explore how documents will feed permission-aware retrieval.",
    action: "New knowledge base",
    emptyTitle: "New knowledge base",
    icon: "knowledge",
    items: [
      { id: "engineering", title: "Product engineering", description: "Technical specifications and design notes", symbol: "knowledge", category: "Knowledge example", detail: "Centralize specifications for future chunking, embedding, retrieval and grounded answers." },
      { id: "operations", title: "Operations handbook", description: "Processes, policies and team procedures", symbol: "files", category: "Knowledge example", detail: "A reusable source of operational guidance, with organization boundaries at retrieval time." },
      { id: "research", title: "Research references", description: "Insights, transcripts and reference material", symbol: "artifacts", category: "Knowledge example", detail: "Searchable organization knowledge that can be attached to the right workspace." },
    ],
  },
  artifacts: {
    label: "Artifacts",
    eyebrow: "WORKSPACE / ARTIFACTS",
    introduction: "Move beyond messages. Turn ideas into editable plans, documents, code and structured deliverables.",
    action: "Create artifact",
    emptyTitle: "Untitled artifact",
    icon: "artifacts",
    items: [
      { id: "brief", title: "Launch brief", description: "Structured product narrative and rollout plan", symbol: "files", category: "Document example", detail: "Overview, audience, goals, key decisions, dates and review status. This is illustrative content, not a stored artifact." },
      { id: "code", title: "API integration example", description: "Code snippet and usage documentation", symbol: "artifacts", category: "Code example", detail: "A place to view, refine and export generated code and its integration notes." },
      { id: "research", title: "Competitive analysis", description: "Comparable options with supporting evidence", symbol: "overview", category: "Analysis example", detail: "Turn research into a clear comparison with assumptions, findings and source references." },
    ],
  },
  agents: {
    label: "Agents",
    eyebrow: "INTELLIGENCE / AGENTS",
    introduction: "Give goals structure with specialized assistants, approved tools and human-controlled checkpoints.",
    action: "Create agent",
    emptyTitle: "New agent",
    icon: "agents",
    items: [
      { id: "research", title: "Research assistant", description: "Collect and compare authorized sources", symbol: "search", category: "Agent example", detail: "Define a research goal, identify information sources, compare results and ask for review before publishing a summary." },
      { id: "delivery", title: "Delivery coordinator", description: "Plan tasks and request human approval", symbol: "projects", category: "Agent example", detail: "Break delivery goals into steps, track dependencies and request approvals before consequential actions." },
      { id: "knowledge", title: "Knowledge analyst", description: "Prepare grounded answers from shared content", symbol: "knowledge", category: "Agent example", detail: "Use organization-approved retrieval to prepare summaries with traceable sources and explicit boundaries." },
    ],
  },
  tools: {
    label: "MCP & tools",
    eyebrow: "INTELLIGENCE / INTEGRATIONS",
    introduction: "A command center for connected services, reusable tools and MCP servers in one secure workspace.",
    action: "Add integration",
    emptyTitle: "New integration",
    icon: "tools",
    items: [
      { id: "github", title: "GitHub", description: "Repositories, issues and code review", symbol: "projects", category: "Integration example", detail: "Configure scoped repository access, inspect available actions and approve tool execution policies." },
      { id: "confluence", title: "Confluence", description: "Internal pages and team knowledge", symbol: "knowledge", category: "Integration example", detail: "Connect approved spaces for knowledge retrieval and documented actions." },
      { id: "mcp", title: "Custom MCP server", description: "Organization-managed tool capabilities", symbol: "tools", category: "MCP example", detail: "Register a trusted MCP server, review its advertised tools and define access boundaries." },
    ],
  },
  incidents: {
    label: "Incidents",
    eyebrow: "OPERATIONS / INCIDENTS",
    introduction: "A future home for AI platform reliability signals, investigations and incident response workflows.",
    action: "Create incident",
    emptyTitle: "New incident",
    icon: "incidents",
    items: [
      { id: "latency", title: "Latency investigation", description: "A sample API responsiveness investigation", symbol: "usage", category: "Incident example", detail: "Track impact, timeline, ownership, mitigations and follow-up actions for degraded performance." },
      { id: "providers", title: "Provider availability", description: "A sample model-provider interruption", symbol: "security", category: "Incident example", detail: "Record provider degradation, alternative models and communication checkpoints." },
      { id: "retrieval", title: "Retrieval quality", description: "A sample knowledge-quality investigation", symbol: "knowledge", category: "Incident example", detail: "Review quality regressions, evidence, remediation steps and validation criteria." },
    ],
  },
};

export function WorkspaceOverviewPage() {
  const conversations = useConversationsQuery();
  const recent = conversations.data?.slice(0, 4) ?? [];

  return (
    <section className="nx-ui-page nx-overview-page">
      <div className="nx-ui-heading nx-overview-hero">
        <div>
          <span className="nx-ui-eyebrow"><DashboardIcon name="sparkle" size={16} /> NEXUS WORKSPACE</span>
          <h1>Good to have you here.</h1>
          <p>One place to think, build, organize knowledge and connect the tools that move your work forward.</p>
          <div className="nx-overview-hero-actions">
            <Link className="nx-ui-button nx-ui-button-primary" to="/conversations">
              <DashboardIcon name="chat" size={17} /> Start a conversation
            </Link>
            <Link className="nx-ui-button nx-ui-button-subtle" to="/files">
              <DashboardIcon name="files" size={17} /> Open your files
            </Link>
          </div>
        </div>
        <div className="nx-overview-illustration" aria-hidden="true">
          <div className="nx-overview-illustration-center">✧</div>
          <span>◈</span><span>▦</span><span>⌁</span>
        </div>
      </div>

      <div className="nx-ui-section-heading">
        <div><span className="nx-ui-eyebrow">GET TO WORK</span><h2>Everything in one space</h2></div>
        <span className="nx-ui-muted">Select a destination to continue</span>
      </div>
      <div className="nx-overview-capabilities">
        {([
          ["Projects", "Organize initiatives and shared context", "projects", "/projects"],
          ["Knowledge bases", "Build a source of trusted answers", "knowledge", "/knowledge-bases"],
          ["Artifacts", "Create polished deliverables", "artifacts", "/artifacts"],
          ["Agents", "Structure multi-step work", "agents", "/agents"],
          ["MCP & tools", "Connect external capabilities", "tools", "/tools"],
          ["Incidents", "Explore reliability workflows", "incidents", "/incidents"],
        ] as const).map(([title, text, icon, path]) => (
          <Link className="nx-overview-capability" key={path} to={path}>
            <span><DashboardIcon name={icon} size={21} /></span>
            <strong>{title}</strong>
            <small>{text}</small>
            <DashboardIcon name="arrow" size={16} />
          </Link>
        ))}
      </div>

      <div className="nx-overview-lower">
        <section className="nx-ui-surface">
          <div className="nx-ui-section-heading">
            <div><span className="nx-ui-eyebrow">ACTIVITY</span><h2>Recent conversations</h2></div>
            <Link className="nx-ui-text-link" to="/conversations">View all →</Link>
          </div>
          {conversations.isPending ? <p role="status">Loading conversations…</p>
            : conversations.isError ? <p>Conversations are temporarily unavailable.</p>
              : recent.length === 0 ? (
                <div className="nx-ui-empty-state"><DashboardIcon name="chat" size={30} /><strong>No conversations yet</strong><p>Start a conversation to see it here.</p></div>
              ) : (
                <div className="nx-overview-recent-list">
                  {recent.map((item) => (
                    <Link key={item.publicId} to={"/conversations/" + item.publicId}>
                      <DashboardIcon name="chat" size={18} />
                      <span>{item.title ?? "New conversation"}</span>
                      <DashboardIcon name="arrow" size={15} />
                    </Link>
                  ))}
                </div>
              )}
        </section>
        <section className="nx-ui-surface nx-overview-access">
          <span className="nx-ui-eyebrow">YOUR ORGANIZATION</span>
          <div className="nx-overview-access-icon"><DashboardIcon name="security" size={25} /></div>
          <h2>Control stays with your team.</h2>
          <p>Organization-scoped access, role-based permissions and configurable AI providers are part of the platform foundation.</p>
          <Link className="nx-ui-text-link" to="/settings/ai-providers">Manage provider credentials →</Link>
        </section>
      </div>
    </section>
  );
}

export function WorkspaceConceptPage({ section }: { section: ConceptId }) {
  const config = concepts[section];
  const [query, setQuery] = useState("");
  const [localItems, setLocalItems] = useState<ConceptItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "context" | "access">("overview");
  const [notice, setNotice] = useState<string | null>(null);
  const entries = [...localItems, ...config.items];
  const displayed = entries.filter((entry) =>
    [entry.title, entry.description, entry.category].join(" ").toLowerCase().includes(query.trim().toLowerCase()),
  );
  const selected = entries.find((entry) => entry.id === selectedId) ?? entries[0];

  function createLocalItem() {
    const id = "local-" + String(localItems.length + 1);
    const item: ConceptItem = {
      id,
      title: config.emptyTitle + (localItems.length === 0 ? "" : " " + (localItems.length + 1)),
      description: "A local draft inside this design preview",
      symbol: config.icon,
      category: "Preview draft",
      detail: "This draft is stored only in the current page state. No backend resources were created.",
    };
    setLocalItems((current) => [item, ...current]);
    setSelectedId(id);
    setNotice("Sample item created in this preview only.");
    setQuery("");
    setActiveTab("overview");
  }

  return (
    <section className="nx-ui-page nx-concept-page">
      <header className="nx-ui-heading">
        <div>
          <span className="nx-ui-eyebrow"><DashboardIcon name={config.icon} size={15} /> {config.eyebrow}</span>
          <h1>{config.label}</h1>
          <p>{config.introduction}</p>
        </div>
        <button type="button" className="nx-ui-button nx-ui-button-primary" onClick={createLocalItem}>
          ＋ {config.action}
        </button>
      </header>

      <div className="nx-ui-stat-strip">
        <div><span><DashboardIcon name={config.icon} size={18} /></span><strong>{entries.length}</strong><small>Example entries</small></div>
        <div><span><DashboardIcon name="security" size={18} /></span><strong>Scoped</strong><small>Organization concept</small></div>
        <div><span><DashboardIcon name="sparkle" size={18} /></span><strong>UI preview</strong><small>Not connected to the backend</small></div>
      </div>

      <div className="nx-concept-main">
        <section className="nx-ui-surface nx-concept-browser" aria-label={config.label + " list"}>
          <div className="nx-ui-section-heading">
            <div><span className="nx-ui-eyebrow">BROWSE</span><h2>Explore {config.label.toLowerCase()}</h2></div>
            <span className="nx-ui-muted">Sample workspace</span>
          </div>
          <div className="nx-ui-search-field">
            <DashboardIcon name="search" size={18} />
            <label htmlFor="nx-concept-filter" className="nx-ui-visually-hidden">Filter {config.label.toLowerCase()}</label>
            <input
              id="nx-concept-filter"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={"Filter " + config.label.toLowerCase() + "..."}
            />
          </div>
          {displayed.length === 0 ? <p className="nx-ui-muted">No matching preview entries.</p> : (
            <div className="nx-concept-card-grid">
              {displayed.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  aria-pressed={selected.id === item.id}
                  className={"nx-concept-card" + (selected.id === item.id ? " is-selected" : "")}
                  onClick={() => {
                    setSelectedId(item.id);
                    setActiveTab("overview");
                  }}
                >
                  <span className="nx-concept-card-symbol"><DashboardIcon name={item.symbol} size={24} /></span>
                  <strong>{item.title}</strong>
                  <small>{item.description}</small>
                  <span className="nx-concept-card-footer">{item.category} <DashboardIcon name="arrow" size={15} /></span>
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="nx-ui-surface nx-concept-detail">
          <div className="nx-ui-section-heading"><span className="nx-ui-eyebrow">INSPECTOR</span><span className="nx-ui-muted">Design preview</span></div>
          <span className="nx-concept-detail-icon"><DashboardIcon name={selected.symbol} size={27} /></span>
          <h2>{selected.title}</h2>
          <p>{selected.description}</p>
          <div className="nx-concept-tabs" role="tablist" aria-label="Preview item details">
            {(["overview", "context", "access"] as const).map((tab) => (
              <button
                key={tab}
                role="tab"
                type="button"
                aria-selected={activeTab === tab}
                aria-controls="nx-concept-details-panel"
                id={"nx-concept-tab-" + tab}
                onClick={() => setActiveTab(tab)}
              >
                {tab === "overview" ? "Overview" : tab === "context" ? "Context" : "Access"}
              </button>
            ))}
          </div>
          <div role="tabpanel" id="nx-concept-details-panel" aria-labelledby={"nx-concept-tab-" + activeTab} className="nx-concept-detail-body">
            {activeTab === "overview" ? <p>{selected.detail}</p> : null}
            {activeTab === "context" ? <p>Connect the right conversations, files and sources to keep this work grounded. This is a visual demonstration only.</p> : null}
            {activeTab === "access" ? <p>Organization-scoped identity and permission checks will govern access to these resources when the feature is implemented.</p> : null}
          </div>
          <div className="nx-concept-detail-footer">
            <DashboardIcon name="security" size={16} />
            <span>No live tools or records are changed in this preview.</span>
          </div>
        </aside>
      </div>

      {notice ? <p className="nx-ui-notice" role="status">{notice}</p> : null}
    </section>
  );
}
