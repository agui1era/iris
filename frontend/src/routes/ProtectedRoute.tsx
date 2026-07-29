import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

/** Requires any authenticated user; otherwise redirects to /login. */
export function ProtectedRoute() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <div className="page-loading">Cargando…</div>;
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

  if (user?.role !== "admin") {
    return (
      <Navigate
        to="/"
        replace
        state={{ notice: "No tienes permisos de administrador para ver esa página." }}
      />
    );
  }
  return <Outlet />;
}
