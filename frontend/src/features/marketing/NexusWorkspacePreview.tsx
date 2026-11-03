import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";

import "../../styles/nexus-workspace-preview.css";

type View =
  "chat" | "projects" | "artifacts" | "tools" | "agents" | "files" | "models";
type ModelId = "claude" | "gpt" | "gemini";
type ConnectorKind = "mcp" | "tool";
type ConnectionFilter = "all" | "connected";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface DemoConversation {
  id: string;
  title: string;
  updated: string;
  messages: Message[];
}

interface DemoProject {
  id: string;
  title: string;
  description: string;
  icon: string;
  details: string;
  documents: string;
}

interface DemoArtifact {
  id: string;
  title: string;
  kind: string;
  summary: string;
  content: string;
}

interface DemoConnector {
  id: string;
  name: string;
  caption: string;
  symbol: string;
  kind: ConnectorKind;
  connected: boolean;
}

const MODELS: readonly {
  id: ModelId;
  label: string;
  provider: string;
  symbol: string;
}[] = [
  { id: "claude", label: "Claude Sonnet", provider: "Anthropic", symbol: "✳" },
  { id: "gpt", label: "GPT", provider: "OpenAI", symbol: "◈" },
  { id: "gemini", label: "Gemini", provider: "Google", symbol: "✦" },
];

const INITIAL_CONVERSATIONS: DemoConversation[] = [
  {
    id: "launch",
    title: "Q4 product launch strategy",
    updated: "Today",
    messages: [
      {
        id: "launch-1",
        role: "user",
        content: "Help me organize our Q4 product launch.",
      },
      {
        id: "launch-2",
        role: "assistant",
        content:
          "I outlined a launch plan with audience segments, milestones, dependencies, and a readiness checklist. We can turn it into a project or an artifact next.",
      },
    ],
  },
  {
    id: "architecture",
    title: "Platform architecture review",
    updated: "Yesterday",
    messages: [
      {
        id: "arch-1",
        role: "user",
        content: "What should we check before scaling our platform?",
      },
      {
        id: "arch-2",
        role: "assistant",
        content:
          "Start with isolation boundaries, latency budgets, idempotent background jobs, observability, and failure recovery. I can put these into an architecture review artifact.",
      },
    ],
  },
  {
    id: "knowledge",
    title: "Knowledge retrieval design",
    updated: "Mon",
    messages: [
      {
        id: "rag-1",
        role: "user",
        content: "Design a secure enterprise RAG flow.",
      },
      {
        id: "rag-2",
        role: "assistant",
        content:
          "An illustrative RAG flow is: ingest documents, chunk and embed, retrieve tenant-authorized passages, rerank, and generate with citations.",
      },
    ],
  },
];

const INITIAL_PROJECTS: DemoProject[] = [
  {
    id: "strategy",
    title: "Product strategy",
    description: "Campaign planning and launch decisions",
    icon: "◧",
    details: "3 conversations",
    documents: "5 documents",
  },
  {
    id: "engineering",
    title: "Engineering hub",
    description: "Architecture, APIs, and implementation",
    icon: "⌘",
    details: "8 conversations",
    documents: "12 documents",
  },
  {
    id: "research",
    title: "Research library",
    description: "Insights, interviews, and findings",
    icon: "◇",
    details: "4 conversations",
    documents: "9 documents",
  },
];

const INITIAL_ARTIFACTS: DemoArtifact[] = [
  {
    id: "brief",
    title: "Launch brief",
    kind: "Document",
    summary: "Audience, positioning, and rollout",
    content:
      "Product launch brief\n\nObjective: introduce the new experience clearly.\n\nAudience: early adopters and team leads.\n\nMilestones: discovery → preview → launch → review.\n\nSuccess: activation, engagement, and feedback.",
  },
  {
    id: "analysis",
    title: "Market comparison",
    kind: "Analysis",
    summary: "A structured competitive snapshot",
    content:
      "Market comparison\n\nDimension       Platform A       Platform B\nIntegrations    Connected        Limited\nControl         Team-scoped      Personal\nAutomation      Multi-step       Manual\n\nIllustrative sample data only.",
  },
  {
    id: "code",
    title: "API example",
    kind: "Code",
    summary: "A reusable integration pattern",
    content:
      "async function generateSummary(input) {\n  const response = await client.messages.create({\n    model: selectedModel,\n    input,\n  });\n\n  return response.content;\n}\n\n// Illustrative pseudocode only.",
  },
];

