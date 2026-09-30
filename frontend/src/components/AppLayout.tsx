import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { env } from "../config/env";
import { clearSession } from "../features/auth";

export function AppLayout() {
  const navigate = useNavigate();

  function logout(): void {
    clearSession();
    navigate("/login", { replace: true });
  }

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
          <NavLink to="/conversations">Conversations</NavLink>
          <NavLink to="/files">Files</NavLink>
          <NavLink to="/settings">Settings</NavLink>
          <button type="button" onClick={logout}>
            Logout
          </button>
        </nav>
      </header>

      <main className="content-panel">
        <Outlet />
      </main>
    </div>
  );
}
