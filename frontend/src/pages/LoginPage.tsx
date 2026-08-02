import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useLanguage } from "../i18n/useLanguage";

interface LocationState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const { user, isLoading, login } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Public route: bounce back to wherever the user was headed (default /)
  // if they're already authenticated.
  if (!isLoading && user) {
    const redirectTo = (location.state as LocationState | null)?.from?.pathname ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("No se pudo iniciar sesión.", "Could not sign in."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={(event) => void handleSubmit(event)}>
        <div className="auth-language" role="group" aria-label={t("Idioma", "Language")}>
          <button type="button" className={language === "es" ? "active" : ""} onClick={() => setLanguage("es")}>ES</button>
          <button type="button" className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button>
        </div>
        <h1 className="auth-title">IRIS</h1>
        <p className="auth-subtitle">{t("Dashboard de monitoreo", "Monitoring dashboard")}</p>

        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        <label className="field">
          <span>{t("Usuario", "Username")}</span>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label className="field">
          <span>{t("Contraseña", "Password")}</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
          {submitting ? t("Ingresando…", "Signing in…") : t("Ingresar", "Sign in")}
        </button>
      </form>
    </div>
  );
}
