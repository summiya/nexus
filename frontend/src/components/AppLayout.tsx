import { NavLink, Outlet } from 'react-router-dom';

import { useNexusApp } from '../context/AppContext';

export function AppLayout() {
  const { appName, isLoading, error } = useNexusApp();

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="brand-mark" aria-label="Nexus logo">
          N
        </div>
        <div className="brand-copy">
          <strong>{appName}</strong>
          <small>Web application foundation</small>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>

      {isLoading && <div className="status-banner">Loading foundation state…</div>}
      {error && <div className="status-banner error">{error}</div>}

      <main className="content-panel">
        <Outlet />
      </main>
    </div>
  );
}
