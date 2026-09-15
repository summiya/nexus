import { NavLink, Outlet } from 'react-router-dom';

import { env } from '../config/env';

export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="brand-mark" aria-label="Nexus logo">
          N
        </div>
        <div className="brand-copy">
          <strong>{env.appName}</strong>
          <small>Web application foundation</small>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>

      <main className="content-panel">
        <Outlet />
      </main>
    </div>
  );
}
