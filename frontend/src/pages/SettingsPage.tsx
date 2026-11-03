import { NavLink, Outlet } from "react-router-dom";

import { DashboardIcon } from "../components/dashboard/DashboardIcon";

const sections = [
  { path: "/settings/profile", label: "Profile", icon: "profile" },
  { path: "/settings/preferences", label: "Preferences", icon: "preferences" },
  { path: "/settings/usage", label: "Usage", icon: "usage" },
  { path: "/settings/security", label: "Security", icon: "security" },
  { path: "/settings/ai-providers", label: "AI Providers", icon: "settings" },
] as const;

export function SettingsPage() {
  return (
    <section className="settings-page nx-ui-page">
      <header className="nx-ui-heading settings-heading">
        <div>
          <span className="nx-ui-eyebrow">
            <DashboardIcon name="settings" size={15} /> ACCOUNT & WORKSPACE
          </span>
          <h1>Settings</h1>
          <p>
            Manage your profile, workspace preferences, usage, and organization
            integrations.
          </p>
        </div>
      </header>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <span className="nx-settings-nav-label">PERSONAL</span>
          {sections.slice(0, 3).map((section) => (
            <NavLink key={section.path} to={section.path}>
              <DashboardIcon name={section.icon} size={18} />
              {section.label}
            </NavLink>
          ))}
          <span className="nx-settings-nav-label nx-settings-nav-group-gap">
            ORGANIZATION
          </span>
          {sections.slice(3).map((section) => (
            <NavLink key={section.path} to={section.path}>
              <DashboardIcon name={section.icon} size={18} />
              {section.label}
            </NavLink>
          ))}
          <div className="nx-settings-nav-note">
            <DashboardIcon name="security" size={18} />
            <p>Organization access is enforced by NEXUS permissions.</p>
          </div>
        </nav>
        <div className="settings-content">
          <Outlet />
        </div>
      </div>
    </section>
  );
}
