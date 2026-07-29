import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

interface LocationState {
  notice?: string;
}

export function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const notice = (location.state as LocationState | null)?.notice;
  const [dismissedNotice, setDismissedNotice] = useState<string | null>(null);

  const showNotice = notice && notice !== dismissedNotice;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label="IRIS centro de monitoreo">
          <span className="brand-mark" aria-hidden="true">I</span>
          <span>
            IRIS
            <small>CARE VISION</small>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Monitoreo
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Historial
          </NavLink>
          {user?.role === "admin" && (
            <NavLink to="/admin" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              Administración
            </NavLink>
          )}
        </nav>
        <div className="user-info">
          <span className="username">{user?.username}</span>
          <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
          <button type="button" className="btn btn-ghost" onClick={logout}>
            Cerrar sesión
          </button>
        </div>
      </header>

      {showNotice && (
        <div className="notice-banner" role="alert">
          <span>{notice}</span>
          <button
            type="button"
            className="notice-dismiss"
            aria-label="Cerrar aviso"
            onClick={() => setDismissedNotice(notice ?? null)}
          >
            ×
          </button>
        </div>
      )}

      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
