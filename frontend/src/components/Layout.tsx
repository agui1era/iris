import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { useLanguage } from "../i18n/useLanguage";

interface LocationState {
  notice?: string;
}

export function Layout() {
  const { user, logout } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const location = useLocation();
  const notice = (location.state as LocationState | null)?.notice;
  const [dismissedNotice, setDismissedNotice] = useState<string | null>(null);

  const showNotice = notice && notice !== dismissedNotice;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label={t("IRIS centro de monitoreo", "IRIS monitoring center")}>
          <span className="brand-mark" aria-hidden="true">I</span>
          <span>
            IRIS
            <small>CARE VISION</small>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            {t("Monitoreo", "Monitoring")}
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            {t("Historial", "History")}
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            {t("Consulta IA", "AI inquiry")}
          </NavLink>
          {user?.role === "admin" && (
            <NavLink to="/admin" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {t("Administración", "Administration")}
            </NavLink>
          )}
        </nav>
        <div className="user-info">
          <div className="language-switcher" role="group" aria-label={t("Idioma", "Language")}>
            <button
              type="button"
              className={language === "es" ? "active" : ""}
              aria-pressed={language === "es"}
              onClick={() => setLanguage("es")}
            >
              ES
            </button>
            <button
              type="button"
              className={language === "en" ? "active" : ""}
              aria-pressed={language === "en"}
              onClick={() => setLanguage("en")}
            >
              EN
            </button>
          </div>
          <span className="username">{user?.username}</span>
          <span className={`role-badge role-${user?.role}`}>
            {user?.role === "admin" ? t("Administrador", "Administrator") : t("Normal", "Standard")}
          </span>
          <button type="button" className="btn btn-ghost" onClick={logout}>
            {t("Cerrar sesión", "Sign out")}
          </button>
        </div>
      </header>

      {showNotice && (
        <div className="notice-banner" role="alert">
          <span>{notice}</span>
          <button
            type="button"
            className="notice-dismiss"
            aria-label={t("Cerrar aviso", "Dismiss notice")}
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