const INITIAL_CONNECTORS: DemoConnector[] = [
  {
    id: "github",
    name: "GitHub",
    caption: "Repositories and issues",
    symbol: "⌘",
    kind: "tool",
    connected: true,
  },
  {
    id: "drive",
    name: "Google Drive",
    caption: "Documents and folders",
    symbol: "▤",
    kind: "tool",
    connected: false,
  },
  {
    id: "slack",
    name: "Slack",
    caption: "Messages and channels",
    symbol: "▦",
    kind: "tool",
    connected: false,
  },
  {
    id: "confluence",
    name: "Confluence",
    caption: "Team knowledge",
    symbol: "◫",
    kind: "tool",
    connected: true,
  },
  {
    id: "mcp-files",
    name: "Workspace MCP",
    caption: "Scoped file capabilities",
    symbol: "⌁",
    kind: "mcp",
    connected: false,
  },
  {
    id: "mcp-data",
    name: "Data MCP",
    caption: "Structured data tools",
    symbol: "◇",
    kind: "mcp",
    connected: false,
  },
];

const QUICK_ACTIONS = [
  {
    id: "summarize",
    symbol: "✧",
    title: "Summarize a document",
    note: "Extract the signal",
    prompt: "Summarize this project and list next steps.",
  },
  {
    id: "project",
    symbol: "▦",
    title: "Plan a project",
    note: "From idea to milestones",
    prompt: "Plan a product launch.",
  },
  {
    id: "research",
    symbol: "◎",
    title: "Research with knowledge",
    note: "Explore grounded answers",
    prompt: "Explain retrieval-augmented generation.",
  },
  {
    id: "artifact",
    symbol: "◫",
    title: "Create an artifact",
    note: "Turn ideas into deliverables",
    prompt: "Create a launch brief artifact.",
  },
] as const;

const NAV_ITEMS: readonly { id: View; icon: string; label: string }[] = [
  { id: "projects", icon: "▦", label: "Projects" },
  { id: "artifacts", icon: "◫", label: "Artifacts" },
  { id: "tools", icon: "⌁", label: "Tools & MCP" },
  { id: "agents", icon: "✦", label: "Agents" },
  { id: "files", icon: "▤", label: "Files" },
  { id: "models", icon: "◈", label: "AI models" },
];

const AGENT_STEPS = ["Objective", "Plan", "Approval", "Result"] as const;

function createDemoResponse(
  question: string,
  modelLabel: string,
  toolName: string | null,
): string {
  const normalized = question.toLowerCase();
  const intro =
    normalized.includes("artifact") || normalized.includes("brief")
      ? "I've drafted a structured outline with a goal, audience, milestones, and next steps. Explore Artifacts to preview a deliverable."
      : normalized.includes("mcp") ||
          normalized.includes("tool") ||
          normalized.includes("connect")
        ? "The tools workspace shows how connected services and MCP servers could be selected for authorized actions."
        : normalized.includes("project") ||
            normalized.includes("launch") ||
            normalized.includes("plan")
          ? "Here's a starting plan: define the outcome, map the milestones, assign owners, and set review checkpoints."
          : normalized.includes("rag") ||
              normalized.includes("retriev") ||
              normalized.includes("knowledge")
            ? "A grounded AI workflow retrieves relevant, permitted passages, adds context to the prompt, then returns an answer with sources."
            : "I can help organize your ideas into conversations, projects, artifacts, or connected workflows.";

  const context = toolName ? " Sample tool selected: " + toolName + "." : "";
  return modelLabel + " · simulated response\n\n" + intro + context;
}

function SmallSectionHeading({
  title,
  action,
}: {
  title: string;
  action?: string;
}) {
  return (
    <div className="nx-ws-section-heading">
      <span>{title}</span>
      {action ? <span className="nx-ws-section-meta">{action}</span> : null}
    </div>
  );
}

