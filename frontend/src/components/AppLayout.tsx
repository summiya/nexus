import { Fragment, type KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { env } from "../config/env";
import { clearSession } from "../features/auth";
import { RecentConversationsMenu } from "./dashboard/RecentConversationsMenu";
import {
  DashboardIcon,
  type DashboardIconName,
} from "./dashboard/DashboardIcon";

import "../styles/nexus-dashboard.css";
import "../styles/nexus-dashboard-pages.css";

interface Destination {
  label: string;
  path: string;
  icon: DashboardIconName;
  group: string;
  terms?: string;
}

const destinations: readonly Destination[] = [
  {
    label: "Overview",
    path: "/workspace",
    icon: "overview",
    group: "Workspace",
    terms: "dashboard home",
  },
  {
    label: "Conversations",
    path: "/conversations",
    icon: "chat",
    group: "Workspace",
    terms: "chat history",
  },
  {
    label: "Projects",
    path: "/projects",
    icon: "projects",
    group: "Workspace",
    terms: "project folder",
  },
  {
    label: "Knowledge bases",
    path: "/knowledge-bases",
    icon: "knowledge",
    group: "Workspace",
    terms: "retrieval rag documents",
  },
  {
    label: "Files",
    path: "/files",
    icon: "files",
    group: "Workspace",
    terms: "uploads documents library",
  },
  {
    label: "Artifacts",
    path: "/artifacts",
    icon: "artifacts",
    group: "Intelligence",
    terms: "code documents previews",
  },
  {
    label: "Agents",
    path: "/agents",
    icon: "agents",
    group: "Intelligence",
    terms: "agentic workflows",
  },
  {
    label: "MCP & tools",
    path: "/tools",
    icon: "tools",
    group: "Intelligence",
    terms: "connectors integration mcp",
  },
  {
    label: "Incidents",
    path: "/incidents",
    icon: "incidents",
    group: "Intelligence",
    terms: "monitoring incident operations",
  },
  {
    label: "Settings",
    path: "/settings/profile",
    icon: "settings",
    group: "Account",
    terms: "account profile",
  },
  {
    label: "Appearance",
    path: "/settings/preferences",
    icon: "preferences",
    group: "Account",
    terms: "theme preferences",
  },
  {
    label: "AI Providers",
    path: "/settings/ai-providers",
    icon: "security",
    group: "Account",
    terms: "provider api keys byok",
  },
];

function currentPage(pathname: string): string {
  if (pathname.startsWith("/conversations/")) return "Conversation";
  if (pathname.startsWith("/settings/ai-models")) return "Model management";
  if (pathname.startsWith("/settings/ai-providers")) return "AI Providers";
  if (pathname.startsWith("/settings/preferences")) return "Appearance";
  if (pathname.startsWith("/settings/usage")) return "Usage";
  if (pathname.startsWith("/settings")) return "Profile";
  return (
    destinations.find((item) => item.path === pathname)?.label ?? "Workspace"
  );
}

function ActiveNavigation({
  closeSidebar,
  logout,
}: {
  closeSidebar: () => void;
  logout: () => void;
}) {
  return (
    <nav className="nx-dash-navigation" aria-label="Main navigation">
      {(["Workspace", "Intelligence", "Account"] as const).map((group) => (
        <div className="nx-dash-nav-group" key={group}>
          <span className="nx-dash-nav-label">{group.toUpperCase()}</span>
          {destinations
            .filter((destination) => destination.group === group)
            .filter(
              (destination) =>
                group !== "Account" ||
                destination.label === "Settings",
            )
            .map((destination) => (
              <Fragment key={destination.path}>
              <NavLink
                to={destination.path}
                end={destination.path !== "/conversations"}
                className={({ isActive }) =>
                  "nx-dash-nav-link" + (isActive ? " active" : "")
                }
                onClick={closeSidebar}
              >
                <DashboardIcon name={destination.icon} />
                <span>{destination.label}</span>
                {destination.label === "Projects" ||
                destination.label === "Knowledge bases" ||
                destination.label === "Agents" ||
                destination.label === "MCP & tools" ||
                destination.label === "Artifacts" ||
                destination.label === "Incidents" ? (
                  <span
                    className="nx-dash-nav-preview"
                    aria-label="Design preview"
                  >
                    ·
                  </span>
                ) : null}
              </NavLink>
              {destination.path === "/conversations" ? (
                <RecentConversationsMenu closeSidebar={closeSidebar} />
              ) : null}
              </Fragment>
            ))}
        </div>
      ))}
      <button
        className="nx-dash-signout"
        type="button"
        onClick={logout}
        aria-label="Logout"
      >
        <DashboardIcon name="logout" />
        <span>Sign out</span>
      </button>
    </nav>
  );
}

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const conversationMode = location.pathname.startsWith("/conversations");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [activeResult, setActiveResult] = useState(0);
  const [profileOpen, setProfileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const paletteInputRef = useRef<HTMLInputElement>(null);

  const normalizedQuery = paletteQuery.trim().toLocaleLowerCase();
  const results = [...destinations, {
    label: "Usage",
    path: "/settings/usage",
    icon: "usage" as const,
    group: "Account",
    terms: "token usage billing",
  }].filter(
    (destination) =>
      normalizedQuery.length === 0 ||
      [destination.label, destination.group, destination.terms ?? ""]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalizedQuery),
  );

  useEffect(() => {
    function onShortcut(event: globalThis.KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteQuery("");
        setActiveResult(0);
        setPaletteOpen((open) => !open);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setProfileOpen(false);
        setSidebarOpen(false);
      }
    }

    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  useEffect(() => {
    if (paletteOpen) paletteInputRef.current?.focus();
  }, [paletteOpen]);

  useEffect(() => {
    setSidebarOpen(false);
    setProfileOpen(false);
    setPaletteOpen(false);
  }, [location.pathname]);

  function closePalette() {
    setPaletteOpen(false);
    setPaletteQuery("");
    setActiveResult(0);
  }

  function openPalette() {
    setProfileOpen(false);
    setPaletteQuery("");
    setActiveResult(0);
    setPaletteOpen(true);
  }

  function visit(path: string) {
    closePalette();
    navigate(path);
  }

  function paletteKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveResult((index) => Math.min(index + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveResult((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && results.length > 0) {
      event.preventDefault();
      visit(results[Math.min(activeResult, results.length - 1)].path);
    }
  }

  function logout() {
    clearSession();
    closePalette();
    setProfileOpen(false);
    navigate("/login", { replace: true });
  }

  return (
    <div
      className={
        "app-shell nexus-dashboard-shell" +
        (conversationMode ? " app-shell-conversations" : "")
      }
    >
      <aside
        className={"nx-dash-sidebar" + (sidebarOpen ? " is-open" : "")}
        aria-label="Workspace sidebar"
      >
        <Link
          to="/workspace"
          className="nx-dash-brand"
          onClick={() => setSidebarOpen(false)}
        >
          <span className="nx-dash-logo" aria-hidden="true">
            ✧
          </span>
          <span className="nx-dash-brand-words">
            <strong>{env.appName}</strong>
            <small>INTELLIGENT WORKSPACE</small>
          </span>
        </Link>
        <div className="nx-dash-sidebar-search">
          <button type="button" onClick={openPalette}>
            <DashboardIcon name="search" size={16} />
            <span>Jump to anything</span>
            <kbd>⌘ K</kbd>
          </button>
        </div>
        <ActiveNavigation
          closeSidebar={() => setSidebarOpen(false)}
          logout={logout}
        />
        <div className="nx-dash-sidebar-footer">
          <span className="nx-dash-org-mark" aria-hidden="true">
            N
          </span>
          <span>
            <strong>NEXUS workspace</strong>
            <small>Organization-scoped</small>
          </span>
          <DashboardIcon name="security" size={16} />
        </div>
      </aside>

      <div className="nx-dash-right">
        <header className="nx-dash-header">
          <div className="nx-dash-breadcrumbs">
            <button
              className="nx-dash-mobile-menu"
              type="button"
              aria-label="Open workspace navigation"
              onClick={() => setSidebarOpen((open) => !open)}
            >
              <DashboardIcon name={sidebarOpen ? "close" : "menu"} />
            </button>
            <Link to="/workspace">Workspace</Link>
            <span aria-hidden="true">/</span>
            <strong>{currentPage(location.pathname)}</strong>
          </div>
          <div className="nx-dash-header-actions">
            <button
              className="nx-dash-jump"
              type="button"
              onClick={openPalette}
            >
              <DashboardIcon name="search" size={17} />
              <span>Jump to anything</span>
              <kbd>⌘ K</kbd>
            </button>
            <span className="nx-dash-workspace-label">SECURE WORKSPACE</span>
            <div className="nx-dash-profile-wrap">
              <button
                type="button"
                className="nx-dash-profile-button"
                aria-label="Open profile menu"
                aria-expanded={profileOpen}
                onClick={() => {
                  setPaletteOpen(false);
                  setProfileOpen((open) => !open);
                }}
              >
                S
              </button>
              {profileOpen ? (
                <div
                  className="nx-dash-profile-popover"
                  role="menu"
                  aria-label="Profile actions"
                >
                  <div className="nx-dash-profile-title">
                    <span>S</span>
                    <div>
                      <strong>My account</strong>
                      <small>Profile and workspace settings</small>
                    </div>
                  </div>
                  <Link
                    to="/settings/profile"
                    role="menuitem"
                    onClick={() => setProfileOpen(false)}
                  >
                    <DashboardIcon name="profile" size={16} /> Profile
                  </Link>
                  <Link
                    to="/settings/preferences"
                    role="menuitem"
                    onClick={() => setProfileOpen(false)}
                  >
                    <DashboardIcon name="preferences" size={16} /> Preferences
                  </Link>
                  <Link
                    to="/settings/usage"
                    role="menuitem"
                    onClick={() => setProfileOpen(false)}
                  >
                    <DashboardIcon name="usage" size={16} /> Usage
                  </Link>
                  <Link
                    to="/settings/ai-providers"
                    role="menuitem"
                    onClick={() => setProfileOpen(false)}
                  >
                    <DashboardIcon name="security" size={16} /> AI Providers
                  </Link>
                  <button type="button" role="menuitem" onClick={logout}>
                    <DashboardIcon name="logout" size={16} /> Sign out
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <main
          className={
            "content-panel nx-dash-content" +
            (conversationMode ? " content-panel-conversations" : "")
          }
        >
          <Outlet />
        </main>
      </div>

      {sidebarOpen ? (
        <button
          className="nx-dash-mobile-overlay"
          type="button"
          aria-label="Close workspace navigation"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      {paletteOpen ? (
        <div className="nx-dash-command-layer">
          <button
            className="nx-dash-command-backdrop"
            type="button"
            aria-label="Close Jump to anything"
            onClick={closePalette}
          />
          <section
            className="nx-dash-command"
            role="dialog"
            aria-modal="true"
            aria-label="Jump to anything"
          >
            <div className="nx-dash-command-search">
              <DashboardIcon name="search" size={21} />
              <input
                ref={paletteInputRef}
                aria-label="Search NEXUS destinations"
                value={paletteQuery}
                onChange={(event) => {
                  setPaletteQuery(event.target.value);
                  setActiveResult(0);
                }}
                onKeyDown={paletteKeyDown}
                placeholder="Jump to conversations, projects, knowledge bases..."
              />
              <button type="button" onClick={closePalette}>
                Esc
              </button>
            </div>
            <div
              className="nx-dash-command-results"
              role="listbox"
              aria-label="Navigation results"
            >
              {results.length === 0 ? (
                <p>No matching destinations.</p>
              ) : (
                results.map((destination, index) => (
                  <button
                    type="button"
                    key={destination.path}
                    role="option"
                    aria-selected={activeResult === index}
                    className={activeResult === index ? "is-current" : ""}
                    onMouseEnter={() => setActiveResult(index)}
                    onClick={() => visit(destination.path)}
                  >
                    <span className="nx-dash-command-icon">
                      <DashboardIcon name={destination.icon} size={19} />
                    </span>
                    <span>
                      <strong>{destination.label}</strong>
                      <small>{destination.group}</small>
                    </span>
                    <DashboardIcon name="arrow" size={16} />
                  </button>
                ))
              )}
            </div>
            <div className="nx-dash-command-footer">
              <span>↑ ↓ Navigate</span>
              <span>↵ Open</span>
              <span>Esc Close</span>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
