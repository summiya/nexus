import { NavLink, Outlet } from "react-router-dom";

export function SettingsPage() {
  return (
    <section className="settings-page">
      <header className="settings-heading">
        <p className="eyebrow">Settings</p>
        <h1>Organization settings</h1>
      </header>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <NavLink to="/settings/ai-providers">AI Providers</NavLink>
        </nav>
        <div className="settings-content">
          <Outlet />
        </div>
      </div>
    </section>
  );
}