export function NexusWorkspacePreview() {
  const [view, setView] = useState<View>("chat");
  const [modelId, setModelId] = useState<ModelId>("claude");
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState<string | null>(null);
  const [localFiles, setLocalFiles] = useState<string[]>([]);
  const [conversations, setConversations] = useState(INITIAL_CONVERSATIONS);
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null);
  const [projects, setProjects] = useState(INITIAL_PROJECTS);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const [artifacts, setArtifacts] = useState(INITIAL_ARTIFACTS);
  const [selectedArtifactId, setSelectedArtifactId] = useState("brief");
  const [connectors, setConnectors] = useState(INITIAL_CONNECTORS);
  const [connectorFilter, setConnectorFilter] =
    useState<ConnectionFilter>("all");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<"research" | "delivery">(
    "research",
  );
  const [agentStep, setAgentStep] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const nextItemId = useRef(1);

  const currentModel =
    MODELS.find((model) => model.id === modelId) ?? MODELS[0];
  const selectedConversation = conversations.find(
    (conversation) => conversation.id === activeConversationId,
  );
  const selectedArtifact =
    artifacts.find((artifact) => artifact.id === selectedArtifactId) ??
    artifacts[0];
  const selectedProject = projects.find(
    (project) => project.id === selectedProjectId,
  );
  const selectedTool = connectors.find(
    (connector) => connector.id === selectedToolId,
  );
  const visibleConversations = conversations.filter((item) =>
    item.title.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const visibleConnectors = connectors.filter(
    (connector) => connectorFilter === "all" || connector.connected,
  );

  function navigateTo(nextView: View) {
    setView(nextView);
    setActionNotice(null);
    setToolsOpen(false);
  }

  function newChat() {
    setActiveConversationId(null);
    setDraft("");
    navigateTo("chat");
  }

  function openConversation(id: string) {
    setActiveConversationId(id);
    navigateTo("chat");
  }

  function choosePrompt(value: string) {
    setActiveConversationId(null);
    setDraft(value);
    navigateTo("chat");
  }

  function pickSampleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setAttachment(file.name);
    setLocalFiles((current) =>
      [file.name, ...current.filter((name) => name !== file.name)].slice(0, 5),
    );
    setActionNotice("File selected locally. It has not been uploaded.");
    if (fileRef.current) fileRef.current.value = "";
  }

  function removeAttachment() {
    setAttachment(null);
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content) return;

    const suffix = String(nextItemId.current++);
    const toolName = selectedTool?.name ?? null;
    const messages: Message[] = [
      {
        id: "user-" + suffix,
        role: "user",
        content:
          content + (attachment ? "\nAttached locally: " + attachment : ""),
      },
      {
        id: "assistant-" + suffix,
        role: "assistant",
        content: createDemoResponse(content, currentModel.label, toolName),
      },
    ];

    if (activeConversationId !== null) {
      setConversations((current) =>
        current.map((item) =>
          item.id === activeConversationId
            ? {
                ...item,
                messages: [...item.messages, ...messages],
                updated: "Just now",
              }
            : item,
        ),
      );
    } else {
      const id = "new-" + suffix;
      setConversations((current) => [
        {
          id,
          title: content.length > 33 ? content.slice(0, 33) + "…" : content,
          updated: "Just now",
          messages,
        },
        ...current,
      ]);
      setActiveConversationId(id);
    }
    setDraft("");
    setAttachment(null);
    setToolsOpen(false);
    setActionNotice(null);
  }

  function handleComposerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function addProject() {
    const id = "project-" + String(nextItemId.current++);
    setProjects((current) => [
      {
        id,
        title: "New project",
        description: "A space for ideas, files, and conversations",
        icon: "◈",
        details: "0 conversations",
        documents: "0 documents",
      },
      ...current,
    ]);
    setSelectedProjectId(id);
    setActionNotice("A sample project was created in this local preview.");
  }

  function addArtifact() {
    const id = "artifact-" + String(nextItemId.current++);
    setArtifacts((current) => [
      {
        id,
        title: "New workspace note",
        kind: "Document",
        summary: "An editable-looking concept document",
        content:
          "New workspace note\n\nOverview\nCapture your goal and key context.\n\nNext steps\n1. Define the outcome.\n2. Gather supporting material.\n3. Share for review.\n\nThis document exists only in the demo.",
      },
      ...current,
    ]);
    setSelectedArtifactId(id);
    setActionNotice("A sample artifact was added to this local preview.");
  }

  function toggleConnector(id: string) {
    setConnectors((current) =>
      current.map((connector) =>
        connector.id === id
          ? { ...connector, connected: !connector.connected }
          : connector,
      ),
    );
    setActionNotice(
      "Connector selection changed in the demo only. No external account was accessed.",
    );
  }

  function renderChat() {
    return (
      <div className="nx-ws-chat">
        {selectedConversation ? (
          <div
            className="nx-ws-thread"
            aria-label="Sample conversation history"
          >
            <div className="nx-ws-thread-heading">
              <span>CONVERSATION</span>
              <h3>{selectedConversation.title}</h3>
              <p>Explore a sample multi-model conversation.</p>
            </div>
            <div className="nx-ws-thread-messages" aria-live="polite">
              {selectedConversation.messages.map((message) => (
                <div
                  key={message.id}
                  className={"nx-ws-bubble nx-ws-bubble-" + message.role}
                >
                  <span className="nx-ws-bubble-author">
                    {message.role === "user" ? "You" : "✧ NEXUS"}
                  </span>
                  <span>{message.content}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="nx-ws-chat-welcome">
            <div className="nx-ws-welcome-icon" aria-hidden="true">
              ✧
            </div>
            <span className="nx-ws-overline">YOUR INTELLIGENT WORKSPACE</span>
            <h3>Where should we begin?</h3>
            <p>
              Think, create, research, or connect your tools. One workspace for
              every idea.
            </p>
            <div className="nx-ws-suggestions">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  onClick={() => choosePrompt(action.prompt)}
                >
                  <span className="nx-ws-action-symbol" aria-hidden="true">
                    {action.symbol}
                  </span>
                  <span>
                    <strong>{action.title}</strong>
                    <small>{action.note}</small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <form className="nx-ws-composer" onSubmit={submitMessage}>
          {attachment ? (
            <div className="nx-ws-file-pill">
              <span>▤ {attachment}</span>
              <button
                type="button"
                onClick={removeAttachment}
                aria-label="Remove sample file"
              >
                ×
              </button>
            </div>
          ) : null}
          <label htmlFor="nx-ws-prompt" className="nx-ws-hidden">
            Demo message
          </label>
          <textarea
            id="nx-ws-prompt"
            rows={2}
            placeholder="Ask a question, create something, or explore an idea..."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKey}
          />
          <div className="nx-ws-composer-bottom">
            <div className="nx-ws-composer-actions">
              <button
                type="button"
                className="nx-ws-composer-icon"
                onClick={() => fileRef.current?.click()}
                aria-label="Attach sample file"
                title="Choose a sample file"
              >
                ＋
              </button>
              <div className="nx-ws-tools-area">
                <button
                  type="button"
                  className={"nx-ws-tool-chip" + (toolsOpen ? " is-on" : "")}
                  onClick={() => setToolsOpen((open) => !open)}
                  aria-label="Choose demo tools"
                  aria-expanded={toolsOpen}
                >
                  <span aria-hidden="true">⌁</span> Tools{" "}
                  <span aria-hidden="true">⌄</span>
                </button>
                {toolsOpen ? (
                  <div
                    className="nx-ws-tool-menu"
                    aria-label="Demo tool picker"
                  >
                    <span>SELECT A TOOL · DEMO ONLY</span>
                    {connectors.map((connector) => (
                      <button
                        key={connector.id}
                        type="button"
                        aria-pressed={selectedToolId === connector.id}
                        className={
                          selectedToolId === connector.id ? "is-selected" : ""
                        }
                        onClick={() => {
                          setSelectedToolId((current) =>
                            current === connector.id ? null : connector.id,
                          );
                          setToolsOpen(false);
                        }}
                      >
                        <span aria-hidden="true">{connector.symbol}</span>
                        {connector.name}
                        <small>
                          {selectedToolId === connector.id ? "✓" : ""}
                        </small>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className="nx-ws-project-chip"
                onClick={() => navigateTo("projects")}
              >
                ▦ Projects
              </button>
            </div>
            <div className="nx-ws-composer-right">
              <select
                aria-label="Demo AI model"
                value={modelId}
                onChange={(event) => setModelId(event.target.value as ModelId)}
              >
                {MODELS.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                className="nx-ws-submit"
                aria-label="Send demo message"
                disabled={draft.trim().length === 0}
                title="Send sample message"
              >
                ↑
              </button>
            </div>
          </div>
          {selectedTool ? (
            <div className="nx-ws-selected-tool">
              ⌁ {selectedTool.name} selected for this demo{" "}
              <button
                type="button"
                aria-label="Clear demo tool"
                onClick={() => setSelectedToolId(null)}
              >
                ×
              </button>
            </div>
          ) : null}
        </form>
        <div className="nx-ws-composer-note">
          NEXUS can make mistakes · Interactive concept preview
        </div>
      </div>
    );
  }

  function renderProjects() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">WORK ORGANIZED</span>
            <h3>Projects</h3>
            <p>Keep conversations, knowledge, and deliverables together.</p>
          </div>
          <button
            type="button"
            className="nx-ws-small-primary"
            onClick={addProject}
          >
            ＋ New project
          </button>
        </div>
        <div className="nx-ws-card-grid">
          {projects.map((project) => (
            <button
              type="button"
              key={project.id}
              className={
                "nx-ws-project-card" +
                (project.id === selectedProjectId ? " is-selected" : "")
              }
              onClick={() => setSelectedProjectId(project.id)}
            >
              <span className="nx-ws-card-icon" aria-hidden="true">
                {project.icon}
              </span>
              <strong>{project.title}</strong>
              <span className="nx-ws-card-description">
                {project.description}
              </span>
              <small>
                {project.details} · {project.documents}
              </small>
              <span className="nx-ws-card-arrow" aria-hidden="true">
                ↗
              </span>
            </button>
          ))}
        </div>
        <div className="nx-ws-detail-panel">
          <span className="nx-ws-overline">PROJECT OVERVIEW</span>
          <h4>
            {selectedProject
              ? selectedProject.title
              : "A place for everything related."}
          </h4>
          <p>
            {selectedProject
              ? selectedProject.description
              : "Select a project to explore its conversations, attached knowledge, and artifacts."}
          </p>
          <button
            type="button"
            className="nx-ws-text-action"
            onClick={() =>
              choosePrompt(
                "Let's work on " +
                  (selectedProject?.title ?? "a new project") +
                  ".",
              )
            }
          >
            Start a project conversation ↗
          </button>
        </div>
      </div>
    );
  }

  function renderArtifacts() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">CREATE & REFINE</span>
            <h3>Artifacts</h3>
            <p>From conversation to something you can use.</p>
          </div>
          <button
            type="button"
            className="nx-ws-small-primary"
            onClick={addArtifact}
          >
            ＋ Create artifact
          </button>
        </div>
        <div className="nx-ws-artifact-grid">
          {artifacts.map((artifact) => (
            <button
              type="button"
              key={artifact.id}
              className={
                "nx-ws-artifact-card" +
                (artifact.id === selectedArtifactId ? " is-selected" : "")
              }
              onClick={() => setSelectedArtifactId(artifact.id)}
            >
              <span className="nx-ws-card-icon" aria-hidden="true">
                {artifact.kind === "Code" ? "⌘" : "◫"}
              </span>
              <strong>{artifact.title}</strong>
              <small>
                {artifact.kind} · {artifact.summary}
              </small>
            </button>
          ))}
        </div>
        <div className="nx-ws-artifact-preview">
          <div>
            <span className="nx-ws-overline">ARTIFACT PREVIEW</span>
            <span>{selectedArtifact.kind}</span>
          </div>
          <pre>{selectedArtifact.content}</pre>
        </div>
      </div>
    );
  }

  function renderTools() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">CONNECTED CAPABILITIES</span>
            <h3>Tools & MCP</h3>
            <p>Bring services and custom capabilities into your workflows.</p>
          </div>
          <span className="nx-ws-counter">
            {connectors.filter((connector) => connector.connected).length}{" "}
            enabled
          </span>
        </div>
        <div
          className="nx-ws-filter-tabs"
          role="group"
          aria-label="Filter demo connectors"
        >
          <button
            type="button"
            aria-pressed={connectorFilter === "all"}
            onClick={() => setConnectorFilter("all")}
          >
            All connections
          </button>
          <button
            type="button"
            aria-pressed={connectorFilter === "connected"}
            onClick={() => setConnectorFilter("connected")}
          >
            Enabled
          </button>
        </div>
        <SmallSectionHeading title="INTEGRATIONS" action="Interactive sample" />
        <div className="nx-ws-connector-grid">
          {visibleConnectors
            .filter((connector) => connector.kind === "tool")
            .map((connector) => (
              <div className="nx-ws-connector-card" key={connector.id}>
                <span className="nx-ws-connector-symbol" aria-hidden="true">
                  {connector.symbol}
                </span>
                <div>
                  <strong>{connector.name}</strong>
                  <small>{connector.caption}</small>
                </div>
                <button
                  type="button"
                  aria-label={
                    (connector.connected ? "Disable " : "Enable ") +
                    connector.name +
                    " demo connector"
                  }
                  aria-pressed={connector.connected}
                  className={
                    "nx-ws-connector-switch" +
                    (connector.connected ? " is-enabled" : "")
                  }
                  onClick={() => toggleConnector(connector.id)}
                >
                  <span />
                </button>
              </div>
            ))}
          {visibleConnectors.every((connector) => connector.kind !== "tool") ? (
            <p className="nx-ws-muted">No enabled integrations in this demo.</p>
          ) : null}
        </div>
        <SmallSectionHeading
          title="MCP SERVERS"
          action="Reusable tool interfaces"
        />
        <div className="nx-ws-connector-grid">
          {visibleConnectors
            .filter((connector) => connector.kind === "mcp")
            .map((connector) => (
              <div className="nx-ws-connector-card" key={connector.id}>
                <span className="nx-ws-connector-symbol" aria-hidden="true">
                  {connector.symbol}
                </span>
                <div>
                  <strong>{connector.name}</strong>
                  <small>{connector.caption}</small>
                </div>
                <button
                  type="button"
                  aria-label={
                    (connector.connected ? "Disable " : "Enable ") +
                    connector.name +
                    " demo connector"
                  }
                  aria-pressed={connector.connected}
                  className={
                    "nx-ws-connector-switch" +
                    (connector.connected ? " is-enabled" : "")
                  }
                  onClick={() => toggleConnector(connector.id)}
                >
                  <span />
                </button>
              </div>
            ))}
          {visibleConnectors.every((connector) => connector.kind !== "mcp") ? (
            <p className="nx-ws-muted">No enabled MCP servers in this demo.</p>
          ) : null}
        </div>
        <div className="nx-ws-inline-info">
          ◈ Toggle switches to explore the interface. No third-party connection
          is created.
        </div>
      </div>
    );
  }

  function renderAgents() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">FROM INTENT TO OUTCOME</span>
            <h3>AI agents</h3>
            <p>Orchestrate a goal with tools, checkpoints, and review.</p>
          </div>
          <span className="nx-ws-counter">Workflow studio</span>
        </div>
        <div className="nx-ws-agent-grid">
          <button
            type="button"
            aria-pressed={selectedAgent === "research"}
            className={
              "nx-ws-agent-card" +
              (selectedAgent === "research" ? " is-selected" : "")
            }
            onClick={() => {
              setSelectedAgent("research");
              setAgentStep(0);
            }}
          >
            <span>✧</span>
            <strong>Research assistant</strong>
            <small>Gather, compare, summarize</small>
          </button>
          <button
            type="button"
            aria-pressed={selectedAgent === "delivery"}
            className={
              "nx-ws-agent-card" +
              (selectedAgent === "delivery" ? " is-selected" : "")
            }
            onClick={() => {
              setSelectedAgent("delivery");
              setAgentStep(0);
            }}
          >
            <span>⌘</span>
            <strong>Delivery coordinator</strong>
            <small>Plan, request review, report</small>
          </button>
        </div>
        <div className="nx-ws-agent-flow">
          <div className="nx-ws-agent-flow-top">
            <span>WORKFLOW PREVIEW</span>
            <span>
              {selectedAgent === "research"
                ? "Research assistant"
                : "Delivery coordinator"}
            </span>
          </div>
          <div className="nx-ws-agent-steps">
            {AGENT_STEPS.map((step, index) => (
              <div
                className={
                  "nx-ws-agent-step" +
                  (agentStep >= index + 1 ? " is-complete" : "")
                }
                key={step}
              >
                <span>{agentStep >= index + 1 ? "✓" : "0" + (index + 1)}</span>
                <strong>{step}</strong>
              </div>
            ))}
          </div>
          <div className="nx-ws-agent-flow-bottom">
            <p>
              {agentStep === 0
                ? "Choose a sample agent and step through its workflow."
                : agentStep === 1
                  ? "The goal has been scoped. Next: draft a plan."
                  : agentStep === 2
                    ? "The plan is ready for human review."
                    : agentStep === 3
                      ? "A sample approval is recorded. Next: verify the outcome."
                      : "Sample workflow complete. No real tools were executed."}
            </p>
            <button
              type="button"
              className="nx-ws-small-primary"
              onClick={() =>
                setAgentStep((current) => (current === 4 ? 0 : current + 1))
              }
            >
              {agentStep === 0
                ? "Start sample workflow ↗"
                : agentStep === 4
                  ? "Run again ↻"
                  : agentStep === 2
                    ? "Approve sample step ✓"
                    : "Continue demo ↗"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderFiles() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">YOUR KNOWLEDGE</span>
            <h3>File library</h3>
            <p>Organize files now. Use them in richer AI workflows.</p>
          </div>
          <button
            type="button"
            className="nx-ws-small-primary"
            onClick={() => fileRef.current?.click()}
          >
            ＋ Select local file
          </button>
        </div>
        <div className="nx-ws-file-list">
          {[
            ...localFiles.map((name) => ({
              name,
              detail: "Selected locally · not uploaded",
              symbol: "▤",
            })),
            {
              name: "Brand guidelines.pdf",
              detail: "Illustrative document",
              symbol: "▤",
            },
            {
              name: "Launch roadmap.md",
              detail: "Illustrative document",
              symbol: "⌘",
            },
            {
              name: "Customer insights.csv",
              detail: "Illustrative dataset",
              symbol: "▦",
            },
          ].map((file, index) => (
            <div className="nx-ws-file-row" key={index + "-" + file.name}>
              <span className="nx-ws-file-icon" aria-hidden="true">
                {file.symbol}
              </span>
              <div>
                <strong>{file.name}</strong>
                <small>{file.detail}</small>
              </div>
              <span className="nx-ws-muted" aria-hidden="true">
                ↗
              </span>
            </div>
          ))}
        </div>
        <div className="nx-ws-inline-info">
          Files selected in this preview stay in your browser. No content is
          uploaded.
        </div>
      </div>
    );
  }

  function renderModels() {
    return (
      <div className="nx-ws-scroll-area">
        <div className="nx-ws-view-heading">
          <div>
            <span className="nx-ws-overline">MODEL INDEPENDENCE</span>
            <h3>AI models</h3>
            <p>Choose the right model for the work in front of you.</p>
          </div>
          <span className="nx-ws-counter">Multi-provider</span>
        </div>
        <SmallSectionHeading
          title="SELECT A SAMPLE MODEL"
          action="Shared with composer"
        />
        <div className="nx-ws-model-list">
          {MODELS.map((model) => (
            <button
              type="button"
              className={
                "nx-ws-model-row" + (modelId === model.id ? " is-selected" : "")
              }
              aria-pressed={modelId === model.id}
              onClick={() => setModelId(model.id)}
              key={model.id}
            >
              <span className="nx-ws-model-avatar" aria-hidden="true">
                {model.symbol}
              </span>
              <span>
                <strong>{model.label}</strong>
                <small>{model.provider}</small>
              </span>
              <span className="nx-ws-model-check">
                {modelId === model.id ? "✓ Selected" : "Choose ↗"}
              </span>
            </button>
          ))}
        </div>
        <div className="nx-ws-byok-panel">
          <span aria-hidden="true">◇</span>
          <div>
            <strong>Bring your own key</strong>
            <p>
              Organization-managed provider credentials, model catalogs, and
              RBAC. No keys or real accounts are accessed in this preview.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="nx-ws-text-action"
          onClick={() => navigateTo("chat")}
        >
          Continue in sample chat ↗
        </button>
      </div>
    );
  }

  function viewTitle(): string {
    switch (view) {
      case "chat":
        return selectedConversation ? "Conversation" : "New conversation";
      case "projects":
        return "Projects";
      case "artifacts":
        return "Artifacts";
      case "tools":
        return "Tools & MCP";
      case "agents":
        return "Agents";
      case "files":
        return "File library";
      case "models":
        return "AI models";
    }
  }

  return (
    <div
      className="nx-next-workspace"
      aria-label="Interactive NEXUS product preview"
    >
      <div className="nx-ws-windowbar">
        <span className="nx-ws-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="nx-ws-window-title">
          NEXUS <span>/</span> WORKSPACE
        </span>
        <span className="nx-ws-demo-tag">
          <span aria-hidden="true">●</span> INTERACTIVE DEMO
        </span>
      </div>
      <div className="nx-ws-layout">
        <aside className="nx-ws-sidebar" aria-label="Preview navigation">
          <div className="nx-ws-sidebar-brand">
            <span aria-hidden="true">✧</span>
            <div>
              <strong>NEXUS</strong>
              <small>INTELLIGENT WORKSPACE</small>
            </div>
          </div>
          <button type="button" className="nx-ws-new-chat" onClick={newChat}>
            ＋ New chat <span aria-hidden="true">↗</span>
          </button>
          <button
            type="button"
            className="nx-ws-sidebar-search-toggle"
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen((open) => !open)}
          >
            <span aria-hidden="true">⌕</span> Search conversations{" "}
            <small>⌘ K</small>
          </button>
          {searchOpen ? (
            <div className="nx-ws-sidebar-search">
              <label htmlFor="nx-ws-search" className="nx-ws-hidden">
                Search demo conversations
              </label>
              <input
                id="nx-ws-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search recent..."
              />
            </div>
          ) : null}
          <SmallSectionHeading title="RECENT CONVERSATIONS" />
          <nav
            className="nx-ws-recents"
            aria-label="Sample recent conversations"
          >
            {visibleConversations.map((item) => (
              <button
                type="button"
                key={item.id}
                aria-pressed={
                  view === "chat" && activeConversationId === item.id
                }
                className={
                  view === "chat" && activeConversationId === item.id
                    ? "is-active"
                    : ""
                }
                onClick={() => openConversation(item.id)}
              >
                <span aria-hidden="true">◫</span>
                <span>
                  {item.title}
                  <small>{item.updated}</small>
                </span>
              </button>
            ))}
            {visibleConversations.length === 0 ? (
              <span className="nx-ws-search-empty">
                No matching conversations.
              </span>
            ) : null}
          </nav>
          <SmallSectionHeading title="WORKSPACE" />
          <nav className="nx-ws-nav" aria-label="Demo workspace sections">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={view === item.id}
                className={view === item.id ? "is-active" : ""}
                onClick={() => navigateTo(item.id)}
              >
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
                {item.id === "projects" ? (
                  <small>{projects.length}</small>
                ) : null}
              </button>
            ))}
          </nav>
          <div className="nx-ws-sidebar-bottom">
            <span className="nx-ws-org-icon" aria-hidden="true">
              N
            </span>
            <span>
              <strong>Northstar Workspace</strong>
              <small>Enterprise example</small>
            </span>
            <span aria-hidden="true">⌄</span>
          </div>
        </aside>

        <section className="nx-ws-main" aria-label="Demo workspace content">
          <div className="nx-ws-topbar">
            <div>
              <span>NEXUS / YOUR SPACE</span>
              <strong>{viewTitle()}</strong>
            </div>
            <div className="nx-ws-topbar-actions">
              <span className="nx-ws-private-tag">◇ Private workspace</span>
              <span className="nx-ws-user-avatar" aria-label="Sample user">
                SR
              </span>
            </div>
          </div>
          {view === "chat" ? renderChat() : null}
          {view === "projects" ? renderProjects() : null}
          {view === "artifacts" ? renderArtifacts() : null}
          {view === "tools" ? renderTools() : null}
          {view === "agents" ? renderAgents() : null}
          {view === "files" ? renderFiles() : null}
          {view === "models" ? renderModels() : null}
          {actionNotice ? (
            <div className="nx-ws-notice" role="status">
              <span>{actionNotice}</span>
              <button
                type="button"
                aria-label="Dismiss demo notice"
                onClick={() => setActionNotice(null)}
              >
                ×
              </button>
            </div>
          ) : null}
        </section>
      </div>
      <input
        ref={fileRef}
        className="nx-ws-hidden"
        type="file"
        aria-label="Choose a sample file"
        onChange={pickSampleFile}
      />
      <div className="nx-ws-footer">
        <span>✧ NEXUS CONCEPT WORKSPACE</span>
        <span>
          Model responses are simulated · Connectors and artifacts are
          illustrative · Files stay local
        </span>
      </div>
    </div>
  );
}
