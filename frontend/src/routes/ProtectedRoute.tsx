import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { useLanguage } from "../i18n/useLanguage";

/** Requires any authenticated user; otherwise redirects to /login. */
export function ProtectedRoute() {
  const { user, isLoading } = useAuth();
  const { t } = useLanguage();
  const location = useLocation();

  if (isLoading) {
    return <div className="page-loading">{t("Cargando…", "Loading…")}</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

/**
 * Requires the 'admin' role. Assumes it is nested under <ProtectedRoute />,
 * so `user` is already known to be non-null by the time this renders.
 * Non-admins are bounced to / with a notice banner instead of a blank page.
 */
export function AdminRoute() {
  const { user } = useAuth();
  const { t } = useLanguage();

  if (user?.role !== "admin") {
    return (
      <Navigate
        to="/"
        replace
        state={{ notice: t("No tienes permisos de administrador para ver esa página.", "You do not have administrator permission to view that page.") }}
      />
    );
  }
  return <Outlet />;
}
